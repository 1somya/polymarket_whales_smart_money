
"""
31_part4a_persistence.py — PART 4A: does a wallet's edge PERSIST out-of-sample?

THE DESIGN (cumulative historical window, disjoint forward eval — never overlap):
  for each month t in a grid:
    MEASURE each wallet on ALL positions resolved THROUGH t   (cumulative => enough sample;
           holders resolve slowly, so cumulative avoids starving early windows)
    EVALUATE those wallets on positions resolved in (t, t+EVAL_MONTHS]  (DISJOINT => genuinely
           out-of-sample; a position resolved after t contributed nothing to the historical side)
  Cumulative HISTORICAL windows overlap each other, so consecutive measurements look sticky BY
  CONSTRUCTION — that is why EVALUATION is disjoint and we NEVER report historical-to-historical
  churn as persistence.

BINNING is by RESOLUTION DATE (CLOB end_date proxy; see 30_market_dates.py). A position's
PnL is realized at settlement, so that is when it must count. No resolution outcome ever
enters a wallet's historical stats for a t before it resolved (it is simply not in the <=t bucket).

RESTRICT to directional HOLDERS — the only followable population — using TWO behavioral
conditions, reported across three trade_holding_rate thresholds so the conclusion isn't an
artifact of the cut:
  trade_holding_rate >= thr   : n_hold_positions / n_positions (COUNT-based). Replaces an
      earlier trading_share (PROFIT-based, = pnl_trading/|pnl_total|) filter — verified to
      structurally misclassify 91-98% of behaviorally-active traders as "holders", because
      its denominator (sum of |pnl_total| per position) compresses toward zero for any
      wallet with realistic win/loss variance, not just wallets that don't trade.
  avg_position_size >= MIN_AVG_POSITION_SIZE : excludes economically-negligible wallets
      (verified: ~4-8% of an otherwise-qualified pool are micro-betting bots placing
      sub-$5 bets across thousands of markets — up to 12% of position volume for ~0% of
      real PnL — that would otherwise pass any purely behavioral holding-rate filter).

FOUR METRICS ARE MEASURED (the comparison IS the finding):
  realized_pnl (rewards bankroll), roi (size-neutral), holding_excess_return (pure
  forecasting skill — beat the price paid), sizing_gap (conviction sizing).

THE TEST ITSELF IS A LITERAL PERSISTENCE RATE, not a population-wide rank correlation.
  "Does a wallet's edge persist" is a claim about an INDIVIDUAL wallet, conditional on it
  having an edge — not a claim about whether relative rank is preserved across the WHOLE
  population. A rank correlation (Spearman) answers a different, broader question and was
  removed after finding it does not match what this file claims to test.
  For each metric -> forward_target pair, per t, per threshold:
    good_past = metric > 0        (wallet had a positive edge through t)
    good_fwd  = forward_target > 0  (wallet had a positive edge in the disjoint eval window)
    P(good_fwd | good_past)   vs   P(good_fwd | bad_past)   vs   P(good_fwd) baseline
  A 2x2 chi-square test on (good_past x good_fwd) gives a significance p-value for the GAP
  between the two conditional rates, the same role Spearman's p used to play.
  Both subgroups (good_past, bad_past) require >= MIN_GROUP_SIZE wallets to report a row —
  a persistence rate computed on a handful of wallets is noise, not a finding.

CONSUMES out/positions.csv, data/clob_market_dates.json
PRODUCES out/part4a_persistence.csv, out/part4a_wallet_status.csv + printed summary

out/part4a_wallet_status.csv is the per-WALLET companion to the aggregated rates above: a
snapshot at the latest GRID checkpoint whose forward window is fully resolved, at the PRIMARY
threshold/pair (trade_holding_rate>=0.5, realized_pnl -> fwd_roi). Columns include good_past
(had a historical edge) and good_fwd (kept it out-of-sample); persisted = good_past & good_fwd.
This is the concrete "wallets that persisted" list — 32_part4b_consistency.py consumes it to
test whether LOW-CONCENTRATION good_past wallets persist (good_fwd) more often than
CONCENTRATED ones, rather than re-deriving its own holder population from scratch.
"""
import os, json
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# ---- NAMED CONSTANTS ----
GRID = pd.date_range("2025-07-01", "2026-03-01", freq="MS", tz="UTC")  # monthly checkpoints
EVAL_MONTHS = 3
MIN_HIST_POSITIONS = 30       # activity floor in the historical (through-t) window
MIN_FWD_POSITIONS = 5         # need enough forward positions to measure forward performance
HOLD_RATE_THRESHOLDS = [0.5, 0.7, 0.9]   # min trade_holding_rate (count-based, replaces trading_share)
MIN_AVG_POSITION_SIZE = 10    # $ floor excluding economically-negligible micro-betting wallets
MIN_GROUP_SIZE = 15           # min wallets in EACH of good_past/bad_past to trust a persistence rate
PRIMARY_THRESHOLD = 0.5                        # trade_holding_rate cut used for the wallet-level snapshot
PRIMARY_PAIR = ("realized_pnl", "fwd_roi")     # metric -> forward_target used to label good_past/good_fwd per wallet

