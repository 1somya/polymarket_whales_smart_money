"""
11_part2_wallets.py — PART 2 (step 1): aggregate positions -> per-wallet metrics.

WHAT IT DOES
  Collapses out/positions.csv to one row per wallet with >= MIN_RESOLVED_POSITIONS
  decomposable resolved positions, and computes the study's KEY VARIABLE:

    trading_share = Σ pnl_trading / Σ |pnl_total|   (profit-weighted)
      ~1.0 ⇒ this wallet's REALIZED PROFIT came mostly from trading the price path —
             NOT a copyable outcome view.  ~0.0 ⇒ realized profit came mostly from
             being right about outcomes — copyable.  It is profit-weighted (says
             where the MONEY came from) and already reflects the sell-at-resolution
             bucket fix from Part 1.

      CAUTION — this is a PROFIT-ATTRIBUTION metric, not a behavioral one. A wallet
      that trades constantly but nets ~$0 from it (wins and losses cancelling) shows
      trading_share ~0 here, identical to a wallet that never trades at all. Do NOT
      read "trading_share near 0" as "this wallet is a holder" — cross-check
      trade_frequency / holding_fraction_dollar (both printed below) before making
      any claim about a wallet's actual behavior, not just where its profit came from.

  Plus the supporting holder/trader metrics (both held-fraction variants per ruling 1).

WHAT IT CONSUMES   out/positions.csv, out/wallet_meta.csv   (from Part 1)
WHAT IT PRODUCES   out/wallet_metrics.csv + printed summary

POSITION SET (documented choices)
  "decomposable resolved" D(w) = positions with resolved==1 AND oversold==0.
    - oversold/CTF excluded per ruling 2 (no reliable cost basis).
    - hedged positions are kept in the $ aggregates (their cash reconciles) AND in the
      outcome metrics below. The `hedged` flag (10_part1_positions.py's "ever bought
      both tokens in a market" check) has a measured ~76-85% false-positive rate on
      real data (sequential flips get misread as simultaneous hedges), so excluding it
      was silently dropping ~174k genuinely single-directional positions across the
      cohort. hedge_share is still reported per wallet so this can be revisited once
      the detection itself is fixed.
  Holding-outcome set H(w) = D(w) positions with held_to_res>0 (i.e. direction_correct
    is defined). Win-rate/excess-return need a settlement view.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# ---- NAMED CONSTANTS ----
MIN_RESOLVED_POSITIONS = 30   # activity floor: below this, wallet metrics are too noisy.
PURE_TRADER_CUT = 0.8         # trading_share above this ⇒ treat holder metrics as unreliable.
PURE_HOLDER_CUT = 0.2         # trading_share below this ⇒ profit is holding-driven.
                               # NOT the same as "doesn't trade" — see docstring CAUTION.


def wsum(s):
    return float(np.nansum(s.values))


def print_metric(name, series, what, how, why, fmt="+.3f"):
    """Prints one wallet-level metric so it's understandable on its own, without the
    source file open: a plain-English WHAT/HOW/WHY, then the actual distribution
    (n / min / p25 / median / p75 / max across qualifying wallets, NaN dropped)."""
    print(name)
    print(f"  WHAT: {what}")
    print(f"  HOW:  {how}")
    print(f"  WHY:  {why}")
    s = series.dropna()
    if len(s) == 0:
        print("  VALUES: (no data)")
    else:
        print(f"  VALUES: n={len(s)}  min={s.min():{fmt}}  p25={s.quantile(.25):{fmt}}  "
              f"median={s.median():{fmt}}  p75={s.quantile(.75):{fmt}}  max={s.max():{fmt}}")
    print()


def main():
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    meta = pd.read_csv(os.path.join(OUT, "wallet_meta.csv")).set_index("wallet")

    # decomposable resolved set
    D = pos[(pos.resolved == 1) & (pos.oversold == 0)].copy()

    recs = []
    for w, g in D.groupby("wallet"):
        n_pos = len(g)
        if n_pos < MIN_RESOLVED_POSITIONS:
            continue

        # ---- profit decomposition (KEY VARIABLE) ----
        pnl_trading = wsum(g.pnl_trading)
        pnl_holding = wsum(g.pnl_holding)
        pnl_total = wsum(g.pnl_total)
        abs_total = wsum(g.pnl_total.abs())
        # profit-weighted trading share. Denominator is Σ|pnl_total| so wins and losses
        # don't cancel (a wallet that made $1M trading and lost $1M holding is NOT 0% trader).
        trading_share = pnl_trading / abs_total if abs_total > 0 else np.nan

        # ---- dollar holding fractions, BOTH variants (ruling 1) ----
        buy_usd = wsum(g.buy_usd)
        hfd_strict = wsum(g.usd_held) / buy_usd if buy_usd > 0 else np.nan
        hfd_adjusted = wsum(g.usd_held_adjusted) / buy_usd if buy_usd > 0 else np.nan
        # token-weighted held fraction, both variants
        tok_bought = wsum(g.tokens_bought)
        hf_tok_strict = wsum(g.tokens_held_to_res) / tok_bought if tok_bought > 0 else np.nan
        hf_tok_adjusted = (wsum(g.tokens_held_to_res) + wsum(g.res_equiv_sold_tokens)) / tok_bought if tok_bought > 0 else np.nan

        # ---- holding-outcome metrics (set H: actually held to resolution) ----
        # Hedged positions are NOT excluded here (see module docstring / POSITION SET):
        # the hedge flag's false-positive rate makes exclusion do more harm than good
        # until 10_part1_positions.py's detection itself is fixed.
        H = g[(g.tokens_held_to_res > 0) & g.direction_correct.notna()]
        if len(H) > 0:
            hold_win_rate = float(H.direction_correct.mean())               # count-weighted
            usd_held_H = wsum(H.usd_held)
            usd_held_win = wsum(H.loc[H.direction_correct == 1, "usd_held"])
            hold_dollar_win_rate = usd_held_win / usd_held_H if usd_held_H > 0 else np.nan
            sizing_gap = hold_dollar_win_rate - hold_win_rate              # >0 ⇒ bigger when right
            # holding_excess_return: return on capital carried to settlement — "did they
            # beat the price they PAID". Σ settlement PnL / Σ cost of held tokens.
            holding_excess_return = wsum(H.pnl_holding_settle) / usd_held_H if usd_held_H > 0 else np.nan
            n_hold = len(H)
        else:
            hold_win_rate = hold_dollar_win_rate = sizing_gap = holding_excess_return = np.nan
            n_hold = 0

        # ---- trading metrics ----
        trading_return = pnl_trading / buy_usd if buy_usd > 0 else np.nan
        m = meta.loc[w] if w in meta.index else None
        maker_ratio = (m.maker_fills_total / m.n_fills_total) if m is not None and m.n_fills_total > 0 else np.nan
        trade_frequency = (m.n_fills_total / m.active_days) if m is not None and m.active_days > 0 else np.nan

        recs.append({
            "wallet": w,
            "n_positions": n_pos,
            "n_markets": g.condition.nunique(),
            "hedge_share": float((g.hedged == 1).mean()),
            "pnl_total": pnl_total,
            "pnl_trading": pnl_trading,
            "pnl_holding": pnl_holding,
            "trading_share": trading_share,               # KEY VARIABLE
            "holding_fraction_dollar_strict": hfd_strict,
            "holding_fraction_dollar_adjusted": hfd_adjusted,
            "held_frac_tok_strict": hf_tok_strict,
            "held_frac_tok_adjusted": hf_tok_adjusted,
            "n_hold_positions": n_hold,
            "hold_win_rate": hold_win_rate,
            "hold_dollar_win_rate": hold_dollar_win_rate,
            "sizing_gap": sizing_gap,
            "holding_excess_return": holding_excess_return,
            "trading_return": trading_return,
            "maker_ratio": maker_ratio,
            "trade_frequency": trade_frequency,
            "avg_position_size": buy_usd / n_pos,
        })

    df = pd.DataFrame(recs).sort_values("pnl_total", ascending=False).reset_index(drop=True)
    df.to_csv(os.path.join(OUT, "wallet_metrics.csv"), index=False)

    # ==================================================================
    # PRINTED SUMMARY — written to be readable on its own, no source file needed.
    # ==================================================================
    print("=" * 72)
    print("PART 2 — turning each wallet's individual bets into one profile per wallet")
    print("=" * 72)
    print()
    print("WHAT THIS FILE DOES: Part 1 produced one row per individual bet a wallet made.")
    print("This file rolls all of one wallet's bets up into a single profile, and answers")
    print("the central question of this study: is a wallet's profit coming from TRADING")
    print("SKILL (timing buys and sells well — you can't copy this after the fact) or from")
    print("correctly PICKING OUTCOMES and holding to settlement (you CAN copy this, by just")
    print("buying the same thing and waiting)?")
    print()
    print("TWO GROUPS OF BETS USED THROUGHOUT THIS REPORT:")
    print("  RESOLVED BETS = one entry per (wallet, market-outcome) where that market has")
    print("    already settled and we also trust the cost-basis data (a small number are")
    print("    excluded because the wallet appears to have acquired the shares outside the")
    print("    order book, so we can't reliably say what it paid for them).")
    print("  IMPORTANT: a single 'bet' here is NOT a single trade. If a wallet bought the")
    print("    same outcome 50 separate times over a month, all 50 of those trades get")
    print("    combined into ONE bet — the wallet's whole position in that one outcome, not")
    print("    each individual purchase. So a wallet with a low bet count can still have")
    print("    placed a very large number of individual trades.")
    print("  HELD BETS = the subset of resolved bets where the wallet was still holding the")
    print("    shares at the moment the market settled — the ones where we know for certain")
    print("    whether that specific position won or lost.")
    print()

    n_recon = pos.wallet.nunique()
    print("HOW MANY WALLETS QUALIFY")
    print(f"  WHAT: how many wallets have enough data to trust any metric about them.")
    print(f"  HOW:  a wallet needs at least {MIN_RESOLVED_POSITIONS} resolved bets to qualify — below")
    print(f"        that, percentages and averages are too noisy to mean anything.")
    print(f"  WHY:  keeps the rest of this report from being dominated by wallets we barely")
    print(f"        have any data on.")
    print(f"  VALUES: {len(df)} of {n_recon} wallets we have any data for qualify.")
    print()

    print("-" * 72)
    print("TRADING_SHARE — the central number in this study")
    print("-" * 72)
    ts = df.trading_share.dropna()
    print("  WHAT: of a wallet's total profit or loss, what fraction came from active")
    print("        trading (buying and selling before the market settled) versus from")
    print("        being right about the outcome and holding to the end.")
    print("  HOW:  (money made or lost from trading) divided by (total money made or lost,")
    print("        with every bet's result counted as a positive number first, so wins and")
    print("        losses across different bets can't cancel each other out).")
    print("  WHY:  this decides whether a wallet is worth copying. If its profit is")
    print("        trading-driven, you can't replicate it without matching its exact buy/")
    print("        sell timing. If it's holding-driven, you can — buy the same thing and wait.")
    print("  CAUTION: this measures WHERE THE MONEY CAME FROM, not how much trading actually")
    print("        happened. A wallet that trades constantly but breaks even on that trading")
    print("        looks identical here to a wallet that never trades at all. Check")
    print("        TRADE_FREQUENCY and HOLDING_FRACTION further down before assuming a low")
    print("        number here means a wallet 'doesn't trade'.")
    print(f"  VALUES: n={len(ts)}  min={ts.min():+.2f}  p25={ts.quantile(.25):+.2f}  "
          f"median={ts.median():+.2f}  p75={ts.quantile(.75):+.2f}  max={ts.max():+.2f}")
    print()

    print("SPLITTING WALLETS INTO THREE GROUPS BY TRADING_SHARE")
    print(f"  WHAT: how many wallets fall into each of three groups, based on the number above.")
    print(f"  HOW:  trading_share below {PURE_HOLDER_CUT} → 'holding-profit-dominated'. Above")
    print(f"        {PURE_TRADER_CUT} → 'trading-profit-dominated'. In between → 'middle'.")
    print(f"  WHY:  turns a continuous number into groups simple enough to report profit-share on.")
    print(f"  VALUES: holding-profit-dominated={(ts < PURE_HOLDER_CUT).sum()}"
          f"   middle={((ts >= PURE_HOLDER_CUT) & (ts <= PURE_TRADER_CUT)).sum()}"
          f"   trading-profit-dominated={(ts > PURE_TRADER_CUT).sum()}")
    print()

    tot_pos_profit = df.loc[df.pnl_total > 0, "pnl_total"].sum()
    def bucket_share(mask):
        return df.loc[mask & (df.pnl_total > 0), "pnl_total"].sum() / tot_pos_profit
    print("HOW MUCH OF THIS COHORT'S PROFIT IS ACTUALLY COPYABLE — the headline answer")
    print(f"  WHAT: of all the money made by wallets that were net profitable, what share")
    print(f"        sits in each of the three groups above.")
    print(f"  HOW:  (profit of profitable wallets in that group) divided by (profit of ALL")
    print(f"        profitable wallets combined). Losing wallets are left out of both — a")
    print(f"        wallet that lost money isn't a candidate to follow regardless of its group.")
    print(f"  WHY:  this is the actual number this whole study exists to produce.")
    print(f"  VALUES: trading-profit-dominated={bucket_share(df.trading_share > PURE_TRADER_CUT):6.1%}"
          f"   middle={bucket_share((df.trading_share >= PURE_HOLDER_CUT) & (df.trading_share <= PURE_TRADER_CUT)):6.1%}"
          f"   holding-profit-dominated={bucket_share(df.trading_share < PURE_HOLDER_CUT):6.1%}")
    print()

    print("-" * 72)
    print("ACTIVITY & SIZE — how big and how busy is each wallet")
    print("-" * 72)
    print()
    print_metric("N_POSITIONS", df.n_positions, fmt=",.0f",
        what="How many distinct market-outcomes this wallet has taken a resolved stance "
             "on — NOT how many individual trades it placed.",
        how="A count of this wallet's resolved bets, where every trade the wallet ever "
            "made in the same outcome-token is already combined into a single bet before "
            "this count happens (see 'IMPORTANT' note above). A wallet that traded the "
            "same outcome 200 times still counts as 1 here.",
        why="Tells you how much data backs up this wallet's other numbers — more bets "
            "means more trustworthy percentages. To see raw trading volume instead, look "
            "at TRADE_FREQUENCY further down, which counts actual trades, not positions.")
    print_metric("N_MARKETS", df.n_markets, fmt=",.0f",
        what="How many different prediction markets this wallet has resolved bets in.",
        how="A count of distinct markets across this wallet's resolved bets.",
        why="Close to N_POSITIONS means the wallet almost always takes just one side of "
            "each market. Noticeably lower means it's holding both outcomes of some "
            "markets at once (see HEDGE_SHARE below).")
    print_metric("AVG_POSITION_SIZE ($)", df.avg_position_size, fmt=",.2f",
        what="The typical dollar amount this wallet commits to a single bet.",
        how="Total dollars spent buying, divided by number of resolved bets.",
        why="A cheap way to tell a whale making a few large bets apart from a bot making "
            "thousands of tiny ones.")
    print_metric("MAKER_RATIO", df.maker_ratio, fmt=".3f",
        what="What fraction of this wallet's trades were placed as a resting order, "
             "rather than crossing an order that was already sitting on the book.",
        how="Maker trades divided by total trades — counting ALL of this wallet's "
            "trading activity, not just its resolved bets.",
        why="A ratio close to 1 usually signals a market-making bot rather than a "
            "directional bettor.")
    print_metric("TRADE_FREQUENCY (fills/day)", df.trade_frequency, fmt=",.2f",
        what="How often this wallet trades, period — regardless of whether it made or "
             "lost money doing so.",
        how="Total number of trades divided by the number of days between its first "
            "and last trade.",
        why="The real check on whether a wallet is actually active. Use this alongside "
            "TRADING_SHARE above, which only says where PROFIT came from, not how much "
            "trading actually happened.")
    print("  NOTE: wallets with an incomplete (truncated) trade history are excluded")
    print("        entirely upstream, in Part 1 — see 10_part1_positions.py's own printed")
    print("        summary for that count. None of the wallets below have partial data.")
    print()

    print("-" * 72)
    print("HEDGING")
    print("-" * 72)
    print()
    print_metric("HEDGE_SHARE", df.hedge_share, fmt=".3f",
        what="What fraction of this wallet's resolved bets were flagged 'hedged' — "
             "meaning the wallet appeared to be betting on both sides of the same market.",
        how="Count of this wallet's bets flagged hedged, divided by its total resolved bets.",
        why="Originally used to exclude ambiguous bets from win-rate scoring. It no "
            "longer excludes anything (see CAUTION below) — reported so its weight per "
            "wallet stays visible.")
    print("  CAUTION: this flag currently has a measured 76-85% false-positive rate — it")
    print("  often fires when a wallet simply changed its mind (fully sold one side, then")
    print("  later bought the other), not when it was genuinely holding both sides at once.")
    print("  Read a high hedge_share as 'flips its view often', not 'hedges often', until")
    print("  the detection logic itself is fixed.")
    print()

    print("-" * 72)
    print("PROFIT, IN DOLLARS")
    print("-" * 72)
    print()
    print_metric("PNL_TOTAL ($)", df.pnl_total, fmt=",.2f",
        what="This wallet's total realized profit or loss, across all its resolved bets.",
        how="Sum of profit/loss across every resolved bet.",
        why="The headline profit number for the wallet — positive means it made money "
            "overall.")
    print_metric("PNL_TRADING ($)", df.pnl_trading, fmt=",.2f",
        what="How much of that profit or loss came specifically from trading the price "
             "before the market settled.",
        how="Sum of the 'trading' portion of profit/loss across every resolved bet.",
        why="The raw dollar figure behind TRADING_SHARE's numerator.")
    print_metric("PNL_HOLDING ($)", df.pnl_holding, fmt=",.2f",
        what="How much of that profit or loss came from being right or wrong about the "
             "outcome, on whatever was carried to settlement.",
        how="Sum of the 'holding' portion of profit/loss across every resolved bet.",
        why="The raw dollar figure behind TRADING_SHARE's other half.")
    print_metric("TRADING_RETURN", df.trading_return, fmt="+.3f",
        what="Trading profit or loss, as a percentage return on the money this wallet "
             "actually spent buying.",
        how="Trading profit/loss divided by total dollars spent buying.",
        why="A different lens than TRADING_SHARE — this asks 'was trading a good use of "
            "capital', not 'how much of total profit came from trading'.")

    print("-" * 72)
    print("HOW MUCH OF EACH WALLET'S MONEY WAS ACTUALLY HELD TO SETTLEMENT")
    print("-" * 72)
    print()
    print_metric("HOLDING_FRACTION_DOLLAR_STRICT", df.holding_fraction_dollar_strict, fmt=".3f",
        what="What fraction of the dollars this wallet spent buying ended up still held "
             "when the market settled, rather than sold beforehand.",
        how="Dollar value of shares still held at settlement, divided by total dollars "
            "spent buying.",
        why="Close to 1 means genuine buy-and-hold behavior; close to 0 means the wallet "
            "almost always trades out before the market settles — this is the number "
            "that catches wallets TRADING_SHARE alone would mislabel (see CAUTION above).")
    print_metric("HOLDING_FRACTION_DOLLAR_ADJUSTED", df.holding_fraction_dollar_adjusted, fmt=".3f",
        what="The same question as above, but a sale made at a near-certain price (over "
             "97 cents or under 3 cents on the dollar) right before settlement also "
             "counts as 'held' — economically it's the same thing as holding to the end.",
        how="Same formula as the strict version, with those near-certain-price sales "
            "added into the 'held' side too.",
        why="A softer, arguably more realistic version of the strict number above.")
    print_metric("HELD_FRAC_TOK_STRICT", df.held_frac_tok_strict, fmt=".3f",
        what="The same 'strict' question as above, counted in number of shares instead "
             "of dollars.",
        how="Shares still held at settlement, divided by total shares bought.",
        why="A cross-check on the dollar-based version — the two can differ if a wallet "
            "buys cheap and expensive shares in different proportions.")
    print_metric("HELD_FRAC_TOK_ADJUSTED", df.held_frac_tok_adjusted, fmt=".3f",
        what="The 'adjusted' question above, counted in shares instead of dollars.",
        how="Shares still held, plus shares sold at a near-certain price, divided by "
            "total shares bought.",
        why="Token-counted version of HOLDING_FRACTION_DOLLAR_ADJUSTED.")

    print("-" * 72)
    print("WAS THIS WALLET ACTUALLY GOOD AT PICKING OUTCOMES")
    print("-" * 72)
    print("(this section only uses HELD BETS — the ones where we know for sure if the")
    print(" wallet was right or wrong, because it was still holding when the market settled)")
    print()
    print_metric("N_HOLD_POSITIONS", df.n_hold_positions, fmt=",.0f",
        what="How many of this wallet's resolved bets are 'held bets' (see the "
             "definition at the top of this report).",
        how="A count.",
        why="Sample size behind the four metrics below — a small number here means "
            "those metrics are noisy for this wallet.")
    print_metric("HOLD_WIN_RATE", df.hold_win_rate, fmt=".3f",
        what="Out of this wallet's held bets, what fraction ended up correct.",
        how="Number of held bets that won, divided by total held bets — every bet "
            "counted equally regardless of its size.",
        why="The simplest possible 'was this wallet right' number — but treating a $1 "
            "bet and a $100,000 bet as equally important can be misleading on its own "
            "(see SIZING_GAP below).")
    print_metric("HOLD_DOLLAR_WIN_RATE", df.hold_dollar_win_rate, fmt=".3f",
        what="The same question as above, but weighted by how much money was actually "
             "riding on each bet.",
        how="Dollars held on bets that won, divided by total dollars held.",
        why="If this is a lot higher than HOLD_WIN_RATE, the wallet bets more money on "
            "the calls it's more confident in — a real skill invisible to the count-"
            "based number alone.")
    print_metric("SIZING_GAP", df.sizing_gap, fmt="+.3f",
        what="The gap between the two win-rate numbers above.",
        how="Dollar-weighted win rate minus count-weighted win rate.",
        why="THE real skill signal in this report. Positive means the wallet sizes its "
            "bets up when more likely right and down when more likely wrong — a skill a "
            "raw win-rate count completely misses. Negative means the opposite: it bets "
            "bigger on its worse calls.")
    print_metric("HOLDING_EXCESS_RETURN", df.holding_excess_return, fmt="+.3f",
        what="The actual financial return earned on the money this wallet carried "
             "through to settlement.",
        how="Profit or loss from settlement, divided by the dollar cost of the shares "
            "that were held to get there.",
        why="A return-based answer to 'did holding pay off', unlike win-rate's binary "
            "right-or-wrong answer — a wallet can have a good win rate and still lose "
            "money if it overpaid for its winners.")

    print(f"wrote out/wallet_metrics.csv")


if __name__ == "__main__":
    main()
