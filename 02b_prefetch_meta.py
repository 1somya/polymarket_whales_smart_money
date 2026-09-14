"""
Phase A2 — populate resolution + market-metadata caches for every market the cohort
traded, so reconstruction (phase B) is pure-local and fast.

  1. load all cached wallet fills -> collect distinct outcome tokens
  2. batch token -> conditionId  (positions subgraph)
  3. batch conditionId -> payout/winner  (pnl subgraph)
  4. parallel conditionId -> {category, open, close}  (CLOB)
"""
import json, os, glob
import lib_subgraph as sg
import lib_recon as R

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    files = glob.glob(os.path.join(sg.DATA, "fills", "*.json"))
    print(f"cached wallets: {len(files)}")
    tokens = set()
    for f in files:
        o = json.load(open(f))
        for fl in o["fills"]:
            for a in (fl["makerAssetId"], fl["takerAssetId"]):
                if a != "0":
                    tokens.add(a)
    print(f"distinct outcome tokens: {len(tokens):,}")
    tok2cond, cond = R.resolve_tokens(sorted(tokens))
    conds = sorted({c for c in tok2cond.values() if c})
    resolved = sum(1 for c in conds if cond.get(c, {}).get("resolved"))
    print(f"distinct conditions: {len(conds):,}  resolved: {resolved:,}")
    n = R.prefetch_market_meta(conds, workers=10)
    g = R._load(R.GAMMA_FP)
    with_cat = sum(1 for c in conds if g.get(c, {}).get("category"))
    with_time = sum(1 for c in conds if g.get(c, {}).get("start") and g.get(c, {}).get("end"))
    print(f"market-meta cached: {n:,}  with category: {with_cat:,}  with open/close: {with_time:,}")

if __name__ == "__main__":
    main()
