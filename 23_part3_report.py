"""
23_part3_report.py — PART 3 report: survivorship fixed. Non-survivorship cohort vs top-500.

WHAT IT DOES
  Compares the newly-enlarged, PnL-NEUTRAL cohort (wallets enumerated by activity, incl.
  losers) against the original top-500-by-PnL winners, and states explicitly which claims
  become possible now that losers and the full distribution are present.

WHAT IT CONSUMES  out/wallet_metrics.csv (full cohort, produced by re-running 11_part2),
                  data/lumid_full.json (the 500 winners, for tagging)
WHAT IT PRODUCES  printed report + out/cohort_labeled.csv (metrics + winner/sampled tag)

DEFINITIONS
  "qualifier" = wallet with >= 30 clean resolved positions (the Part-2 floor).
  "profitable" = clean decomposable realized PnL (pnl_total) > 0. NB this excludes the
                 oversold/CTF bucket by construction (ruling 2) — stated as a caveat.
  group: winner = in lum.id top-500; sampled = enumerated from the fill log (may include
                 a few winners the sampler happened to re-catch — those stay tagged winner).
"""
import os, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def main():
    df = pd.read_csv(os.path.join(OUT, "wallet_metrics.csv"))
    winners = {r["wallet"].lower() for r in json.load(open(os.path.join(HERE, "data", "lumid_full.json")))}
    df["group"] = np.where(df.wallet.str.lower().isin(winners), "winner", "sampled")
    df["profitable"] = df.pnl_total > 0
    df.to_csv(os.path.join(OUT, "cohort_labeled.csv"), index=False)

    def line(name, sub):
        if len(sub) == 0:
            print(f"  {name:10s}: (none)"); return
        print(f"  {name:10s}: n={len(sub):5d}  profitable={sub.profitable.mean():5.1%}  "
              f"median_pnl={sub.pnl_total.median():>12,.0f}  "
              f"median_trading_share={sub.trading_share.median():+.2f}")

    print("=" * 78)
    print("PART 3 — SURVIVORSHIP FIXED: non-survivorship cohort vs top-500 winners")
    print("=" * 78)
    print(f"total qualifiers (>=30 clean resolved positions): {len(df)}")
    print(f"  winners (top-500)  : {(df.group=='winner').sum()}")
    print(f"  sampled (fill log) : {(df.group=='sampled').sum()}")
    print()
    print("profitability + profit source by group:")
    line("ALL", df)
    line("winner", df[df.group == "winner"])
    line("sampled", df[df.group == "sampled"])
    print()
    # the key survivorship point: the sampled group should contain real losers
    samp = df[df.group == "sampled"]
    print(f"LOSERS now visible: {(~df.profitable).sum()} unprofitable qualifiers "
          f"({(~df.profitable).mean():.0%} of cohort) — "
          f"vs the old top-500 view where ~all were winners.")
    print(f"  among sampled: {(~samp.profitable).sum()} losers ({(~samp.profitable).mean():.0%})")
    print()
    # does the Part-2 holder-dominance survive with losers present?
    ts = df.trading_share.dropna()
    print("trading_share across FULL cohort (holder≈0 / trader≈1):")
    print(f"  median={ts.median():+.2f}  p10={ts.quantile(.1):+.2f}  p90={ts.quantile(.9):+.2f}  "
          f"pure_holders(<0.2)={ (ts<0.2).mean():.0%}  pure_traders(>0.8)={(ts>0.8).mean():.0%}")
    print()
    print("CLAIMS NOW POSSIBLE (were not, with winners-only):")
    print("  1. Baselines for persistence: random / median / bottom-decile wallets exist.")
    print("  2. 'What distinguishes winners from losers' — losers are now in-sample.")
    print("  3. Forward-looking rank tests have a full distribution to rank within, not")
    print("     just the survivors, so top-decile performance can be judged vs the field.")
    print()
    print("CAVEAT (carry to Part 5): 'profitable' and trading_share are measured on the")
    print("clean decomposable set; oversold/CTF activity is excluded (ruling 2), so heavy")
    print("market-makers are under-represented here too.")
    print(f"\nwrote out/cohort_labeled.csv")


if __name__ == "__main__":
    main()
