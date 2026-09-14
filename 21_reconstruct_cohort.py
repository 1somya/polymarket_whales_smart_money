"""
21_reconstruct_cohort.py — PART 3 (step 2): reconstruct candidates, keep >=30-resolved.

REVISED after calibration showed the hyperactive tier is a cost sink (median 12k fills,
many truncated at 40k, all MM/trader — the non-followable population). Two changes:
  - FILL_CAP lowered to 8,000 for the cohort scan: a moderate holder with >=30 resolved
    positions sits well under this, so followable wallets are captured COMPLETE; only
    hyperactive wallets truncate (flagged, and they obviously qualify anyway).
    NOTE: lib_subgraph.fetch_fills now counts FILL_CAP in DISTINCT ORDERS (via orderHash),
    not raw fills — a moderate holder places far fewer than 8,000 orders either way, so the
    "captured complete" guarantee still holds; true MM/hyperactive wallets now need far more
    raw fill volume to hit the same cap, since one resting order can span many fills.
  - FETCH is PARALLEL (network-bound; per-wallet cache files are thread-safe). Token
    resolution + position counting run single-threaded afterward (shared cache files
    tok2cond/cond_payout are NOT safe for concurrent writes).

Modes:
  calibrate <N>  : parallel-fetch a stratified sample, report >=30-resolved hit rate +
                   speed per appearance tier, so the full run can be sized.
  full <HI> <MID> <LO> : fetch that many from each tier (random within tier), then count.

CONSUMES: out/candidates.json + Goldsky subgraph.  PRODUCES: out/cohort_qualifiers.json
"""
import os, sys, json, time, random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import lib_subgraph as sg
import lib_recon as rec
import lib_decompose as dec

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(HERE, "out", "candidates.json")
OUTQ = os.path.join(HERE, "out", "cohort_qualifiers.json")
MIN_RESOLVED = 30
FILL_CAP = 8000        # per-wallet DISTINCT-ORDER ceiling for the cohort scan (see docstring)
FETCH_WORKERS = 8      # parallel network fetchers
SEED = 42


def fetch_one(w):
    """Network-bound: pull+cache a wallet's fills (thread-safe, per-wallet file)."""
    try:
        fills, truncated = sg.fetch_fills(w, cap=FILL_CAP)
        return w, len(fills), truncated, None
    except sg.FetchError:
        return w, 0, False, "fetch_error"


def count_resolved(w):
    """Single-threaded: count >=net-long resolved positions from cached fills."""
    fills, truncated = sg.fetch_fills(w, cap=FILL_CAP)
    norm = [n for f in fills if (n := sg.normalize(f, w))]
    if not norm:
        return 0, 0, truncated
    tokens = sorted({n["token"] for n in norm})
    tok2cond, cond = rec.resolve_tokens(tokens)
    by_token = defaultdict(list)
    for n in norm:
        by_token[n["token"]].append(n)
    n_res = sum(1 for t, fl in by_token.items()
                if sum(x["size"] for x in fl if x["side"] == "BUY") > dec.HELD_TOKEN_EPS
                and cond.get(tok2cond.get(t), {}).get("resolved"))
    return n_res, len(norm), truncated


def tiers_excluding_cached():
    data = json.load(open(CAND))
    appear = data["appearances"]
    already = {f[:-5] for f in os.listdir(os.path.join(sg.DATA, "fills"))}
    T = {"hi": [], "mid": [], "lo": []}
    for w, c in appear.items():
        if w in already:
            continue
        (T["hi"] if c >= 5 else T["mid"] if c >= 3 else T["lo"]).append(w)
    return T


def run(sample_map):
    """sample_map: {tier: [wallets]}. Parallel-fetch all, then count sequentially."""
    all_w = [w for lst in sample_map.values() for w in lst]
    tier_of = {w: t for t, lst in sample_map.items() for w in lst}
    print(f"parallel-fetching {len(all_w)} wallets @ {FETCH_WORKERS} workers, cap={FILL_CAP}...")
    t0 = time.time()
    fetched, ferr = 0, 0
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        for i, fut in enumerate(as_completed([ex.submit(fetch_one, w) for w in all_w])):
            w, nf, trunc, err = fut.result()
            if err:
                ferr += 1
            else:
                fetched += 1
            if (i + 1) % 200 == 0:
                print(f"  fetched {i+1}/{len(all_w)}  ({ferr} errors)  {time.time()-t0:.0f}s")
    print(f"fetch done: {fetched} ok, {ferr} errors, {time.time()-t0:.0f}s")

    print("counting resolved positions (single-threaded)...")
    per_tier = defaultdict(lambda: {"n": 0, "qual": 0, "fills": 0, "trunc": 0})
    quals = {}
    for w in all_w:
        try:
            nres, nf, trunc = count_resolved(w)
        except sg.FetchError:
            continue
        d = per_tier[tier_of[w]]
        d["n"] += 1; d["fills"] += nf; d["trunc"] += int(trunc)
        if nres >= MIN_RESOLVED:
            d["qual"] += 1
            quals[w] = {"n_resolved": nres, "n_fills": nf, "truncated": trunc, "tier": tier_of[w]}
    for t, d in per_tier.items():
        if d["n"]:
            print(f"  {t:3s}: scanned={d['n']:5d}  >=30-resolved={d['qual']:5d} "
                  f"({d['qual']/d['n']:4.0%})  avg_fills={d['fills']/d['n']:6.0f}  trunc={d['trunc']}")
    return quals


if __name__ == "__main__":
    random.seed(SEED)
    mode = sys.argv[1] if len(sys.argv) > 1 else "calibrate"
    T = tiers_excluding_cached()
    print("pool sizes (excluding already-cached):",
          {k: len(v) for k, v in T.items()})
    for lst in T.values():
        random.shuffle(lst)

    if mode == "calibrate":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        per = n // 3
        run({t: T[t][:per] for t in T})
    elif mode == "full":
        hi = int(sys.argv[2]); mid = int(sys.argv[3]); lo = int(sys.argv[4])
        quals = run({"hi": T["hi"][:hi], "mid": T["mid"][:mid], "lo": T["lo"][:lo]})
        json.dump(quals, open(OUTQ, "w"))
        print(f"\nwrote {OUTQ}  ({len(quals)} qualifiers, >= {MIN_RESOLVED} resolved)")
