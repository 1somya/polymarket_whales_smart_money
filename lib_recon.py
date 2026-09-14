"""
Position reconstruction + per-wallet behavioural fingerprint.

A "position" = one outcome-token the wallet took a net-long side in (had buys).
For each resolved position we know: entry VWAP (price paid), $ staked (cost basis),
realized PnL, outcome (token payout 1/0), and entry/exit timestamps.

CORRECTNESS: resolution (payout) is used ONLY to (a) label a position resolved and
(b) score win/pnl AFTER the fact. It never enters entry_price, entry_timing, size,
side, or any pre-resolution behavioural feature — those come from fills alone.
"""
import json, os, math
from collections import defaultdict
import lib_subgraph as sg

DATA = sg.DATA
_cond_cache, _gamma_cache = {}, {}

# ---------- global maps (batched, cached to disk) ----------
# IN-MEMORY MEMOIZATION: the token/condition caches grew to ~74MB / ~18MB. Reloading
# and re-parsing them from disk on EVERY resolve_tokens() call (i.e. once per wallet)
# made a whole-cohort run pathologically slow. We now parse each file ONCE, keep the
# dict in memory, and have _save update both disk and the memo so writes stay consistent.
_MEMO = {}
def _load(fp):
    if fp not in _MEMO:
        _MEMO[fp] = json.load(open(fp)) if os.path.exists(fp) else {}
    return _MEMO[fp]
def _save(fp, d):
    # ATOMIC write: dump to a temp file then os.replace() (atomic on POSIX). A plain
    # json.dump to the real path truncates it first, so a kill mid-write corrupts the
    # cache — which is exactly what happened once. temp+rename makes that impossible.
    _MEMO[fp] = d                       # keep memo in sync with what we just wrote
    tmp = fp + ".tmp"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, fp)

TOK2COND_FP = os.path.join(DATA, "tok2cond.json")
COND_FP     = os.path.join(DATA, "cond_payout.json")
GAMMA_FP    = os.path.join(DATA, "gamma_meta.json")

def resolve_tokens(tokens):
    """token -> conditionId, plus conditionId -> {won_tokens set, resolved, positionIds}."""
    tok2cond = _load(TOK2COND_FP)
    need = [t for t in tokens if t not in tok2cond]
    for i in range(0, len(need), 200):
        chunk = need[i:i+200]
        ids = '["' + '","'.join(chunk) + '"]'
        d = sg.gq(sg.POSG, '{ tokenIdConditions(where:{id_in:%s}){ id condition{ id } } }' % ids)
        for r in (d or {}).get("tokenIdConditions", []):
            tok2cond[r["id"]] = r["condition"]["id"]
        for t in chunk:
            tok2cond.setdefault(t, None)
    if need:                       # only rewrite the (large) cache when it actually changed;
        _save(TOK2COND_FP, tok2cond)  # an unconditional save wrote ~74MB PER WALLET otherwise.

    conds = sorted({c for c in (tok2cond[t] for t in tokens) if c})
    cond = _load(COND_FP)
    need = [c for c in conds if c not in cond]
    for i in range(0, len(need), 100):
        chunk = need[i:i+100]
        ids = '["' + '","'.join(chunk) + '"]'
        d = sg.gq(sg.PNLG, '{ conditions(where:{id_in:%s}){ id positionIds payoutNumerators payoutDenominator }}' % ids)
        for r in (d or {}).get("conditions", []):
            pn = r.get("payoutNumerators") or []
            pids = r.get("positionIds") or []
            resolved = bool(pn) and any(int(x) > 0 for x in pn)
            winners = set(p for p, n in zip(pids, pn) if int(n) > 0) if resolved else set()
            cond[r["id"]] = {"resolved": resolved, "winners": list(winners)}
        for c in chunk:
            cond.setdefault(c, {"resolved": False, "winners": []})
    if need:                       # same: skip the ~18MB rewrite when nothing new resolved.
        _save(COND_FP, cond)
    return tok2cond, cond

import urllib.request
def _clob_meta(c):
    """One market's metadata from CLOB (reliable for all markets). category = tags[0]."""
    try:
        req = urllib.request.Request(f"https://clob.polymarket.com/markets/{c}",
                                     headers={"User-Agent": "Mozilla/5.0"})
        m = json.load(urllib.request.urlopen(req, timeout=30))
        if isinstance(m, dict) and m.get("condition_id"):
            tags = m.get("tags") or []
            return {"category": tags[0] if tags else (m.get("category") or None),
                    "start": m.get("accepting_order_timestamp") or m.get("game_start_time"),
                    "end": m.get("end_date_iso"), "closed": m.get("closed")}
    except Exception:
        pass
    return None

def gamma_meta(cond_ids):
    """conditionId -> {category, start, end}. Reads cache only (populated by prefetch).
    Missing markets return an empty meta so timing/category just go uncovered."""
    g = _load(GAMMA_FP)
    return {c: g.get(c, {"category": None, "start": None, "end": None}) for c in cond_ids}

