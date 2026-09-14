"""
PROBE 2 — depth / pagination / coverage of the findata trades endpoint.
Answers the questions that decide whether this source is usable:
  - full field list (is there a maker leg, or taker-only like data-api?)
  - is 500 a hard cap? do limit/offset/cursor/before params work?
  - how far back in time does the returned window reach? (recent-only?)
"""
import json, urllib.request, urllib.error, sys

UA = {"User-Agent": "Mozilla/5.0 (research; polymarket-whale-taxonomy)"}
BASE = "https://lum.id/findata/prediction-markets/trades/polymarket"
cid = sys.argv[1]


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def trange(rows):
    ts = [r["ts"] for r in rows if "ts" in r]
    return (min(ts), max(ts)) if ts else ("-", "-")


# ---- baseline ----
st, base = get(f"{BASE}/{cid}")
print("baseline:", st, "n=", len(base) if isinstance(base, list) else base)
if isinstance(base, list) and base:
    print("ALL fields in element 0:")
    for k, v in base[0].items():
        print(f"    {k}: {type(v).__name__} = {v!r}")
    lo, hi = trange(base)
    print(f"ts span of the {len(base)} rows: {lo}  ->  {hi}")
    # is there any maker-side identity?
    print("has 'maker'-like key:", [k for k in base[0] if "mak" in k.lower()])
    print("distinct wallets (taker) in window:", len({r.get("taker") for r in base}))

# ---- pagination attempts: does the count exceed 500? ----
print("\n-- param probes (looking for >500 or a different time window) --")
for q in ["limit=1000", "limit=2000", "offset=500", "offset=500&limit=500",
          "page=2", "cursor=1", "before=2026-07-21T00:00:00Z", "days=90"]:
    st, r = get(f"{BASE}/{cid}?{q}")
    if isinstance(r, list):
        lo, hi = trange(r)
        print(f"  ?{q:35s} -> {st} n={len(r):4d}  ts[{lo} .. {hi}]")
    else:
        print(f"  ?{q:35s} -> {st} {str(r)[:80]}")
