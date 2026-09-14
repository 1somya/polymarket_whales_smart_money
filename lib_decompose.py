"""
lib_decompose.py — position-level PnL decomposition (Part 1 of the "worth following?" study).

WHAT IT DOES
  For one (wallet, outcome_token) position, split the position's total realized PnL
  into two economically distinct sources:
    pnl_trading  = money made/lost by BUYING LOW AND SELLING HIGH before resolution
                   (a price-movement / execution edge — NOT copyable as an outcome bet)
    pnl_holding  = money made/lost by TOKENS CARRIED TO SETTLEMENT
                   (an outcome edge — the only thing a follower can actually copy)
  This is the whole point of the study: following a wallet only makes sense if its
  edge lives in HOLDING. A wallet that earns everything from TRADING has no copyable
  outcome view.

WHAT IT CONSUMES
  Per-fill lists for one token, already normalized by lib_subgraph.normalize():
  each fill = {price, size, ts, side in {BUY,SELL}, ...}. Plus the resolution facts
  for that token: resolved (bool) and won (bool, did THIS token pay out $1).

WHAT IT PRODUCES
  A dict of decomposition fields for the position (see decompose() docstring).

KEY CORRECTNESS INVARIANT (validated by the caller for every clean position):
    pnl_trading + pnl_holding  ==  (Σ sell cash) + (payout on held tokens) − (Σ buy cash)
  i.e. the two buckets must re-sum to the raw cash flow. If they don't, the matching
  has a bug. We assert this to a tight tolerance.
"""
from collections import deque

# ---------------------------------------------------------------------------
# NAMED CONSTANTS  (every threshold/convention lives here, with its rationale)
# ---------------------------------------------------------------------------

# SELL-AT-RESOLUTION TOLERANCE (price-based).
# A sell at $0.99 a minute before a market resolves YES is economically a HOLD:
# the price already equals the ~$1 payout, so the profit came from being RIGHT ABOUT
# THE OUTCOME, not from trading the path. We therefore route the PnL of such
# extreme-price sells into the HOLDING bucket instead of the TRADING bucket.
#   >0.97  : selling into near-certainty of a YES payout  -> holding-equivalent
#   <0.03  : selling into near-certainty of a NO payout   -> holding-equivalent
HOLD_PRICE_HI = 0.97
HOLD_PRICE_LO = 0.03

# The brief's THIRD tolerance trigger — "within 60 minutes of resolution" — is NOT
# APPLIED. We have no reliable resolution timestamp: cond_payout carries only
# resolved/winners (no time), and the only proxy (gamma market `end`) is ~33%
# populated and, even when present, a nominal midnight date rather than the true
# settlement moment. Per the study's global rule (never silently substitute a proxy),
# we rely on the two PRICE triggers above, which economically subsume most 60-minute
# cases (a sell that close to resolution is almost always already at an extreme price).
RESOLUTION_WINDOW_MIN = 60  # documented intent only; see note above — not computed.

# A token balance below this (in token units) is treated as fully closed, not "held".
# Matches the epsilon used in the existing lib_recon so the two agree on what "held" means.
HELD_TOKEN_EPS = 1e-6

# Reconciliation tolerance (USDC). Cash flows are 6-dp on-chain; floating FIFO
# accumulation over thousands of fills can drift a few micro-dollars. Anything above
# this on a CLEAN position signals a real matching bug, not rounding.
RECON_TOL_USD = 1e-3


