"""
FIRST TASK (pre-Part-1): probe lum.id findata per-market trades endpoint.

Goal: determine whether
  https://lum.id/findata/prediction-markets/trades/polymarket/{conditionId}
returns PER-FILL data carrying (wallet, price, timestamp). If it does, it is a
second, independent source that might:
  (a) cross-validate the Goldsky subgraph reconstruction, and
  (b) cover the post-2026-04-28 v2-migration gap the legacy subgraphs miss.

This script ONLY probes and reports schema. It changes no project state.
"""
import json, urllib.request, urllib.error, sys

UA = {"User-Agent": "Mozilla/5.0 (research; polymarket-whale-taxonomy)"}
BASE = "https://lum.id/findata/prediction-markets/trades/polymarket"


def get(url):
    """Return (status, parsed_or_text). Never raises on HTTP error."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body[:500]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def describe(obj, depth=0, maxdepth=3):
    """Print the shape (keys/types) of a JSON object without dumping all data."""
    pad = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            t = type(v).__name__
            if isinstance(v, (dict, list)) and depth < maxdepth:
                print(f"{pad}{k}: {t}")
                describe(v, depth + 1, maxdepth)
            else:
                sample = repr(v)
                if len(sample) > 80:
                    sample = sample[:80] + "..."
                print(f"{pad}{k}: {t} = {sample}")
    elif isinstance(obj, list):
        print(f"{pad}[list len={len(obj)}]")
        if obj and depth < maxdepth:
            print(f"{pad}first element:")
            describe(obj[0], depth + 1, maxdepth)


cid = sys.argv[1]
print("=" * 70)
print("PROBE 1 — bare endpoint")
print("URL:", f"{BASE}/{cid}")
print("=" * 70)
status, obj = get(f"{BASE}/{cid}")
print("HTTP status:", status)
if isinstance(obj, (dict, list)):
    describe(obj)
    # if it's a paginated container, show total count if present
    if isinstance(obj, list):
        print(f"\n>> top-level is a LIST of {len(obj)} items")
    elif isinstance(obj, dict):
        for k in ("total", "count", "hasMore", "nextCursor", "next", "data", "trades", "results"):
            if k in obj:
                v = obj[k]
                print(f">> container field {k!r}: {type(v).__name__}"
                      + (f" (len {len(v)})" if isinstance(v, (list, dict)) else f" = {v}"))
else:
    print("non-JSON / error body:")
    print(obj)
