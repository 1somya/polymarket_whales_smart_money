"""
PROBE 4 — clean test of retention-after-resolution, the crux for the gap.
Pick genuinely recently-resolved, previously-LIQUID markets (closed=true, high
volume, endDate in the recent past) and see if their tape survives resolution.
Also: cross-check completeness on one OPEN market against data-api taker fills.
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


print("== (B') retention on recently-resolved, high-volume markets ==")
# closed markets, most volume first; keep those whose endDate is a real recent past date
_, ms = get(f"{GAMMA}?closed=true&order=volume&ascending=false&limit=60")
picked = 0
for m in ms:
    end = (m.get("endDate") or "")[:10]
    if not ("2026-05-01" <= end <= "2026-07-21"):
        continue
    cid = m.get("conditionId")
    st, r = get(f"{BASE}/{cid}?limit=2000")
    n = len(r) if isinstance(r, list) else r
    vol = m.get("volume") or m.get("volumeNum")
    print(f"  end={end}  vol={str(vol)[:9]:>9}  n={str(n):>5}  {(m.get('question') or '')[:42]}")
    picked += 1
    if picked >= 10:
        break
if picked == 0:
    print("  (no closed market with endDate in 2026-05..07 among top-60 by volume)")