def _fifo_match(buys, sells):
    """
    FIFO-match sells against buys in TIME ORDER.

    WHY FIFO: it respects the temporal sequence — an early cheap buy is credited to
    the early sell that consumed it, which is the natural reading of "bought low,
    sold high". (We ALSO compute a VWAP/average-cost version elsewhere as a
    robustness check; if the two disagree materially the caller reports it.)

    Returns:
      matched : list of (sell_fill, buy_price, tokens) — one entry per (sell lot,
                buy lot) overlap, so a single sell that eats several buy lots yields
                several entries, each with the buy price of the lot it consumed.
      held_lots : deque of [tokens, buy_price] left UNSOLD after all sells — these are
                  the tokens carried to resolution (FIFO leaves the LATEST buys unsold).
      unmatched_sell_tokens : tokens sold with NO buy lot left to match (oversold /
                  short via the complementary token / CTF-minted tokens with no cost
                  basis). Flagged by the caller; breaks clean reconciliation.
    """
    # Each buy becomes a lot [remaining_tokens, price]; FIFO consumes from the left.
    lots = deque([[b["size"], b["price"]] for b in sorted(buys, key=lambda f: f["ts"])])
    matched = []
    unmatched_sell_tokens = 0.0
    for s in sorted(sells, key=lambda f: f["ts"]):
        need = s["size"]
        while need > HELD_TOKEN_EPS and lots:
            lot = lots[0]
            take = min(need, lot[0])
            matched.append((s, lot[1], take))   # buy price = lot[1]
            lot[0] -= take
            need -= take
            if lot[0] <= HELD_TOKEN_EPS:
                lots.popleft()
        if need > HELD_TOKEN_EPS:
            unmatched_sell_tokens += need        # sold more than we ever bought
    return matched, lots, unmatched_sell_tokens


def _is_resolution_equivalent_sell(price):
    """A sell whose price is so extreme it is economically a HOLD (see constants)."""
    return price > HOLD_PRICE_HI or price < HOLD_PRICE_LO