def prefetch_market_meta(cond_ids, workers=8):
    """Populate the market-meta cache in parallel (CLOB). Call before reconstruct()."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    g = _load(GAMMA_FP)
    need = [c for c in set(cond_ids) if c not in g]
    if not need:
        return len(g)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_clob_meta, c): c for c in need}
        n = 0
        for fu in as_completed(futs):
            c = futs[fu]; m = fu.result()
            g[c] = m or {"category": None, "start": None, "end": None}
            n += 1
            if n % 500 == 0:
                _save(GAMMA_FP, g); print(f"  market-meta {n}/{len(need)}", flush=True)
    _save(GAMMA_FP, g)
    return len(g)

def _iso_ts(s):
    if not s: return None
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

# ---------- per-wallet reconstruction ----------
def reconstruct(wallet, want_gamma=True):
    fills, truncated = sg.fetch_fills(wallet)
    norm = [n for f in fills if (n := sg.normalize(f, wallet))]
    if not norm:
        return {"wallet": wallet, "truncated": truncated, "positions": [], "n_fills": 0}
    tokens = sorted({n["token"] for n in norm})
    tok2cond, cond = resolve_tokens(tokens)
    cond_ids = sorted({tok2cond[t] for t in tokens if tok2cond.get(t)})
    gm = gamma_meta(cond_ids) if want_gamma else {}

    by_token = defaultdict(list)
    for n in norm:
        by_token[n["token"]].append(n)

    positions = []
    for tok, fs in by_token.items():
        cid = tok2cond.get(tok)
        cinfo = cond.get(cid, {"resolved": False, "winners": []})
        buys  = [f for f in fs if f["side"] == "BUY"]
        sells = [f for f in fs if f["side"] == "SELL"]
        buy_sz  = sum(f["size"] for f in buys)
        buy_usd = sum(f["usdc"] for f in buys)
        sell_usd = sum(f["usdc"] for f in sells)
        sell_sz = sum(f["size"] for f in sells)
        if buy_sz <= 0:               # not a net-long entry (pure maker-sell/short) -> skip as a position
            continue
        entry_vwap = buy_usd / buy_sz
        held = buy_sz - sell_sz
        won = tok in cinfo["winners"]
        redeem = held * (1.0 if won else 0.0) if cinfo["resolved"] else 0.0
        realized = sell_usd + redeem - buy_usd
        ts_all = [f["ts"] for f in fs]
        maker_fills = sum(1 for f in fs if f["is_maker"])
        meta = gm.get(cid, {})
        t_open, t_close = _iso_ts(meta.get("start")), _iso_ts(meta.get("end"))
        t_entry = min(f["ts"] for f in buys)
        # entry timing normalized within market life (None if timing unknown)
        timing = None
        if t_open and t_close and t_close > t_open:
            timing = max(0.0, min(1.0, (t_entry - t_open) / (t_close - t_open)))
        t_exit = t_close if held > 1e-6 and cinfo["resolved"] else max(ts_all)
        hold = (t_exit - t_entry) if t_exit and t_entry else max(ts_all) - t_entry
        positions.append({
            "token": tok, "condition": cid, "resolved": cinfo["resolved"], "won": bool(won),
            "entry_price": entry_vwap, "stake": buy_usd, "realized_pnl": realized,
            "held_to_resolution": held > 1e-6, "n_fills": len(fs), "maker_fills": maker_fills,
            "t_entry": t_entry, "timing": timing, "hold_days": hold / 86400.0,
            "category": meta.get("category"),
        })
    return {"wallet": wallet, "truncated": truncated, "positions": positions,
            "n_fills": len(norm), "maker_share": sum(n["is_maker"] for n in norm) / len(norm),
            "active_days": (max(n["ts"] for n in norm) - min(n["ts"] for n in norm)) / 86400.0}


if __name__ == "__main__":
    import sys
    w = sys.argv[1] if len(sys.argv) > 1 else "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    r = reconstruct(w)
    P = r["positions"]; res = [p for p in P if p["resolved"]]
    real = sum(p["realized_pnl"] for p in res)
    print(f"{w}")
    print(f"  fills={r['n_fills']} positions={len(P)} resolved={len(res)} "
          f"maker_share={r['maker_share']:.2f} active_days={r['active_days']:.0f}")
    print(f"  reconstructed realized PnL (resolved) = ${real:,.0f}")
    if res:
        wins = sum(p["won"] for p in res)
        stake = sum(p["stake"] for p in res); wstake = sum(p["stake"] for p in res if p["won"])
        print(f"  count_win_rate={wins/len(res):.3f}  dollar_win_rate={wstake/stake:.3f}  "
              f"sizing_gap={wstake/stake - wins/len(res):+.3f}")
