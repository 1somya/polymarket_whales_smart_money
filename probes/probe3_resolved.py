"""
PROBE 3 — the two facts that decide usability:
  (A) max limit / how far back the tape reaches for a long-lived market
  (B) do RECENTLY-RESOLVED markets return trades, or only OPEN ones?
      (B) is decisive: Part 1 needs resolved markets. If resolution empties the
      tape, this source cannot fill the post-April-2026 gap.
"""
import json, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; polymarket-whale-taxonomy)"}
BASE = "https://lum.id/findata/prediction-markets/trades/polymarket"
GAMMA = "https://gamma-api.polymarket.com/markets"


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def span(rows):
    ts = sorted(r["ts"] for r in rows if "ts" in r)
    return (ts[0], ts[-1]) if ts else ("-", "-")


# (A) find a long-lived, still-open, high-volume market and push limit hard
print("== (A) max-limit / history depth on a long-lived OPEN market ==")
_, ms = get(f"{GAMMA}?closed=false&order=volume&ascending=false&limit=20")
longlived = None
for m in ms:
    sd = m.get("startDate", "") or ""
    if sd < "2026-03-01":  # started before the April migration
        longlived = m
        break
if longlived:
    cid = longlived["conditionId"]
    print(f"market: {(longlived.get('question') or '')[:55]}")
    print(f"  startDate={longlived.get('startDate')}  cid={cid}")
    for lim in (5000, 20000, 100000):
        st, r = get(f"{BASE}/{cid}?limit={lim}")
        if isinstance(r, list):
            lo, hi = span(r)
            print(f"  limit={lim:6d} -> n={len(r):6d}  ts[{lo} .. {hi}]")
        else:
            print(f"  limit={lim:6d} -> {st} {r}")
else:
    print("  (no long-lived open market found in top-20 by volume)")

# (B) recently-resolved markets
print("\n== (B) do RECENTLY-RESOLVED markets return trades? ==")
_, closed = get(f"{GAMMA}?closed=true&order=endDate&ascending=false&limit=8")
for m in closed:
    cid = m.get("conditionId")
    if not cid:
        continue
    st, r = get(f"{BASE}/{cid}?limit=1000")
    n = len(r) if isinstance(r, list) else r
    print(f"  end={str(m.get('endDate'))[:10]}  n={str(n):>5}  {(m.get('question') or '')[:45]}")
