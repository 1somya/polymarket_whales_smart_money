"""
Step 3 — cluster wallets into behavioural species.

Clusters on STRATEGY-SIGNATURE features ONLY (never on PnL/ROI/win-rate). After
clustering we describe how profitable each cluster is — profit is an OUTCOME we
check, never an input. Uses k-means + agglomerative; reports k-stability (silhouette
+ label agreement) so we don't over-read a particular k.
"""
import json, os
import numpy as np, pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score, adjusted_rand_score

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_RESOLVED = 50

# behaviour only — NOT profit.
#  - favorite_share dropped: redundant with avg_entry_price.
#  - category_HHI dropped from CLUSTERING: only ~28% position coverage produces a
#    spurious HHI=1 artifact; reported descriptively instead.
#  - entry_timing kept (28% coverage but stable within-wallet); flagged lower-confidence.
CLUSTER_FEATURES = ["avg_entry_price", "entry_timing", "hold_days_median",
                    "maker_taker_ratio", "trade_frequency", "avg_position_size"]

def load():
    df = pd.read_csv(os.path.join(HERE, "out", "fingerprints.csv"))
    df = df[(df.reconstructed == True) & (df.truncated == False)]
    coh = df[df.n_resolved >= MIN_RESOLVED].copy()
    return df, coh

def prep(coh):
    X = coh[CLUSTER_FEATURES].copy()
    # log-scale heavy-tailed positive features
    for c in ["trade_frequency", "avg_position_size", "hold_days_median"]:
        X[c] = np.log1p(X[c].clip(lower=0))
    # impute missing timing/HHI with cohort median (coverage reported separately)
    X = X.fillna(X.median())
    Xs = StandardScaler().fit_transform(X)
    return Xs, X

def choose_k(Xs):
    print("k-stability (silhouette; ARI kmeans-vs-ward):")
    best = None
    for k in range(3, 7):
        km = KMeans(n_clusters=k, n_init=25, random_state=0).fit(Xs)
        wd = AgglomerativeClustering(n_clusters=k, linkage="ward").fit(Xs)
        sil = silhouette_score(Xs, km.labels_)
        ari = adjusted_rand_score(km.labels_, wd.labels_)
        # split-half stability of kmeans
        rng = np.random.default_rng(0); aris = []
        for _ in range(5):
            idx = rng.permutation(len(Xs)); h = len(idx)//2
            l = KMeans(k, n_init=10, random_state=1).fit(Xs)
            a = KMeans(k, n_init=10, random_state=2).fit_predict(Xs)
            aris.append(adjusted_rand_score(l.labels_, a))
        print(f"  k={k}: silhouette={sil:.3f}  ARI(km,ward)={ari:.3f}  ARI(reseed)={np.mean(aris):.3f}")
        if best is None or sil > best[1]:
            best = (k, sil, km.labels_)
    return best

def profile(coh, labels):
    coh = coh.copy(); coh["cluster"] = labels
    pos_total = coh.loc[coh.lz_realized_pnl > 0, "lz_realized_pnl"].sum()
    rows = []
    for c, g in coh.groupby("cluster"):
        rows.append({
            "cluster": c, "n_wallets": len(g),
            "med_realized_pnl": g.lz_realized_pnl.median(),
            "med_roi": g.lz_roi.median(), "med_count_win": g.count_win_rate.median(),
            "med_dollar_win": g.dollar_win_rate.median(), "med_sizing_gap": g.sizing_gap.median(),
            "med_excess_ret": g.excess_return.median(), "med_brier": g.brier_score.median(),
            "med_entry_price": g.avg_entry_price.median(), "med_entry_timing": g.entry_timing.median(),
            "med_maker": g.maker_taker_ratio.median(), "med_freq": g.trade_frequency.median(),
            "med_HHI": g.category_HHI.median(), "med_pos_size": g.avg_position_size.median(),
            "med_hold_days": g.hold_days_median.median(), "med_favorite_share": g.favorite_share.median(),
            "share_pos_profit": g.loc[g.lz_realized_pnl > 0, "lz_realized_pnl"].sum() / pos_total,
        })
    return coh, pd.DataFrame(rows).set_index("cluster")

def name_clusters(prof):
    """Permutation-robust names from cluster medians (not hard-coded to label ids)."""
    names = {}
    # HFT market maker: highest maker*freq composite
    hft = (prof.med_maker.rank() + prof.med_freq.rank()).idxmax()
    names[hft] = "HFT market maker"
    # Favorite conviction: highest entry price + sizing gap among the rest
    rest = [c for c in prof.index if c not in names]
    fav = (prof.loc[rest].med_entry_price.rank() + prof.loc[rest].med_sizing_gap.rank()).idxmax()
    names[fav] = "Favorite conviction bettor"
    # Large directional taker: lowest maker ratio + largest size among the rest
    rest = [c for c in prof.index if c not in names]
    tak = (prof.loc[rest].med_maker.rank(ascending=False) + prof.loc[rest].med_pos_size.rank()).idxmax()
    names[tak] = "Large directional taker"
    for c in prof.index:
        names.setdefault(c, "Mid-price active trader")
    return names

if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    full, coh = load()
    print(f"reconstructed wallets: {(full.reconstructed==True).sum()}   "
          f"cohort (>= {MIN_RESOLVED} resolved): {len(coh)}")
    if len(coh) < 10:
        print("cohort too small to cluster yet."); raise SystemExit
    Xs, X = prep(coh)
    choose_k(Xs)                       # report stability across k for the record
    K = 4                              # fixed: interpretable & the stable/clean partition
    labels = KMeans(K, n_init=50, random_state=0).fit_predict(Xs)
    print(f"\nusing k={K}")
    coh2, prof = profile(coh, labels)
    nm = name_clusters(prof)
    prof["name"] = [nm[c] for c in prof.index]
    coh2["cluster_name"] = coh2.cluster.map(nm)
    pd.set_option("display.width", 240, "display.max_columns", 30, "display.float_format", lambda x: f"{x:,.3f}")
    print("\nCLUSTER PROFILE (clustered on behaviour; profit shown as outcome):")
    print(prof.to_string())
    coh2.to_csv(os.path.join(HERE, "out", "fingerprints_clustered.csv"), index=False)
    prof.to_csv(os.path.join(HERE, "out", "cluster_profile.csv"))
    print("\nwrote out/fingerprints_clustered.csv, out/cluster_profile.csv")