# (historical metric, forward target) pairs. Most metrics are evaluated against fwd_roi
# (MIXED trading+holding — what a real follower would actually earn copying everything
# the wallet does). holding_excess_return and sizing_gap are ALSO evaluated against a
# MATCHED, holding-only forward target (fwd_holding_excess_return / fwd_sizing_gap)
# because mixing trading noise into the forward side dilutes a purely holding-side
# historical metric — verified empirically to produce a meaningfully stronger persistence
# signal for holding_excess_return. Keeping both per metric: fwd_roi answers "what do I
# actually earn", the matched target answers "does the underlying skill/behavior persist".
# sizing_gap -> fwd_sizing_gap specifically tests something DIFFERENT from
# sizing_gap -> fwd_roi: is conviction-sizing a STABLE TRAIT (does the wallet keep
# sizing up on its better calls), separate from whether that sizing pays off in returns.
PAIRS = [
    ("realized_pnl", "fwd_roi"),
    ("roi", "fwd_roi"),
    ("holding_excess_return", "fwd_roi"),
    ("holding_excess_return", "fwd_holding_excess_return"),
    ("sizing_gap", "fwd_roi"),
    ("sizing_gap", "fwd_sizing_gap"),
]


def wallet_aggregates(df):
    """Per-wallet historical metrics from a set of resolved positions."""
    g = df.groupby("wallet")
    out = pd.DataFrame({
        "n": g.size(),
        "realized_pnl": g.pnl_total.sum(),
        "buy_usd": g.buy_usd.sum(),
    })
    out["roi"] = out.realized_pnl / out.buy_usd.replace(0, np.nan)
    out["avg_position_size"] = out.buy_usd / out.n
    # holding-only metrics (held, non-hedged positions)
    h = df[(df.hedged == 0) & (df.tokens_held_to_res > 0) & df.direction_correct.notna()]
    hg = h.groupby("wallet")
    usd_held = hg.usd_held.sum()
    out["holding_excess_return"] = hg.pnl_holding_settle.sum() / usd_held.replace(0, np.nan)
    hold_win = hg.direction_correct.mean()
    dollar_win = hg.apply(lambda x: x.loc[x.direction_correct == 1, "usd_held"].sum()
                          / max(x.usd_held.sum(), 1e-9), include_groups=False)
    out["sizing_gap"] = dollar_win - hold_win
    # trade_holding_rate (COUNT-based, the eligibility filter): n_hold_positions / n_positions.
    # Clean, bounded [0,1] — no cancellation issue since it never involves signed PnL.
    out["trade_holding_rate"] = hg.size().reindex(out.index, fill_value=0) / out.n
    return out


