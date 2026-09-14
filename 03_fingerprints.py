"""
Step 2 — behavioural fingerprints. Resumable driver.

Runs reconstruction over leaderboard wallets (rank order by total_pnl), computes
the full fingerprint, and appends one row per wallet to out/fingerprints.csv.

Wallets whose lum.id trade count exceeds BOT_SKIP are NOT reconstructed (would take
too long via subgraph); they are recorded with reconstructed=False so they can be
typed descriptively from aggregate signature (these are the HFT/market-maker scale).
Wallets whose fills hit FILL_CAP are marked truncated and excluded from fingerprints.
"""
import json, os, sys, math, time, csv
from collections import Counter
import lib_recon as R

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_SKIP = 300_000      # lum.id trades above this -> don't reconstruct (bot-scale)
FILL_CAP = 80_000       # per-wallet fill ceiling (lib_subgraph enforces)
OUT = os.path.join(HERE, "out", "fingerprints.csv")

def fingerprint(wallet, lz):
    r = R.reconstruct(wallet)
    P = r["positions"]
    res = [p for p in P if p["resolved"]]
    row = {
        "wallet": wallet, "primary_style": lz["primary_style"],
        "lz_total_pnl": lz["total_pnl"], "lz_realized_pnl": lz["realized_pnl"],
        "lz_roi": lz["roi"], "lz_win_rate": lz["win_rate"], "lz_volume": lz["volume"],
        "lz_trades": lz["trades"], "first_trade_at": lz["first_trade_at"],
        "reconstructed": True, "truncated": r["truncated"],
        "n_fills": r["n_fills"], "n_positions": len(P), "n_resolved": len(res),
        "n_markets": len({p["condition"] for p in P}),
        "recon_realized_pnl": sum(p["realized_pnl"] for p in res),
        "maker_taker_ratio": r.get("maker_share"),
        "trade_frequency": r["n_fills"] / max(r.get("active_days", 0) or 1, 1),
        "active_days": r.get("active_days"),
    }
    if res:
        stake = sum(p["stake"] for p in res)
        wstake = sum(p["stake"] for p in res if p["won"])
        wins = sum(p["won"] for p in res)
        row["count_win_rate"] = wins / len(res)
        row["dollar_win_rate"] = wstake / stake if stake else None
        row["sizing_gap"] = (wstake / stake - wins / len(res)) if stake else None
        row["avg_entry_price"] = sum(p["entry_price"] * p["stake"] for p in res) / stake if stake else None
        row["excess_return"] = sum(((1.0 if p["won"] else 0.0) - p["entry_price"]) / p["entry_price"]
                                   for p in res if p["entry_price"] > 0) / len(res)
        row["brier_score"] = sum((p["entry_price"] - (1.0 if p["won"] else 0.0))**2 for p in res) / len(res)
        row["favorite_share"] = sum(p["stake"] for p in res if p["entry_price"] > 0.5) / stake if stake else None
        row["avg_position_size"] = sorted(p["stake"] for p in res)[len(res)//2]     # median stake
        tim = [p["timing"] for p in res if p["timing"] is not None]
        row["entry_timing"] = sum(tim)/len(tim) if tim else None
        row["timing_coverage"] = len(tim)/len(res)
        holds = sorted(p["hold_days"] for p in res)
        row["hold_days_median"] = holds[len(holds)//2]
        cats = [p["category"] for p in res if p["category"]]
        if cats:
            c = Counter(cats); tot = sum(c.values())
            row["category_HHI"] = sum((v/tot)**2 for v in c.values())
            row["category_coverage"] = len(cats)/len(res)
            row["top_category"] = c.most_common(1)[0][0]
    return row

FIELDS = ["wallet","primary_style","reconstructed","truncated","n_fills","n_positions",
          "n_resolved","n_markets","recon_realized_pnl","lz_total_pnl","lz_realized_pnl",
          "lz_roi","lz_win_rate","lz_volume","lz_trades","first_trade_at","active_days",
          "count_win_rate","dollar_win_rate","sizing_gap","avg_entry_price","excess_return",
          "brier_score","favorite_share","avg_position_size","maker_taker_ratio",
          "trade_frequency","entry_timing","timing_coverage","hold_days_median",
          "category_HHI","category_coverage","top_category"]

def main(limit=500):
    board = json.load(open(os.path.join(HERE, "data", "lumid_full.json")))
    board.sort(key=lambda r: -r["total_pnl"])
    done = set()
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT)):
            done.add(r["wallet"])
    write_header = not os.path.exists(OUT)
    f = open(OUT, "a", newline="")
    wr = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if write_header: wr.writeheader()
    t0 = time.time()
    for i, lz in enumerate(board[:limit]):
        w = lz["wallet"]
        if w in done: continue
        fills_cached = os.path.exists(os.path.join(HERE, "data", "fills", f"{w.lower()}.json"))
        if not fills_cached:
            # not in the fetched cohort (bot-scale or post-cutoff) -> aggregate-only row
            wr.writerow({"wallet": w, "primary_style": lz["primary_style"], "reconstructed": False,
                         "truncated": True, "lz_total_pnl": lz["total_pnl"],
                         "lz_realized_pnl": lz["realized_pnl"], "lz_roi": lz["roi"],
                         "lz_win_rate": lz["win_rate"], "lz_volume": lz["volume"],
                         "lz_trades": lz["trades"], "first_trade_at": lz["first_trade_at"]})
            f.flush(); continue
        try:
            row = fingerprint(w, lz)
            wr.writerow(row); f.flush()
            print(f"[{i+1}/{limit}] {w[:10]} fills={row['n_fills']:>6} "
                  f"resolved={row['n_resolved']:>4} pnl_recon=${row['recon_realized_pnl']:>12,.0f} "
                  f"[{time.time()-t0:.0f}s]", flush=True)
        except Exception as e:
            print(f"[{i+1}] {w[:10]} ERROR {e}", flush=True)
    f.close()

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
