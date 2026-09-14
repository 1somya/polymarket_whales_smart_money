"""
33_part4d_decay.py — PART 4D: does the edge DECAY with horizon? Half-life of "top wallet".

Same cumulative-rank / disjoint-forward design as 4A, evaluated at horizons t+1, t+3, t+6
months. Uses 4A's PERSISTENCE-RATE test, not a rank correlation: "does a wallet's edge
persist" is a claim about an individual wallet conditional on it having an edge, not about
whether relative rank is preserved across the whole population. A prior version of this file
used Spearman rank correlation between historical rank and forward ROI — the same
population-wide-correlation approach 4A tried and explicitly rejected (see 4A's docstring)
because it answers a different, broader question than what these files claim to test. Removed
here for the same reason and replaced with P(good_fwd | good_past) at each horizon, exactly
as 4A computes it for its single 3-month window. If that gap shrinks toward the P(good_fwd)
baseline as horizon grows, the edge is fading; the horizon where it halves is the approximate
half-life.

Eligibility uses the same count-based trade_holding_rate filter as 4A (>=0.5, avg_position_size
>=$10) — replaces the earlier profit-based trading_share filter, which was verified to
structurally misclassify 91-98% of behaviorally-active traders as "holders".

CONSUMES out/positions.csv, data/clob_market_dates.json
PRODUCES out/part4d_decay.csv + printed summary
"""
import os, json
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
GRID = pd.date_range("2025-07-01", "2026-01-01", freq="MS", tz="UTC")  # leave room for +6mo eval
HORIZONS = [1, 3, 6]                 # months
MIN_HIST_POSITIONS = 30
MIN_FWD_POSITIONS = 3
HOLD_RATE_THRESHOLD = 0.5     # min trade_holding_rate (count-based, replaces trading_share) — 4A's primary
MIN_AVG_POSITION_SIZE = 10    # $ floor excluding economically-negligible micro-betting wallets
MIN_GROUP_SIZE = 15           # min wallets in EACH of good_past/bad_past to trust a persistence rate
EDGE_METRIC = "holding_excess_return"   # 4A's strongest metric


def wallet_aggregates(df):
    g = df.groupby("wallet")
    n = g.size()
    avg_position_size = g.buy_usd.sum() / n
    h = df[(df.hedged == 0) & (df.tokens_held_to_res > 0) & df.direction_correct.notna()]
    hg = h.groupby("wallet")
    her = hg.pnl_holding_settle.sum() / hg.usd_held.sum().replace(0, np.nan)
    trade_holding_rate = hg.size().reindex(n.index, fill_value=0) / n
    return pd.DataFrame({"n": n, "avg_position_size": avg_position_size,
                         "trade_holding_rate": trade_holding_rate, EDGE_METRIC: her})


def forward(df):
    g = df.groupby("wallet")
    fwd_buy = g.buy_usd.sum()
    return pd.DataFrame({"fwd_n": g.size(), "fwd_roi": g.pnl_total.sum() / fwd_buy.replace(0, np.nan)})


def main():
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    md = json.load(open(os.path.join(HERE, "data", "clob_market_dates.json")))
    res = pos[(pos.resolved == 1) & (pos.oversold == 0)].copy()
    res["res_date"] = pd.to_datetime(res.condition.map(lambda c: md.get(c, {}).get("end")),
                                     errors="coerce", utc=True)
    res = res[res.res_date.notna()]

    rows = []
    for t in GRID:
        hist = wallet_aggregates(res[res.res_date <= t])
        hist = hist[(hist.n >= MIN_HIST_POSITIONS) & (hist.trade_holding_rate >= HOLD_RATE_THRESHOLD)
                    & (hist.avg_position_size >= MIN_AVG_POSITION_SIZE)]
        for h in HORIZONS:
            t_end = t + pd.DateOffset(months=h)
            fwd = forward(res[(res.res_date > t) & (res.res_date <= t_end)])
            J = hist.join(fwd, how="inner")
            J = J[J.fwd_n >= MIN_FWD_POSITIONS].dropna(subset=[EDGE_METRIC, "fwd_roi"])
            if len(J) < 20:
                continue
            good_past = J[EDGE_METRIC] > 0
            good_fwd = J.fwd_roi > 0
            n_good_past = int(good_past.sum())
            n_bad_past = int((~good_past).sum())
            if n_good_past < MIN_GROUP_SIZE or n_bad_past < MIN_GROUP_SIZE:
                continue    # too few wallets in one of the two groups to trust a rate
            p_good_given_good = good_fwd[good_past].mean()
            p_good_given_bad = good_fwd[~good_past].mean()
            p_good_baseline = good_fwd.mean()
            table = pd.crosstab(good_past, good_fwd)
            gap_p = chi2_contingency(table)[1] if table.shape == (2, 2) else np.nan
            cut = J[EDGE_METRIC].quantile(0.9)
            rows.append({
                "t": t.date(), "eval_end": t_end.date(), "horizon_m": h,
                "n": len(J), "n_good_past": n_good_past, "n_bad_past": n_bad_past,
                "p_good_fwd_given_good_past": p_good_given_good,
                "p_good_fwd_given_bad_past": p_good_given_bad,
                "p_good_fwd_baseline": p_good_baseline,
                "gap_p_value": gap_p,
                "top_decile_fwd_roi": J[J[EDGE_METRIC] >= cut].fwd_roi.median(),
                "median_fwd_roi": J.fwd_roi.median(),
            })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "part4d_decay.csv"), index=False)

    print("=" * 90)
    print(f"PART 4D — EDGE DECAY (rank by {EDGE_METRIC}, trade_holding_rate>={HOLD_RATE_THRESHOLD}, "
          f"avg_position_size>=${MIN_AVG_POSITION_SIZE})")
    print("=" * 90)
    print(f"{'horizon':>8} {'P(good|good_past)':>18} {'P(good|bad_past)':>17} {'baseline':>9} "
          f"{'gap':>7} {'frac p<.05':>11} {'top_dec_ROI':>12} {'edge_vs_median':>15}")
    base_gap = None
    for h in HORIZONS:
        s = df[df.horizon_m == h]
        if len(s) == 0:
            print(f"{h:>6}m  (no windows with enough wallets)")
            continue
        p_good = s.p_good_fwd_given_good_past.mean()
        p_bad = s.p_good_fwd_given_bad_past.mean()
        p_base = s.p_good_fwd_baseline.mean()
        gap = p_good - p_bad
        edge = (s.top_decile_fwd_roi - s.median_fwd_roi).mean()
        if h == HORIZONS[0]:
            base_gap = gap
        print(f"{h:>6}m  {p_good:>17.0%} {p_bad:>17.0%} {p_base:>9.0%} {gap:>+7.0%} "
              f"{(s.gap_p_value<0.05).mean():>10.0%} {s.top_decile_fwd_roi.mean():>12.3f} {edge:>+15.3f}")
    print("\n(if the good_past/bad_past gap shrinks toward 0 as horizon grows, the edge is decaying;")
    print(" the horizon where the gap is ~half of the 1-month gap is the approximate half-life.)")
    if base_gap:
        for h in HORIZONS[1:]:
            s = df[df.horizon_m == h]
            if len(s) == 0:
                continue
            gap = (s.p_good_fwd_given_good_past - s.p_good_fwd_given_bad_past).mean()
            print(f"  {h}m gap is {gap/base_gap:.0%} of the {HORIZONS[0]}m gap")
    print("wrote out/part4d_decay.csv")


if __name__ == "__main__":
    main()
