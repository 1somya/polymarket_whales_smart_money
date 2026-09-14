"""
10_part1_positions.py — PART 1: position-level PnL decomposition for the whole cohort.

WHAT IT DOES
  For every wallet with cached subgraph fills, and every (market, outcome_token) it
  took a net-long position in, decompose realized PnL into pnl_trading vs pnl_holding
  (see lib_decompose.py for the economics). Runs BOTH cost-basis conventions:
  FIFO (temporal) and VWAP (average-cost) as a robustness check.

  Wallets whose fetch_fills() history is truncated (still hits the order cap, i.e.
  incomplete) are excluded entirely, not just flagged — computing metrics on an
  arbitrary partial slice of a wallet's real history would be worse than having no
  data at all. See stats['wallets_truncated'] for the count.

WHAT IT CONSUMES
  data/fills/<wallet>.json   (Goldsky CLOB fills, via lib_subgraph.fetch_fills)
  data/tok2cond.json, data/cond_payout.json  (token->condition, condition->resolution)
  All are pre-cached; this script does no network I/O for the resolved cohort.

WHAT IT PRODUCES
  out/positions.csv          one row per (wallet, token) position, FIFO + VWAP fields
  printed summary            reconciliation result, edge-case counts, FIFO-vs-VWAP delta

VALIDATION GATE (must pass before Part 2)
  For every CLEAN resolved position (not oversold), pnl_trading + pnl_holding must
  equal the raw cash flow to within RECON_TOL_USD. We print the max abs discrepancy;
  if it is not ~0 the matching is buggy and Part 2 must not proceed.

GLOBAL RULES honored
  - Resolution (payout) enters ONLY as the settlement value on held tokens; it never
    touches any pre-resolution quantity.
  - Realized and unrealized PnL are never summed: unresolved positions get pnl_holding=None.
"""
import os, csv, time
from collections import defaultdict

import lib_subgraph as sg
import lib_recon as rec
import lib_decompose as dec

HERE = os.path.dirname(os.path.abspath(__file__))
FILLS_DIR = os.path.join(sg.DATA, "fills")
OUT = os.path.join(HERE, "out", "positions.csv")


def wallets_with_fills():
    """Every wallet we have a cached fill history for (the reconstructible cohort)."""
    return sorted(f[:-5] for f in os.listdir(FILLS_DIR) if f.endswith(".json"))