def forward(df):
    """Per-wallet forward performance from eval-window positions (MIXED trading+holding)."""
    g = df.groupby("wallet")
    fwd = pd.DataFrame({"fwd_n": g.size(), "fwd_pnl": g.pnl_total.sum(),
                        "fwd_buy": g.buy_usd.sum()})
    fwd["fwd_roi"] = fwd.fwd_pnl / fwd.fwd_buy.replace(0, np.nan)
    return fwd


def forward_holding(df):
    """Per-wallet forward performance restricted to the SAME holding-only construct as
    holding_excess_return / sizing_gap (hedged==0, held to resolution, known outcome) —
    the matched forward targets for testing whether holding SKILL and conviction-SIZING
    BEHAVIOR themselves persist, not a mixed outcome."""
    h = df[(df.hedged == 0) & (df.tokens_held_to_res > 0) & df.direction_correct.notna()]
    hg = h.groupby("wallet")
    usd_held = hg.usd_held.sum()
    fwd_hold_win = hg.direction_correct.mean()
    fwd_dollar_win = hg.apply(lambda x: x.loc[x.direction_correct == 1, "usd_held"].sum()
                              / max(x.usd_held.sum(), 1e-9), include_groups=False)
    fwd = pd.DataFrame({"fwd_hold_n": hg.size(),
                        "fwd_holding_excess_return": hg.pnl_holding_settle.sum() / usd_held.replace(0, np.nan),
                        "fwd_sizing_gap": fwd_dollar_win - fwd_hold_win})
    return fwd


