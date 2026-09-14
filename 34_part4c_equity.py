"""
34_part4c_equity.py — PART 4C: equity-curve shape of each holder's edge.

Build each wallet's CUMULATIVE PnL vs RESOLUTION DATE (profit is realized at settlement;
entry dates would smear timing). Split pnl_holding vs pnl_trading as separate cumulative
lines. Then quantify the temporal shape:

  slope_r2                   R^2 of cumulative PnL on time — steady grind vs lumpy/one-off.
  max_drawdown               worst peak-to-trough of the cumulative curve.
  recent_vs_historical_slope slope over last 6 months / full-history slope — EDGE-DECAY
                             detector (a wallet may have earned it all long ago).

Classify shapes: steady_climber / one_jump / decayed / volatile_rising / flat_or_down, and
report how many wallets and what share of cohort profit each holds.

CAUTION: holders' resolutions are lumpy by nature, so smoothness is compared WITHIN
bet-frequency terciles, not against the whole cohort (else we'd just favour high-frequency
wallets — exactly the population that isn't followable).

Eligibility uses the same count-based trade_holding_rate filter as 4A (>=0.5, avg_position_size
>=$10) — replaces the earlier profit-based trading_share filter, which was verified to
structurally misclassify 91-98% of behaviorally-active traders as "holders".

top1_share (one-jump signature) is computed HERE, on 4C's own holder population, rather than
pulled from 4B — 4B's population is now the narrower good_past pool from 4A's snapshot (252
wallets), which covers only ~15% of 4C's ~1600 eligible holders and would leave the rest
unclassifiable as one_jump.

CONSUMES out/positions.csv, out/wallet_metrics.csv, data/clob_market_dates.json
PRODUCES out/part4c_equity.csv + printed summary + out/equity_examples.png
"""
import os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
HOLD_RATE_THRESHOLD = 0.5     # min trade_holding_rate (count-based, replaces trading_share) — 4A's primary
MIN_POS = 30
MIN_AVG_POSITION_SIZE = 10    # $ floor excluding economically-negligible micro-betting wallets