def build_positions():
    wallets = wallets_with_fills()
    print(f"cohort (wallets with cached fills): {len(wallets)}")

    rows = []
    wmeta = []                  # one row per wallet: fills/maker/activity (for Part 2 metrics)
    # ---- counters for the summary / edge-case report ----
    stats = defaultdict(int)
    max_recon_err = 0.0
    max_recon_pos = None
    fifo_vs_vwap_trading = []   # per-position |pnl_trading_fifo - pnl_trading_vwap|

    t0 = time.time()
    for wi, w in enumerate(wallets):
        try:
            fills, truncated = sg.fetch_fills(w)
        except sg.FetchError:
            stats["wallets_fetch_error"] += 1
            continue
        if truncated:
            # incomplete history (still hits the order cap): the wallet's real trading
            # record extends further than what we captured, so any metric built from it
            # would be computed on an arbitrary partial slice. Excluded entirely, not
            # just flagged — a stale slice is worse than no data.
            stats["wallets_truncated"] += 1
            continue
        norm = [n for f in fills if (n := sg.normalize(f, w))]
        if not norm:
            stats["wallets_no_priced_fills"] += 1
            continue

        # token -> conditionId and condition -> {resolved, winners}
        tokens = sorted({n["token"] for n in norm})
        tok2cond, cond = rec.resolve_tokens(tokens)

        # group fills by outcome token
        by_token = defaultdict(list)
        for n in norm:
            by_token[n["token"]].append(n)

        # HEDGED detection: within a (wallet, condition), did the wallet BUY more than
        # one outcome token? If so its directional view is undefined (it is long both
        # sides) — flag every position in that condition.
        buys_per_condition = defaultdict(set)
        for tok, fs in by_token.items():
            cid = tok2cond.get(tok)
            if cid and any(f["side"] == "BUY" for f in fs):
                buys_per_condition[cid].add(tok)
        hedged_conditions = {cid for cid, toks in buys_per_condition.items() if len(toks) > 1}

        for tok, fs in by_token.items():
            cid = tok2cond.get(tok)
            cinfo = cond.get(cid, {"resolved": False, "winners": []})
            buys = [f for f in fs if f["side"] == "BUY"]
            sells = [f for f in fs if f["side"] == "SELL"]

            if sum(b["size"] for b in buys) <= dec.HELD_TOKEN_EPS:
                # No net-long entry: pure maker-sell / short via this token. Not a
                # "position" in the follow sense (no outcome view bought). Count & skip.
                # Tally its sell volume so the CTF/exclusion report (ruling 2) can state
                # how much activity lives outside the clean decomposable set.
                stats["skipped_pure_sell_positions"] += 1
                stats["skipped_pure_sell_usd"] += sum(s["price"] * s["size"] for s in sells)
                continue

            resolved = cinfo["resolved"]
            won = tok in set(cinfo.get("winners", []))

            d_fifo = dec.decompose(buys, sells, resolved, won, mode="fifo")
            d_vwap = dec.decompose(buys, sells, resolved, won, mode="vwap")

            hedged = cid in hedged_conditions
            oversold = d_fifo["oversold_tokens"] > dec.HELD_TOKEN_EPS

            # ---- edge-case tallies ----
            if not resolved:
                stats["positions_open_excluded_from_resolved"] += 1
            if hedged:
                stats["positions_hedged"] += 1
            if oversold:
                # sold more than ever bought: short via complementary token OR tokens
                # acquired via CTF split/merge/redeem (no cost basis in the fill log).
                stats["positions_oversold_no_cost_basis"] += 1
            if d_fifo["resolution_equiv_sold_tokens"] > dec.HELD_TOKEN_EPS:
                stats["positions_with_resolution_equiv_sell"] += 1

            # ---- reconciliation check (clean resolved positions only) ----
            clean = resolved and not oversold
            recon_err = None
            if clean:
                recon_err = abs((d_fifo["pnl_trading"] + d_fifo["pnl_holding"]) - d_fifo["cash_flow"])
                if recon_err > max_recon_err:
                    max_recon_err = recon_err
                    max_recon_pos = (w, tok, recon_err)
                if recon_err > dec.RECON_TOL_USD:
                    stats["positions_recon_FAIL"] += 1

            if resolved and not oversold and not hedged:
                stats["clean_resolved_positions"] += 1
                fifo_vs_vwap_trading.append(abs(d_fifo["pnl_trading"] - d_vwap["pnl_trading"]))

            rows.append({
                "wallet": w,
                "condition": cid,
                "token": tok,
                "resolved": int(resolved),
                "won": int(won) if resolved else "",
                "direction_correct": ("" if d_fifo["direction_correct"] is None
                                      else int(d_fifo["direction_correct"])),
                "hedged": int(hedged),
                "oversold": int(oversold),
                "n_fills": len(fs),
                "maker_fills": sum(1 for f in fs if f["is_maker"]),
                "tokens_bought": round(d_fifo["tokens_bought"], 4),
                "tokens_sold": round(d_fifo["tokens_sold"], 4),
                "tokens_held_to_res": round(d_fifo["tokens_held_to_res"], 4),
                # BOTH held-fraction variants (ruling 1): strict = literally held to
                # settlement; adjusted = near-resolution sells counted as holds too.
                "held_fraction_strict": ("" if d_fifo["held_fraction_strict"] is None
                                         else round(d_fifo["held_fraction_strict"], 6)),
                "held_fraction_adjusted": ("" if d_fifo["held_fraction_adjusted"] is None
                                           else round(d_fifo["held_fraction_adjusted"], 6)),
                "vwap_buy": ("" if d_fifo["vwap_buy"] is None else round(d_fifo["vwap_buy"], 6)),
                "vwap_sell": ("" if d_fifo["vwap_sell"] is None else round(d_fifo["vwap_sell"], 6)),
                "buy_usd": round(d_fifo["buy_usd"], 4),
                "sell_usd": round(d_fifo["sell_usd"], 4),
                "usd_held": round(d_fifo["usd_held"], 4),
                "usd_held_adjusted": round(d_fifo["usd_held_adjusted"], 4),
                # FIFO decomposition (primary)
                "pnl_trading": round(d_fifo["pnl_trading"], 4),
                "pnl_holding": ("" if d_fifo["pnl_holding"] is None else round(d_fifo["pnl_holding"], 4)),
                "pnl_holding_settle": ("" if d_fifo["pnl_holding_settle"] is None
                                       else round(d_fifo["pnl_holding_settle"], 4)),
                "pnl_total": round(d_fifo["pnl_total"], 4),
                "cash_flow": round(d_fifo["cash_flow"], 4),
                "recon_err": ("" if recon_err is None else round(recon_err, 8)),
                "res_equiv_sold_tokens": round(d_fifo["resolution_equiv_sold_tokens"], 4),
                # VWAP decomposition (robustness)
                "pnl_trading_vwap": round(d_vwap["pnl_trading"], 4),
                "pnl_holding_vwap": ("" if d_vwap["pnl_holding"] is None else round(d_vwap["pnl_holding"], 4)),
                "pnl_total_vwap": round(d_vwap["pnl_total"], 4),
                # tolerance transparency
                "res_equiv_sold_usd": round(d_fifo["resolution_equiv_sold_usd"], 4),
                "oversold_tokens": round(d_fifo["oversold_tokens"], 4),
            })
        # ---- wallet-level meta (fills-derived quantities Part 2 needs but positions.csv lacks) ----
        ts_all = [n["ts"] for n in norm]
        wmeta.append({
            "wallet": w,
            "n_fills_total": len(norm),
            "maker_fills_total": sum(1 for n in norm if n["is_maker"]),
            "maker_share": round(sum(n["is_maker"] for n in norm) / len(norm), 6),
            "active_days": round((max(ts_all) - min(ts_all)) / 86400.0, 3),
            "first_ts": min(ts_all),
            "last_ts": max(ts_all),
        })

        stats["positions_total"] = len(rows)
        if (wi + 1) % 50 == 0:
            print(f"  {wi+1}/{len(wallets)} wallets, {len(rows)} positions, {time.time()-t0:.0f}s")

    return rows, wmeta, stats, max_recon_err, max_recon_pos, fifo_vs_vwap_trading


