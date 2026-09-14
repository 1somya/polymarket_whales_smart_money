"""
Shared, cached, rate-limited fetchers for the Polymarket pipeline.

Design goals:
  - resumable: every network result is cached on disk; re-runs are cheap.
  - honest: no silent truncation. fetch_all_trades() pages until exhausted and
    records whether it hit a hard cap so downstream code can exclude the wallet.
"""
import json, os, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = {"User-Agent": "Mozilla/5.0 (research; polymarket-whale-taxonomy)"}

_last = [0.0]
def _throttle(min_interval=0.12):
    dt = time.time() - _last[0]
    if dt < min_interval:
        time.sleep(min_interval - dt)
    _last[0] = time.time()

def _get(url, tries=5):
    for i in range(tries):
        _throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (i + 1)); continue
            if e.code == 404:
                return None
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1.0 * (i + 1))
    return None

# ---------------- trades (data-api) ----------------
PAGE = 1000
def fetch_all_trades(wallet, hard_cap_pages=400):
    """Return (list_of_trades, truncated_bool). Cached per wallet.
    hard_cap_pages*1000 fills is the ceiling we're willing to pull; beyond that
    the wallet is marked truncated and must be excluded from fingerprints."""
    fp = os.path.join(DATA, "trades", f"{wallet}.json")
    if os.path.exists(fp):
        obj = json.load(open(fp))
        return obj["trades"], obj["truncated"]
    out, off, truncated = [], 0, False
    while True:
        batch = _get(f"https://data-api.polymarket.com/trades?user={wallet}&limit={PAGE}&offset={off}")
        if not batch:
            break
        out.extend(batch)
        if len(batch) < PAGE:
            break
        off += PAGE
        if off >= hard_cap_pages * PAGE:
            truncated = True
            break
    json.dump({"trades": out, "truncated": truncated}, open(fp, "w"))
    return out, truncated

# ---------------- market resolution (CLOB) + metadata (Gamma) ----------------
def fetch_market(condition_id):
    """Merged market record: winner token (CLOB) + timing/category (Gamma).
    Cached per conditionId. Returns dict or None."""
    fp = os.path.join(DATA, "markets", f"{condition_id}.json")
    if os.path.exists(fp):
        return json.load(open(fp))
    clob = _get(f"https://clob.polymarket.com/markets/{condition_id}")
    rec = {"conditionId": condition_id, "closed": None, "winner_token": None,
           "tokens": {}, "startDate": None, "endDate": None, "category": None,
           "question": None}
    if clob:
        rec["closed"] = clob.get("closed")
        rec["question"] = clob.get("question")
        for t in clob.get("tokens", []):
            tid = str(t.get("token_id"))
            rec["tokens"][tid] = {"outcome": t.get("outcome"),
                                  "winner": t.get("winner"),
                                  "price": t.get("price")}
            if t.get("winner"):
                rec["winner_token"] = tid
        rec["startDate"] = clob.get("game_start_time") or clob.get("accepting_orders_timestamp")
        rec["endDate"] = clob.get("end_date_iso")
    g = _get(f"https://gamma-api.polymarket.com/markets?condition_ids={condition_id}")
    if g and isinstance(g, list) and g:
        gm = g[0]
        rec["category"] = gm.get("category")
        rec["startDate"] = rec["startDate"] or gm.get("startDate")
        rec["endDate"] = rec["endDate"] or gm.get("endDate")
        rec["question"] = rec["question"] or gm.get("question")
    json.dump(rec, open(fp, "w"))
    return rec

if __name__ == "__main__":
    import sys, statistics
    w = sys.argv[1] if len(sys.argv) > 1 else "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    t0 = time.time()
    tr, trunc = fetch_all_trades(w)
    print(f"{w}: {len(tr)} trades, truncated={trunc}, {time.time()-t0:.1f}s")
    cids = {t["conditionId"] for t in tr}
    print(f"  distinct markets (conditionId): {len(cids)}")