def main():
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    md = json.load(open(os.path.join(HERE, "data", "clob_market_dates.json")))
    res = pos[(pos.resolved == 1) & (pos.oversold == 0)].copy()
    res["res_date"] = pd.to_datetime(res.condition.map(lambda c: md.get(c, {}).get("end")),
                                     errors="coerce", utc=True)
    covered = res.res_date.notna()
    print(f"clean resolved positions: {len(res)}  with resolution date: {covered.mean():.0%}")
    res = res[covered]

    rows = []
    wallet_status = None   # per-wallet snapshot at the latest checkpoint, primary threshold/pair
    for t in GRID:
        t_end = t + pd.DateOffset(months=EVAL_MONTHS)
        hist = wallet_aggregates(res[res.res_date <= t])
        hist = hist[hist.n >= MIN_HIST_POSITIONS]
        fwd_window = res[(res.res_date > t) & (res.res_date <= t_end)]
        fwd_mixed = forward(fwd_window)
        fwd_hold = forward_holding(fwd_window)
        for thr in HOLD_RATE_THRESHOLDS:
            holders = hist[(hist.trade_holding_rate >= thr) & (hist.avg_position_size >= MIN_AVG_POSITION_SIZE)]
            J_mixed = holders.join(fwd_mixed, how="inner")
            J_mixed = J_mixed[J_mixed.fwd_n >= MIN_FWD_POSITIONS]
            J_hold = holders.join(fwd_hold, how="inner")
            J_hold = J_hold[J_hold.fwd_hold_n >= MIN_FWD_POSITIONS]
            if len(J_mixed) < 20 and len(J_hold) < 20:   # too few wallets to say anything this window
                continue
            for metric, fwd_col in PAIRS:
                J = J_mixed if fwd_col == "fwd_roi" else J_hold
                if len(J) < 20:
                    continue
                m = J[[metric, fwd_col]].dropna()
                if len(m) < 20:
                    continue
                good_past = m[metric] > 0
                good_fwd = m[fwd_col] > 0
                if t == GRID[-1] and thr == PRIMARY_THRESHOLD and (metric, fwd_col) == PRIMARY_PAIR:
                    wallet_status = pd.DataFrame({
                        "wallet": m.index, "t": t.date(), "eval_end": t_end.date(),
                        "trade_holding_rate": J.loc[m.index, "trade_holding_rate"].values,
                        "avg_position_size": J.loc[m.index, "avg_position_size"].values,
                        "n_hist": J.loc[m.index, "n"].values,
                        "realized_pnl": m[metric].values, "fwd_roi": m[fwd_col].values,
                        "good_past": good_past.values, "good_fwd": good_fwd.values,
                    })
                    wallet_status["persisted"] = wallet_status.good_past & wallet_status.good_fwd
                n_good_past = int(good_past.sum())
                n_bad_past = int((~good_past).sum())
                if n_good_past < MIN_GROUP_SIZE or n_bad_past < MIN_GROUP_SIZE:
                    continue    # too few wallets in one of the two groups to trust a rate
                p_good_given_good = good_fwd[good_past].mean()
                p_good_given_bad = good_fwd[~good_past].mean()
                p_good_baseline = good_fwd.mean()
                # significance of the GAP between the two conditional rates (2x2 chi-square)
                table = pd.crosstab(good_past, good_fwd)
                gap_p = chi2_contingency(table)[1] if table.shape == (2, 2) else np.nan
                rows.append({
                    "t": t.date(), "eval_end": t_end.date(), "threshold": thr,
                    "metric": metric, "fwd_target": fwd_col,
                    "n_holders": len(m), "n_good_past": n_good_past, "n_bad_past": n_bad_past,
                    "p_good_fwd_given_good_past": p_good_given_good,
                    "p_good_fwd_given_bad_past": p_good_given_bad,
                    "p_good_fwd_baseline": p_good_baseline,
                    "gap_p_value": gap_p,
                })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "part4a_persistence.csv"), index=False)

    if wallet_status is None:
        raise RuntimeError("primary threshold/pair snapshot was never captured — check "
                            "PRIMARY_THRESHOLD/PRIMARY_PAIR against GRID/HOLD_RATE_THRESHOLDS/PAIRS")
    wallet_status.to_csv(os.path.join(OUT, "part4a_wallet_status.csv"), index=False)
    print(f"\nwallet-level snapshot @ t={GRID[-1].date()} (trade_holding_rate>={PRIMARY_THRESHOLD}, "
          f"{PRIMARY_PAIR[0]}->{PRIMARY_PAIR[1]}): {len(wallet_status)} holders, "
          f"{wallet_status.good_past.sum()} good_past, {wallet_status.persisted.sum()} persisted "
          f"-> wrote out/part4a_wallet_status.csv")

    # ---------------- summary ----------------
    print("\n" + "=" * 78)
    print("PART 4A — PERSISTENCE (does a wallet that had an edge KEEP it out-of-sample?)")
    print("=" * 78)
    print(f"PRIMARY threshold = trade_holding_rate >= 0.5 (avg_position_size >= ${MIN_AVG_POSITION_SIZE}).")
    print("Averaged across t windows:")
    for thr in HOLD_RATE_THRESHOLDS:
        sub = df[df.threshold == thr]
        print(f"\n  holder threshold trade_holding_rate >= {thr} (avg_position_size >= ${MIN_AVG_POSITION_SIZE}):")
        for metric, fwd_col in PAIRS:
            s = sub[(sub.metric == metric) & (sub.fwd_target == fwd_col)]
            label = f"{metric} -> {fwd_col}"
            if len(s) == 0:
                print(f"    {label:42s}: (no windows with enough wallets)"); continue
            p_good = s.p_good_fwd_given_good_past.mean()
            p_bad = s.p_good_fwd_given_bad_past.mean()
            p_base = s.p_good_fwd_baseline.mean()
            frac_sig = (s.gap_p_value < 0.05).mean()
            print(f"    {label:42s}: P(good|good_past)={p_good:.0%}  P(good|bad_past)={p_bad:.0%}  "
                  f"baseline={p_base:.0%}  |  windows={len(s)}  frac gap-sig p<.05={frac_sig:.0%}")
    print("\n(P(good|good_past) > baseline > P(good|bad_past)  =>  real persistence.")
    print(" All three close together  =>  no persistence — past edge tells you nothing.)")
    print("wrote out/part4a_persistence.csv")


if __name__ == "__main__":
    main()