def main():
    rows, wmeta, stats, max_recon_err, max_recon_pos, fvv = build_positions()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    WMETA = os.path.join(HERE, "out", "wallet_meta.csv")
    with open(WMETA, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(wmeta[0].keys()))
        wr.writeheader()
        wr.writerows(wmeta)
    print(f"wrote {WMETA}  ({len(wmeta)} wallets)")
    # persist the run stats so Part 2's CTF/exclusion report (ruling 2) is exact
    import json
    json.dump(dict(stats), open(os.path.join(HERE, "out", "part1_stats.json"), "w"), indent=2)

    print("\n" + "=" * 70)
    print("PART 1 SUMMARY — position-level decomposition")
    print("=" * 70)
    print(f"positions written                     : {len(rows)}  -> {OUT}")
    resolved = [r for r in rows if r["resolved"] == 1]
    print(f"  resolved positions                  : {len(resolved)}")
    print(f"  open/unresolved (excluded from res.) : {stats['positions_open_excluded_from_resolved']}")
    print()
    print("EDGE CASES (counts):")
    print(f"  hedged (bought >1 outcome/market)   : {stats['positions_hedged']}")
    print(f"  oversold / no-cost-basis (CTF)      : {stats['positions_oversold_no_cost_basis']}")
    print(f"  positions w/ resolution-equiv sell  : {stats['positions_with_resolution_equiv_sell']}")
    print(f"  skipped pure-sell (no long entry)   : {stats['skipped_pure_sell_positions']}")
    print(f"  wallets excluded: truncated history  : {stats['wallets_truncated']}")
    print(f"  wallets excluded: no priced fills    : {stats['wallets_no_priced_fills']}")
    print(f"  wallets excluded: fetch error        : {stats['wallets_fetch_error']}")
    print()
    print("RECONCILIATION GATE (clean resolved positions):")
    print(f"  clean resolved positions            : {stats['clean_resolved_positions']}")
    print(f"  max |pnl_trading+pnl_holding - cash|: {max_recon_err:.2e} USD")
    if max_recon_pos:
        print(f"    (worst: wallet {max_recon_pos[0][:10]}… token …{max_recon_pos[1][-8:]})")
    print(f"  positions FAILING (> {dec.RECON_TOL_USD} USD)     : {stats['positions_recon_FAIL']}")
    verdict = "PASS ✅" if stats["positions_recon_FAIL"] == 0 else "FAIL ❌ — DO NOT PROCEED"
    print(f"  GATE                                : {verdict}")
    print()
    if fvv:
        import statistics as st
        print("FIFO vs VWAP robustness (|Δ pnl_trading| per clean resolved position):")
        print(f"  median Δ = {st.median(fvv):.2f} USD   mean Δ = {st.mean(fvv):.2f} USD   max Δ = {max(fvv):.2f} USD")
        print("  (interpretation printed above; wallet-level effect on trading_share is a Part-2 check)")


if __name__ == "__main__":
    main()