def decompose(buys, sells, resolved, won, mode="fifo"):
    """
    Decompose one (wallet, outcome_token) position.

    Parameters
      buys, sells : lists of normalized fills (dicts with price,size,ts) for THIS token.
      resolved    : did the market resolve (do we have a payout)?  If False, the
                    holding bucket is left as None (unrealized — NEVER blended in).
      won         : did THIS token pay out $1 (True) or $0 (False)? Only meaningful
                    when resolved.
      mode        : "fifo"  -> each sold token priced at the specific buy lot FIFO
                              matched it (temporal).
                    "vwap"  -> every sold/held token priced at the average buy cost
                              (buy_usd/buy_sz). Robustness check against FIFO.

    Returns a dict; the economically load-bearing fields are:
      tokens_bought, tokens_sold, tokens_held_to_res
      held_fraction            = tokens_held_to_res / tokens_bought   (token-weighted)
      pnl_trading, pnl_holding, pnl_total
      vwap_buy, vwap_sell
      direction_correct        = won  IFF tokens_held_to_res > 0 else None
                                 (a fully-exited wallet took NO settlement view; scoring
                                  it right/wrong is a measurement error — the leaderboard bug)
      resolution_equiv_sold_tokens / _usd  : how much selling the tolerance reclassified
      oversold_tokens          : sold-more-than-bought (flag; breaks clean reconciliation)
      cash_flow                : Σ sells + payout − Σ buys (the number both buckets must sum to)
    """
    buy_sz = sum(b["size"] for b in buys)
    sell_sz = sum(s["size"] for s in sells)
    buy_usd = sum(b["price"] * b["size"] for b in buys)
    sell_usd = sum(s["price"] * s["size"] for s in sells)
    vwap_buy = buy_usd / buy_sz if buy_sz > 0 else None
    vwap_sell = sell_usd / sell_sz if sell_sz > 0 else None

    matched, held_lots, unmatched_sell_tokens = _fifo_match(buys, sells)
    held_tokens = sum(lot[0] for lot in held_lots)
    held_to_res = held_tokens if held_tokens > HELD_TOKEN_EPS else 0.0

    # ---- TRADING bucket: realized price-movement PnL from NON-resolution-equivalent sells.
    #      RESOLUTION-EQUIVALENT sells (extreme price) are peeled off into the HOLDING
    #      bucket, because near-resolution the sell price ≈ the payout, so the profit is
    #      an outcome result, not a trade. This ROUTING preserves reconciliation exactly:
    #      we only change which bucket a sell's (sell−buy) PnL lands in, never the cash.
    pnl_trading = 0.0
    pnl_holding_from_sells = 0.0
    res_equiv_tokens = 0.0
    res_equiv_usd = 0.0       # SELL proceeds of resolution-equivalent sells
    res_equiv_cost = 0.0      # BUY cost basis of those same tokens (for adjusted $ held-fraction)
    for sell_fill, buy_price, tok in matched:
        # price used for the buy leg depends on the cost-basis mode
        cost = vwap_buy if mode == "vwap" else buy_price
        leg = (sell_fill["price"] - cost) * tok
        if _is_resolution_equivalent_sell(sell_fill["price"]):
            pnl_holding_from_sells += leg
            res_equiv_tokens += tok
            res_equiv_usd += sell_fill["price"] * tok
            res_equiv_cost += cost * tok
        else:
            pnl_trading += leg

    # ---- HOLDING bucket: tokens actually carried to settlement, scored at the payout.
    #      Only defined when the market RESOLVED. payout = $1 if this token won else $0.
    #      pnl = (payout − buy_price) × held_tokens, summed over the unsold FIFO lots.
    pnl_holding = None
    pnl_holding_settle = None    # settlement PnL of ACTUALLY-held tokens (excl. res-equiv sells)
    usd_held = 0.0               # cost basis (USDC) of the tokens carried to settlement
    if resolved:
        payout = 1.0 if won else 0.0
        pnl_hold_settle = 0.0
        for tokens_left, buy_price in held_lots:
            if tokens_left <= HELD_TOKEN_EPS:
                continue
            cost = vwap_buy if mode == "vwap" else buy_price
            pnl_hold_settle += (payout - cost) * tokens_left
            usd_held += cost * tokens_left
        pnl_holding_settle = pnl_hold_settle
        pnl_holding = pnl_hold_settle + pnl_holding_from_sells
    else:
        # Market unresolved (or resolved only AFTER the subgraph's April-2026 cutoff, so
        # invisible to us): held tokens are UNREALIZED. We do not fabricate a payout and
        # we do not blend unrealized value into pnl_total. Only the realized TRADING leg
        # is knowable here; holding stays None and the caller excludes it from resolved metrics.
        # Note: any resolution-equivalent-sell PnL we peeled off is still realized cash,
        # so fold it back into trading when unresolved to keep cash reconciliation intact.
        pnl_trading += pnl_holding_from_sells
        pnl_holding_from_sells = 0.0
        res_equiv_tokens = 0.0
        res_equiv_usd = 0.0
        res_equiv_cost = 0.0

    # pnl_total: for resolved positions this is the full realized PnL; for unresolved it
    # is the realized-from-trading-only figure (held tokens excluded, by design).
    if resolved:
        pnl_total = pnl_trading + pnl_holding
        payout = 1.0 if won else 0.0
        cash_flow = sell_usd + payout * held_to_res - buy_usd
    else:
        pnl_total = pnl_trading
        cash_flow = sell_usd - buy_usd  # held tokens carry no realized cash yet

    return {
        "mode": mode,
        "tokens_bought": buy_sz,
        "tokens_sold": sell_sz,
        "tokens_held_to_res": held_to_res,
        # STRICT: only tokens literally carried to settlement.
        "held_fraction_strict": (held_to_res / buy_sz) if buy_sz > 0 else None,
        # ADJUSTED: near-resolution (extreme-price) sells counted as holds too — per the
        # ruling that a sell at >0.97 / <0.03 is economically a hold. res_equiv_tokens are
        # matched sold tokens, so (held_to_res + res_equiv) <= buy_sz for non-oversold.
        "held_fraction_adjusted": ((held_to_res + res_equiv_tokens) / buy_sz) if buy_sz > 0 else None,
        "vwap_buy": vwap_buy,
        "vwap_sell": vwap_sell,
        "usd_held": usd_held,                       # cost basis of held-to-settlement tokens (strict)
        "usd_held_adjusted": usd_held + res_equiv_cost,  # + cost of near-resolution sells (adjusted)
        "pnl_trading": pnl_trading,
        "pnl_holding": pnl_holding,                 # None iff unresolved; = settle + res-equiv-sells
        "pnl_holding_settle": pnl_holding_settle,   # None iff unresolved; held tokens ONLY
        "pnl_total": pnl_total,
        "direction_correct": (won if held_to_res > 0 else None) if resolved else None,
        "resolution_equiv_sold_tokens": res_equiv_tokens,
        "resolution_equiv_sold_usd": res_equiv_usd,
        "oversold_tokens": unmatched_sell_tokens,
        "cash_flow": cash_flow,
        "buy_usd": buy_usd,
        "sell_usd": sell_usd,
    }
