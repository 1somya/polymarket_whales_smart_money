"""
Goldsky subgraph client + fill-based position reconstruction.

WHY THIS EXISTS: Polymarket's data-api /trades is hard-capped at ~4000 most-recent
fills per wallet and ignores time-window params, so full history of any active
wallet is unreachable there. The legacy Goldsky subgraphs expose the complete
on-chain CLOB order-fill log, paginable past the skip-limit via a timestamp cursor.

LIMITATIONS (must be stated in any writeup):
  - Legacy subgraphs stop indexing at the 2026-04-28 v2 contract migration.
  - Reconstruction uses CLOB OrderFilled events only; CTF split/merge/redeem are
    not modeled, so cost-basis is approximate for heavy full-set minters.
"""
import json, os, time, socket, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PROJ = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs"
OB   = f"{PROJ}/orderbook-subgraph/0.0.1/gn"
POSG = f"{PROJ}/positions-subgraph/0.0.7/gn"
PNLG = f"{PROJ}/pnl-subgraph/0.0.14/gn"
HDR  = {"User-Agent": "Mozilla/5.0 (research)", "Content-Type": "application/json"}

def gq(url, query, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps({"query": query}).encode(), headers=HDR)
            r = json.load(urllib.request.urlopen(req, timeout=90))
            if "errors" in r:
                time.sleep(1.0 * (i + 1)); continue
            return r["data"]
        # NB: in Python 3.9 socket.timeout is NOT a subclass of TimeoutError, so it must
        # be caught explicitly or a read-timeout escapes the retry loop. OSError covers
        # connection resets / broken pipes on long paginated pulls.
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                socket.timeout, OSError, json.JSONDecodeError):
            time.sleep(1.2 * (i + 1))
    return None

# ---------------- fills for a wallet (capped, timestamp cursor) ----------------
class FetchError(RuntimeError):
    pass

def _walk(w, cap, out, seen, seen_orders, last_ts):
    """Shared pagination core: walk orderFilledEvents ascending from `last_ts`,
    appending fresh rows into `out`/`seen`/`seen_orders` (mutated in place) until
    `cap` distinct orders are seen or history runs out. `out`/`seen`/`seen_orders`
    may be pre-seeded from an existing cache to RESUME a previously truncated
    wallet instead of starting from scratch. Returns (out, truncated)."""
    truncated = False
    while True:
        q = ('{ orderFilledEvents(first:1000, orderBy:timestamp, orderDirection:asc,'
             'where:{and:[{timestamp_gte:%d},{or:[{maker:"%s"},{taker:"%s"}]}]}){'
             'id orderHash timestamp maker taker makerAssetId takerAssetId makerAmountFilled takerAmountFilled }}'
             % (last_ts, w, w))
        d = gq(OB, q)
        if d is None:                      # error, NOT a true empty page -> do not cache
            raise FetchError(f"query failed for {w} at ts>={last_ts}")
        rows = d.get("orderFilledEvents", [])
        if not rows: break
        fresh = [r for r in rows if r["id"] not in seen]
        for r in fresh:
            seen.add(r["id"]); out.append(r)
            seen_orders.add(r["orderHash"])
        if len(seen_orders) >= cap:
            truncated = True; break
        if len(rows) < 1000: break
        last_ts = int(rows[-1]["timestamp"])
    return out, truncated

def fetch_fills(wallet, cap=8_000):
    """CLOB order fills where wallet is maker or taker, ascending time, up to `cap`
    DISTINCT ORDERS (by orderHash) — not fills; one resting order can produce many
    fills at the same price, so capping on orders lets the walk go much deeper into
    a market-maker wallet's real history for the same budget.
    Cached. Returns (fills, truncated). truncated=True iff we stopped at `cap` (there
    is more history than we pulled). Raises FetchError on a network/query failure so
    the caller can skip the wallet rather than silently cache a truncated/empty result."""
    w = wallet.lower()
    fp = os.path.join(DATA, "fills", f"{w}.json")
    if os.path.exists(fp):
        o = json.load(open(fp)); return o["fills"], o["truncated"]
    out, truncated = _walk(w, cap, [], set(), set(), 0)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    tmp = fp + ".tmp"
    json.dump({"fills": out, "truncated": truncated}, open(tmp, "w"))
    os.replace(tmp, fp)
    return out, truncated

# ---------------- normalize a fill into (token, side, size, price, ts, is_maker) ----------------
def normalize(fill, wallet):
    w = wallet.lower()
    mk_a, tk_a = fill["makerAssetId"], fill["takerAssetId"]
    mk_amt, tk_amt = int(fill["makerAmountFilled"]), int(fill["takerAmountFilled"])
    is_maker = fill["maker"].lower() == w
    # identify the outcome token (non-USDC leg) and USDC leg
    if mk_a == "0":            # maker gives USDC, receives token -> maker BUYS token
        token, usdc, toks = tk_a, mk_amt, tk_amt
        maker_side = "BUY"
    elif tk_a == "0":          # taker gives USDC, receives token -> taker BUYS token
        token, usdc, toks = mk_a, tk_amt, mk_amt
        maker_side = "SELL"
    else:
        return None            # token<->token (rare merge-like); skip
    if toks == 0: return None
    price = usdc / toks                       # USDC per token (both 6dp -> ratio unitless)
    side = maker_side if is_maker else ("SELL" if maker_side == "BUY" else "BUY")
    return {"token": token, "side": side, "size": toks / 1e6, "usdc": usdc / 1e6,
            "price": price, "ts": int(fill["timestamp"]), "is_maker": is_maker,
            "orderHash": fill.get("orderHash")}

if __name__ == "__main__":
    import sys, statistics as st
    w = sys.argv[1] if len(sys.argv) > 1 else "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    t0 = time.time(); fills, tr = fetch_fills(w)
    norm = [n for f in fills if (n := normalize(f, w))]
    toks = {n["token"] for n in norm}
    print(f"{w}: {len(fills)} fills ({len(norm)} priced), {len(toks)} distinct tokens, "
          f"truncated={tr}, {time.time()-t0:.1f}s")
    if norm:
        print(" price range:", round(min(n['price'] for n in norm),3), "-", round(max(n['price'] for n in norm),3))
        print(" maker share:", round(st.mean(n['is_maker'] for n in norm),3))
