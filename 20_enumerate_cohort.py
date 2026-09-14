"""
20_enumerate_cohort.py — PART 3 (step 1): enumerate a PnL-NEUTRAL candidate wallet pool.

WHY: the existing 278 wallets are lum.id top-500-by-PnL = WINNERS ONLY (survivorship).
Persistence tests and baselines need losers and the full distribution. lum.id cannot
supply losers (capped, winner-sorted), so we enumerate wallets straight from the fill
log, which conditions on TRADING, not on WINNING.

METHOD — time-slice fill sampling:
  Draw N_SLICES timestamps spread across the fill window, pull SLICE_FILLS consecutive
  fills at each, and collect the distinct maker+taker addresses with an APPEARANCE COUNT
  (how many slices each wallet showed up in — a cheap activity proxy used later to
  prioritize reconstruction).

KNOWN SAMPLING PROPERTY (report, don't hide): inclusion probability is ~proportional to
a wallet's fill count, so the pool is activity-weighted — PnL-neutral (the point) but
over-representing high-frequency wallets. Spreading many slices across the whole window
gives moderate-activity wallets a fair chance to be caught too.

CONSUMES: Goldsky orderbook subgraph (live).   PRODUCES: out/candidates.json
"""
import os, json, random, time
import lib_subgraph as sg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "candidates.json")

N_SLICES = 200          # number of time points sampled across the window
SLICE_FILLS = 1000      # fills pulled per slice (subgraph page size)
WINDOW_LO = 1669060209  # 2022-11-21, earliest fill (from calibration)
WINDOW_HI = 1777374040  # 2026-04-28, last fill before the v2 migration cutoff
SEED = 42               # reproducible sampling


def main():
    random.seed(SEED)
    # sample timestamps uniformly across the window; leave headroom before HI so a
    # forward page of SLICE_FILLS still lands inside the window.
    points = sorted(random.randint(WINDOW_LO, WINDOW_HI - 3600) for _ in range(N_SLICES))

    appear = {}     # wallet -> number of slices it appeared in
    total_fills = 0
    t0 = time.time()
    for i, ts in enumerate(points):
        q = ('{ orderFilledEvents(first:%d, orderBy:timestamp, orderDirection:asc,'
             'where:{timestamp_gte:%d}){ maker taker } }' % (SLICE_FILLS, ts))
        d = sg.gq(sg.OB, q)
        if not d:
            continue
        rows = d.get("orderFilledEvents", [])
        total_fills += len(rows)
        seen_here = set()
        for r in rows:
            for w in (r["maker"].lower(), r["taker"].lower()):
                seen_here.add(w)
        for w in seen_here:
            appear[w] = appear.get(w, 0) + 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{N_SLICES} slices, {len(appear)} distinct wallets, {time.time()-t0:.0f}s")

    # sort by appearance count desc (activity proxy)
    ranked = dict(sorted(appear.items(), key=lambda kv: kv[1], reverse=True))
    json.dump({"n_slices": N_SLICES, "slice_fills": SLICE_FILLS, "total_fills": total_fills,
               "appearances": ranked}, open(OUT, "w"))

    # ---- summary ----
    counts = list(ranked.values())
    print("\n" + "=" * 60)
    print("PART 3 step 1 — candidate enumeration")
    print("=" * 60)
    print(f"fills sampled                : {total_fills:,}")
    print(f"distinct candidate wallets   : {len(ranked):,}")
    for k in (1, 2, 3, 5, 10):
        print(f"  appeared in >= {k:2d} slices    : {sum(1 for c in counts if c >= k):,}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
