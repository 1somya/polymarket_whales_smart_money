"""
Step 4 — the scatter that breaks the leaderboard's logic.

x = count_win_rate, y = ROI, dot size = volume, color = behavioural cluster.
Top-10 by total_pnl annotated. The point: profitable wallets sit at BOTH low and
high win rates, so win rate does not determine profit — the leaderboard's implicit
"more wins = better" is incoherent.
"""
import os, json
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
# Okabe-Ito: colorblind-safe categorical palette, assigned in fixed order (not cycled)
OKABE = ["#E69F00", "#0072B2", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]
INK, MUTED, GRID = "#1a1a1a", "#6b6b6b", "#e2e2e2"

def main():
    fp = os.path.join(HERE, "out", "fingerprints_clustered.csv")
    df = pd.read_csv(fp)
    board = pd.read_csv(os.path.join(HERE, "out", "leaderboard_honest.csv"))
    names = {r.wallet: (r.cluster_name if hasattr(r, "cluster_name") else r.cluster) for r in df.itertuples()}

    df = df.dropna(subset=["count_win_rate", "lz_roi", "lz_volume"]).copy()
    # robust y-limits (ROI has heavy tails); clip display, keep points at the rail
    ylo, yhi = np.percentile(df.lz_roi, 2), np.percentile(df.lz_roi, 98)
    ylo, yhi = max(ylo, -1.0), min(yhi, 4.0)
    df["y"] = df.lz_roi.clip(ylo, yhi)
    smin, smax = df.lz_volume.min(), df.lz_volume.max()
    df["s"] = 40 + 620 * (np.sqrt(df.lz_volume) - np.sqrt(smin)) / (np.sqrt(smax) - np.sqrt(smin) + 1e-9)

    clusters = sorted(df.cluster.unique())
    cmap = {c: OKABE[i % len(OKABE)] for i, c in enumerate(clusters)}
    label = {c: (df[df.cluster == c].cluster_name.iloc[0]
                 if "cluster_name" in df.columns else f"cluster {c}") for c in clusters}

    plt.rcParams.update({"font.size": 11, "axes.edgecolor": MUTED, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED})
    fig, ax = plt.subplots(figsize=(11, 7.5), dpi=140)
    ax.axhline(0, color=MUTED, lw=1, ls="--", zorder=1)
    for c in clusters:
        g = df[df.cluster == c]
        ax.scatter(g.count_win_rate, g.y, s=g.s, c=cmap[c], alpha=0.72,
                   edgecolors="white", linewidths=0.6, label=label[c], zorder=3)

    # annotate top-10 by total_pnl that are present in the cohort
    board_top = board.sort_values("total_pnl", ascending=False).head(10)
    present = df.set_index("wallet")
    for rank, (_, b) in enumerate(board_top.iterrows(), 1):
        if b.wallet in present.index:
            r = present.loc[b.wallet]
            r = r.iloc[0] if isinstance(r, pd.DataFrame) else r
            ax.annotate(f"#{rank}", (r.count_win_rate, r.y), fontsize=9, fontweight="bold",
                        color=INK, xytext=(4, 4), textcoords="offset points", zorder=5)

    ax.set_xlabel("count win rate  (winning resolved positions / resolved positions)")
    ax.set_ylabel("ROI  (lum.id; display clipped to [%.0f%%, %.0f%%])" % (ylo*100, yhi*100))
    ax.set_title("Win rate does not determine profit\nProfitable wallets appear at both low and high win rates — dot size = volume, color = behavioural species",
                 fontsize=12.5, loc="left", color=INK)
    ax.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    leg = ax.legend(title="behavioural species", loc="upper left", frameon=True,
                    fontsize=9, title_fontsize=9, framealpha=0.9)
    leg.get_frame().set_edgecolor(GRID)
    # size legend
    handles = [Line2D([0],[0], marker="o", ls="", markersize=np.sqrt(v)/3, mfc=MUTED, mec="white", alpha=0.6)
               for v in [1e6, 1e7]]
    ax.text(0.99, 0.02, "dot size ∝ √volume", transform=ax.transAxes, ha="right", color=MUTED, fontsize=8)
    fig.tight_layout()
    out = os.path.join(HERE, "out", "winrate_vs_roi.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print("wrote", out, f"({len(df)} wallets plotted)")

if __name__ == "__main__":
    main()