def curve_stats(g):
    """g: one wallet's resolved positions with res_date + pnl. Return shape metrics."""
    g = g.sort_values("res_date")
    t = (g.res_date - g.res_date.min()).dt.total_seconds().values / 86400.0  # days
    cum = np.cumsum(g.pnl_total.values)
    if len(t) < 5 or t[-1] <= 0:
        return None
    # linear fit R^2 of cumulative curve on time
    A = np.vstack([t, np.ones_like(t)]).T
    coef, *_ = np.linalg.lstsq(A, cum, rcond=None)
    pred = A @ coef
    ss_res = np.sum((cum - pred) ** 2)
    ss_tot = np.sum((cum - cum.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    # max drawdown of cumulative curve
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    # recent (last 182d) vs historical slope
    total_slope = coef[0]
    cut = t[-1] - 182
    recent = t >= cut
    rec_slope = np.nan
    if recent.sum() >= 3 and (t[recent][-1] - t[recent][0]) > 0:
        rec_slope = np.polyfit(t[recent], cum[recent], 1)[0]
    top1_share = g.pnl_total.max() / cum[-1] if cum[-1] > 0 else np.nan
    return {"n": len(t), "span_days": t[-1], "total_pnl": cum[-1],
            "slope_r2": r2, "max_drawdown": dd, "hist_slope": total_slope,
            "recent_slope": rec_slope, "top1_share": top1_share,
            "recent_vs_hist": (rec_slope / total_slope) if (total_slope not in (0, np.nan) and total_slope != 0) else np.nan}


def classify(row):
    """Rule-based shape label."""
    if row.total_pnl <= 0:
        return "flat_or_down"
    if pd.notna(row.top1_share) and row.top1_share > 0.6:
        return "one_jump"                         # >60% of profit from a single position
    if row.slope_r2 >= 0.9:
        return "steady_climber"
    if pd.notna(row.recent_vs_hist) and row.recent_vs_hist < 0.25:
        return "decayed"                          # recent slope << historical
    return "volatile_rising"


def main():
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    wm = pd.read_csv(os.path.join(OUT, "wallet_metrics.csv"))
    md = json.load(open(os.path.join(HERE, "data", "clob_market_dates.json")))

    trade_holding_rate = wm.n_hold_positions / wm.n_positions
    holders = set(wm[(trade_holding_rate >= HOLD_RATE_THRESHOLD) & (wm.n_positions >= MIN_POS)
                     & (wm.avg_position_size >= MIN_AVG_POSITION_SIZE)].wallet)
    res = pos[(pos.resolved == 1) & (pos.oversold == 0) & pos.wallet.isin(holders)].copy()
    res["res_date"] = pd.to_datetime(res.condition.map(lambda c: md.get(c, {}).get("end")),
                                     errors="coerce", utc=True)
    res = res.dropna(subset=["res_date"])

    recs = []
    for w, g in res.groupby("wallet"):
        s = curve_stats(g)
        if s is None:
            continue
        s["wallet"] = w
        s["shape"] = classify(pd.Series(s))
        recs.append(s)
    df = pd.DataFrame(recs)
    # bet-frequency terciles (positions per active day) for the smoothness caution
    df["freq"] = df.n / df.span_days.replace(0, np.nan)
    df["freq_tier"] = pd.qcut(df.freq, 3, labels=["low", "mid", "high"])
    df.to_csv(os.path.join(OUT, "part4c_equity.csv"), index=False)

    print("=" * 70)
    print(f"PART 4C — EQUITY-CURVE SHAPES (directional holders, n={len(df)})")
    print("=" * 70)
    tot_profit = df[df.total_pnl > 0].total_pnl.sum()
    print(f"{'shape':16s} {'wallets':>8} {'% wallets':>10} {'% cohort profit':>16}")
    for sh in ["steady_climber", "volatile_rising", "one_jump", "decayed", "flat_or_down"]:
        sub = df[df["shape"] == sh]
        prof = sub[sub.total_pnl > 0].total_pnl.sum()
        print(f"{sh:16s} {len(sub):>8} {len(sub)/len(df):>9.0%} {prof/tot_profit:>15.0%}")
    print()
    print(f"median slope_R^2 (steady-grind measure): {df.slope_r2.median():.2f}  "
          f"(1.0 = perfectly steady; low = lumpy)")
    print("  by bet-frequency tercile (smoothness rises with frequency — the caution):")
    for tier in ["low", "mid", "high"]:
        s = df[df.freq_tier == tier]
        print(f"    {tier:4s} freq: median R^2 {s.slope_r2.median():.2f}  (n={len(s)})")
    dec = df[df["shape"] == "decayed"]
    print(f"\nEDGE-DECAY: {len(dec)} wallets ({len(dec)/len(df):.0%}) earned it mostly >6mo ago "
          f"(recent slope <25% of historical) — following them would chase a stale edge.")

    # example curves: 4 profitable holders across shapes
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    picks = {}
    for sh in ["steady_climber", "volatile_rising", "one_jump", "decayed"]:
        cand = df[(df["shape"] == sh) & (df.total_pnl > 0)].sort_values("total_pnl", ascending=False)
        if len(cand):
            picks[sh] = cand.iloc[0].wallet
    for ax, (sh, w) in zip(axes.ravel(), picks.items()):
        g = res[res.wallet == w].sort_values("res_date")
        ax.plot(g.res_date, np.cumsum(g.pnl_total.values), label="total", lw=2)
        ax.plot(g.res_date, np.cumsum(g.pnl_holding.fillna(0).values), label="holding", ls="--", alpha=.7)
        ax.plot(g.res_date, np.cumsum(g.pnl_trading.values), label="trading", ls=":", alpha=.7)
        ax.set_title(f"{sh}  ({w[:8]}…)"); ax.legend(fontsize=7); ax.tick_params(labelsize=7)
    fig.suptitle("Part 4C — example equity curves vs resolution date")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "equity_examples.png"), dpi=110)
    print("wrote out/part4c_equity.csv + out/equity_examples.png")


if __name__ == "__main__":
    main()
