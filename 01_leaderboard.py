"""
Step 1 — Reconstruct an honest leaderboard.

The lum.id leaderboard ranks by `total_pnl`, which is a mark-to-market number:
realized (money from resolved markets) PLUS unrealized (paper marks on open
positions). This script NEVER sums them into one ranking criterion. It:

  - separates realized_pnl (given directly by lum.id) from the implied
    unrealized component (total_pnl - realized_pnl),
  - re-ranks by realized-only,
  - measures how much the ranking reshuffles vs the given (total_pnl) order.

Input : data/lumid_full.json  (raw pull, 500 rows)
Output: out/leaderboard_honest.csv, plus printed summary.

NOTE ON TRUST: we take lum.id's realized_pnl at face value here. Steps 2-3
independently reconstruct realized PnL from the trade log for the analysis
cohort, which lets us cross-check that number rather than trust it blindly.
"""
import json, os
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "data", "lumid_full.json")))
df = pd.DataFrame(raw)

# implied unrealized = mark-to-market total minus realized. We keep it separate
# and NEVER re-sum it into the ranking.
df["unrealized_pnl_implied"] = df["total_pnl"] - df["realized_pnl"]

# ranking as given (by total_pnl) — lum.id 'rank' already encodes this
df = df.sort_values("total_pnl", ascending=False).reset_index(drop=True)
df["rank_total"] = np.arange(1, len(df) + 1)

# honest ranking: realized only
df = df.sort_values("realized_pnl", ascending=False)
df["rank_realized"] = np.arange(1, len(df) + 1)
df = df.sort_values("rank_total").reset_index(drop=True)

df["rank_delta"] = df["rank_realized"] - df["rank_total"]  # + = demoted by honesty

# ---- reshuffle diagnostics ----
def topn_overlap(n):
    a = set(df.sort_values("rank_total").head(n)["wallet"])
    b = set(df.sort_values("rank_realized").head(n)["wallet"])
    return len(a & b), n

print("=" * 70)
print("STEP 1 — HONEST (REALIZED-ONLY) LEADERBOARD vs GIVEN (TOTAL-PNL)")
print("=" * 70)
print(f"wallets: {len(df)}")
print(f"neg realized_pnl among top-PnL wallets : {(df.realized_pnl<0).sum()}")
share_unreal = df.unrealized_pnl_implied.clip(lower=0).sum() / df.total_pnl.clip(lower=0).sum()
print(f"unrealized share of all positive headline PnL : {share_unreal:6.1%}")
print()
print("Top-N membership overlap (given vs honest):")
for n in (10, 25, 50, 100):
    k, n = topn_overlap(n)
    print(f"  top-{n:<3}: {k}/{n} survive  ({(n-k)/n:5.1%} of the club changes)")
print()
# rank correlation
from scipy.stats import spearmanr, kendalltau
rho, _ = spearmanr(df.rank_total, df.rank_realized)
tau, _ = kendalltau(df.rank_total, df.rank_realized)
print(f"Spearman rho(total, realized) = {rho:.3f}   Kendall tau = {tau:.3f}")
print(f"median |rank change| = {df.rank_delta.abs().median():.0f} places;"
      f"  max = {df.rank_delta.abs().max():.0f}")
print()
print("Biggest DEMOTIONS when judged on realized money (paper-gain inflated):")
cols = ["wallet","rank_total","rank_realized","rank_delta","total_pnl",
        "realized_pnl","unrealized_pnl_implied","win_rate","trades","primary_style"]
show = df.sort_values("rank_delta", ascending=False).head(8)[cols]
with pd.option_context("display.width",200,"display.max_columns",20,"display.float_format",lambda x:f"{x:,.0f}"):
    print(show.to_string(index=False))
print()
print("Biggest PROMOTIONS (realized money the headline buried):")
show = df.sort_values("rank_delta").head(8)[cols]
with pd.option_context("display.width",200,"display.max_columns",20,"display.float_format",lambda x:f"{x:,.0f}"):
    print(show.to_string(index=False))

df.to_csv(os.path.join(HERE,"out","leaderboard_honest.csv"), index=False)
print("\nwrote out/leaderboard_honest.csv")
