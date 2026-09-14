"""
32_part4b_consistency.py — PART 4B: is the edge REPEATABLE, or one lucky event?

Persistence (4A) can be produced by ONE huge hit inside the evaluation window, which is
not a repeatable skill. This measures, per holder wallet (continuous measures, not a hard
pass/fail — prediction markets are lumpy and a real specialist may have few big chances):

  profit_concentration : share of total realized PnL from the single largest position,
                         the top-5, and a Herfindahl over per-position PnL. High ⇒ lucky.
  profitable_quarters  : of the (resolution-date) quarters the wallet was active, how many
                         were net profitable?
  median_position_pnl  : is the MEDIAN bet profitable, or is a positive mean just outliers?

POPULATION comes directly from 31_part4a_persistence.py's wallet-level snapshot
(out/part4a_wallet_status.csv): the good_past==True holders at t (trade_holding_rate>=0.5,
avg_position_size>=$10 — the count-based eligibility filter that replaced the old
profit-based trading_share, which was verified to structurally misclassify 91-98% of
behaviorally-active traders as "holders"). Concentration metrics below are computed ONLY on
each wallet's HISTORICAL positions (resolved <= t) — the same side of the 4A split that
good_past was measured on — so nothing from the forward/eval window leaks into them.

KEY TEST: among these good_past holders, do the CONSISTENT ones (low concentration,
profitable median) forward-persist (good_fwd, from 4A) better than the CONCENTRATED ones?
If yes, consistency is the real skill signal, and 4A's persistence isn't just lucky hits.

CONSUMES out/positions.csv, out/part4a_wallet_status.csv, data/clob_market_dates.json
PRODUCES out/part4b_consistency.csv + printed summary
"""
import os, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def main():
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    status = pd.read_csv(os.path.join(OUT, "part4a_wallet_status.csv"))
    md = json.load(open(os.path.join(HERE, "data", "clob_market_dates.json")))

    t = pd.Timestamp(status.t.iloc[0], tz="UTC")
    good_past = status[status.good_past].set_index("wallet")
    print(f"good_past holders from part4a_wallet_status.csv @ t={t.date()}: {len(good_past)}")

    res = pos[(pos.resolved == 1) & (pos.oversold == 0) & pos.wallet.isin(good_past.index)].copy()
    res["res_date"] = pd.to_datetime(res.condition.map(lambda c: md.get(c, {}).get("end")),
                                     errors="coerce", utc=True)
    res = res[res.res_date.notna() & (res.res_date <= t)]     # historical side only, matches good_past
    res["res_q"] = res.res_date.dt.tz_localize(None).dt.to_period("Q")

    recs = []
    for w, g in res.groupby("wallet"):
        p = g.pnl_total.values
        tot = p.sum()
        gross = np.abs(p).sum()
        order = np.sort(p)[::-1]                     # largest positive PnL first
        top1 = order[0]
        top5 = order[:5].sum()
        herf = float(np.sum((np.abs(p) / gross) ** 2)) if gross > 0 else np.nan
        # quarterly profitability (by resolution date)
        q = g.groupby("res_q").pnl_total.sum()
        recs.append({
            "wallet": w, "n_pos": len(p), "total_pnl": tot,
            "median_pos_pnl": float(np.median(p)),
            "top1_share": top1 / tot if tot > 0 else np.nan,   # only meaningful for winners
            "top5_share": top5 / tot if tot > 0 else np.nan,
            "herfindahl": herf,
            "active_quarters": len(q),
            "profitable_quarters": int((q > 0).sum()),
            "profitable_quarter_frac": (q > 0).mean() if len(q) else np.nan,
        })
    df = pd.DataFrame(recs).set_index("wallet")
    df["good_fwd"] = good_past.loc[df.index, "good_fwd"]
    df = df.reset_index()
    df.to_csv(os.path.join(OUT, "part4b_consistency.csv"), index=False)

    win = df[df.total_pnl > 0]     # profitable holders — where concentration is interpretable
    print("=" * 74)
    print(f"PART 4B — CONSISTENCY  (good_past holders from part4a, n={len(df)})")
    print("=" * 74)
    print(f"profitable holders: {len(win)} ({len(win)/len(df):.0%})")
    print("\nProfit concentration among profitable holders (share of total PnL):")
    print(f"  from SINGLE largest position : median {win.top1_share.median():.0%}  "
          f"p90 {win.top1_share.quantile(.9):.0%}")
    print(f"  from top-5 positions         : median {win.top5_share.median():.0%}")
    print(f"  Herfindahl (per-position)    : median {win.herfindahl.median():.3f}  "
          f"(1/n baseline = {1/win.n_pos.median():.3f})")
    print(f"  >50% of profit from ONE bet  : {(win.top1_share>0.5).mean():.0%} of profitable holders")
    print("\nDepth of skill:")
    print(f"  median position PnL > 0      : {(df.median_pos_pnl>0).mean():.0%} of holders "
          f"(rest: positive total is outlier-driven)")
    print(f"  profitable-quarter fraction  : median {df.profitable_quarter_frac.median():.0%}  "
          f"(of active quarters)")
    print(f"  wallets profitable in >=75% of active quarters: {(df.profitable_quarter_frac>=0.75).mean():.0%}")

    # ---------------- KEY TEST: does consistency predict forward persistence? ----------------
    print("\n" + "=" * 74)
    print("KEY TEST — consistent vs. concentrated good_past holders: who persists forward?")
    print("=" * 74)
    win = win.dropna(subset=["top1_share", "median_pos_pnl", "good_fwd"])
    consistent = win[(win.top1_share <= win.top1_share.median()) & (win.median_pos_pnl > 0)]
    concentrated = win[~win.index.isin(consistent.index)]
    print(f"  consistent   (top1_share<=median & median_pos_pnl>0): n={len(consistent)}  "
          f"P(good_fwd)={consistent.good_fwd.mean():.0%}" if len(consistent) else
          "  consistent group: n=0 (no wallets qualify)")
    print(f"  concentrated (everyone else)                        : n={len(concentrated)}  "
          f"P(good_fwd)={concentrated.good_fwd.mean():.0%}" if len(concentrated) else
          "  concentrated group: n=0 (no wallets qualify)")
    print("\nINTERPRETATION: consistent P(good_fwd) meaningfully > concentrated P(good_fwd)")
    print("=> consistency is the real skill signal, not luck. Close/reversed => 4A's persistence")
    print("finding may just be one-lucky-hit wallets getting lucky again.")
    print("wrote out/part4b_consistency.csv")


if __name__ == "__main__":
    main()
