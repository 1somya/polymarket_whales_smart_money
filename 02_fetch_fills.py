"""
Phase A — fetch & cache order fills for the target cohort (parallel I/O).

Separated from reconstruction because fill-fetching is the slow, network-bound step
and parallelizes well, while reconstruction/resolution is fast and serial.

Target cohort: leaderboard wallets ranked by total_pnl, EXCLUDING
  - post-cutoff wallets (first_trade > 2026-04-28): invisible to the legacy subgraph;
  - bot-scale wallets (lum.id trades > BOT_SKIP): too many fills to pull.
Fills are capped at FILL_CAP DISTINCT ORDERS (not raw fills — see lib_subgraph.fetch_fills);
wallets that hit the cap are flagged truncated and are kept only for descriptive typing,
not the clean clustering cohort.
"""
import json, os, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
import lib_subgraph as sg

HERE = os.path.dirname(os.path.abspath(__file__))
CUTOFF = dt.datetime(2026, 4, 28, tzinfo=dt.timezone.utc)
BOT_SKIP = 250_000
FILL_CAP = 8_000
WORKERS = 6

def first_trade(r):
    return dt.datetime.fromisoformat(r["first_trade_at"].replace("Z", "+00:00"))

def targets(top_n):
    board = sorted(json.load(open(os.path.join(HERE, "data", "lumid_full.json"))),
                   key=lambda r: -r["total_pnl"])[:top_n]
    out = []
    for r in board:
        if first_trade(r) > CUTOFF:      # invisible to subgraph
            continue
        if r["trades"] > BOT_SKIP:       # bot-scale, skip fetch
            continue
        out.append(r["wallet"])
    return out

def one(w):
    fp = os.path.join(sg.DATA, "fills", f"{w.lower()}.json")
    if os.path.exists(fp):
        o = json.load(open(fp)); return w, len(o["fills"]), o["truncated"], "cached"
    try:
        fills, tr = sg.fetch_fills(w, cap=FILL_CAP)
        return w, len(fills), tr, "ok"
    except sg.FetchError as e:
        return w, 0, None, f"FAIL:{e}"

def main(top_n=350):
    ws = targets(top_n)
    print(f"target cohort: {len(ws)} wallets (top {top_n} by total_pnl, minus post-cutoff & bot-scale)")
    t0 = time.time(); done = 0; tot_fills = 0; fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(one, w): w for w in ws}
        for fu in as_completed(futs):
            w, n, tr, st = fu.result()
            done += 1; tot_fills += n
            if st.startswith("FAIL"): fails.append(w)
            if done % 10 == 0 or st.startswith("FAIL"):
                rate = tot_fills / max(time.time() - t0, 1)
                print(f"[{done}/{len(ws)}] {w[:10]} fills={n:>6} trunc={tr} {st}  "
                      f"| {tot_fills:,} fills, {rate:.0f}/s, {time.time()-t0:.0f}s", flush=True)
    print(f"DONE fetch: {done} wallets, {tot_fills:,} fills, {time.time()-t0:.0f}s, fails={len(fails)}")
    if fails:
        json.dump(fails, open(os.path.join(HERE, "data", "fetch_fails.json"), "w"))

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 350)
