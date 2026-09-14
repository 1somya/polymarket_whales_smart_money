"""
30_market_dates.py — PART 4 prerequisite: build a condition -> resolution-DATE map.

WHY: Part 4 bins every position by RESOLUTION DATE (rank on resolved-by-t, evaluate on
resolved-in-(t,t+3]; equity curves vs resolution date). But NO resolution timestamp
exists in our subgraph data (pnl-subgraph Condition has only payoutNumerators). The
authoritative CLOB API does expose `end_date_iso` per market — the scheduled market
close, which resolution follows within days. That is a good PROXY for resolution date
at monthly binning granularity, and it is the best available (documented as a proxy).

METHOD: page the CLOB bulk /markets endpoint (1000/page) once, cache
condition_id -> {end_date_iso, winner_token}. Cheap (~0.5s/page).

PRODUCES: data/clob_market_dates.json  + coverage report against the cohort's conditions.
"""
import os, json, time, urllib.request, urllib.error
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTFP = os.path.join(HERE, "data", "clob_market_dates.json")
UA = {"User-Agent": "Mozilla/5.0 (research; polymarket-whale-taxonomy)"}


def get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1.0 * (i + 1))
    return None


COVERAGE_TARGET = 0.98   # stop early once this share of cohort conditions have a date

def _cohort_conditions():
    """The clean-resolved conditions we actually need dates for (early-stop target)."""
    pos = pd.read_csv(os.path.join(HERE, "out", "positions.csv"))
    return set(pos[(pos.resolved == 1) & (pos.oversold == 0)].condition.dropna())

def _save_atomic(out):
    tmp = OUTFP + ".tmp"; json.dump(out, open(tmp, "w")); os.replace(tmp, OUTFP)

def build():
    need = _cohort_conditions()
    print(f"cohort conditions needing a date: {len(need)}", flush=True)
    out, cursor, t0, pages = {}, "", time.time(), 0
    # resume from an existing checkpoint if present (so a kill/restart doesn't lose work)
    if os.path.exists(OUTFP):
        out = json.load(open(OUTFP)); print(f"resumed checkpoint: {len(out)} markets", flush=True)
    while True:
        url = "https://clob.polymarket.com/markets" + (f"?next_cursor={cursor}" if cursor else "")
        d = get(url)
        if not d or not d.get("data"):
            break
        for m in d["data"]:
            cid = m.get("condition_id")
            if not cid:
                continue
            winner = next((str(t.get("token_id")) for t in m.get("tokens", []) if t.get("winner")), None)
            out[cid] = {"end": m.get("end_date_iso"), "winner": winner, "closed": m.get("closed")}
        pages += 1
        cursor = d.get("next_cursor")
        if pages % 100 == 0:
            cov = sum(1 for c in need if c in out) / max(len(need), 1)
            _save_atomic(out)
            print(f"  {pages} pages, {len(out)} markets, cohort_coverage={cov:.1%}, {time.time()-t0:.0f}s", flush=True)
            if cov >= COVERAGE_TARGET:
                print(f"  reached coverage target {COVERAGE_TARGET:.0%} — stopping early.", flush=True)
                break
        if not cursor or cursor == "LTE=":
            break
    _save_atomic(out)
    print(f"done: {len(out)} markets in {pages} pages, {time.time()-t0:.0f}s -> {OUTFP}")
    return out


def coverage(m):
    pos = pd.read_csv(os.path.join(HERE, "out", "positions.csv"))
    res = pos[(pos.resolved == 1) & (pos.oversold == 0)].copy()
    conds = set(res.condition.dropna())
    have = sum(1 for c in conds if m.get(c, {}).get("end"))
    res["has"] = res.condition.map(lambda c: bool(m.get(c, {}).get("end")))
    print(f"\ncohort clean-resolved conditions: {len(conds)}")
    print(f"  with CLOB end date : {have} ({have/len(conds):.0%})")
    print(f"  positions covered  : {res.has.mean():.0%}")
    print(f"  |PnL| covered      : {res.loc[res.has,'pnl_total'].abs().sum()/res.pnl_total.abs().sum():.0%}")


if __name__ == "__main__":
    m = build()
    coverage(m)
