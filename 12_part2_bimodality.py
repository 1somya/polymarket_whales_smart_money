"""
12_part2_bimodality.py — PART 2 (step 2): is the holder/trader split BIMODAL or a CONTINUUM,
                          plus the ruling-2 CTF/exclusion size report.

WHAT IT DOES
  1. BIMODALITY test on the two Part-2 variables (trading_share, holding_fraction_dollar
     in both strict & adjusted forms):
       - Hartigan's dip test  (H0 = unimodal; p<0.05 ⇒ reject ⇒ multimodal)
       - 1- vs 2-component Gaussian mixture, compared by BIC (lower = better)
     Verdict per variable: two real populations, or one spectrum?
  2. EXCLUSION report (ruling 2): how many wallets, and what share of cohort VOLUME and
     PnL, sit in the CTF/oversold + pure-sell buckets that the clean decomposition drops.
     This bounds how much the "trading vs holding" split is under-representing MMs.

WHAT IT CONSUMES  out/positions.csv, out/wallet_metrics.csv, out/part1_stats.json
WHAT IT PRODUCES  out/trading_share_dist.png, out/holding_fraction_dist.png + printed report
"""
import os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from diptest import diptest
from sklearn.mixture import GaussianMixture

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DIP_ALPHA = 0.05   # p below this ⇒ reject unimodality


# Two GMM components count as genuinely SEPARATED (i.e. real bimodality, not just a
# skew-absorbing second Gaussian) only if their means are far apart relative to their
# spread AND neither component is a negligible sliver.
SEP_STD_MULT = 2.0     # means must differ by >2x the larger component std
MIN_COMP_WEIGHT = 0.10 # each mode must hold >=10% of wallets to count as a population


def modality_verdict(x, name):
    """
    Decide bimodal vs continuous on a 1-D sample.

    PRIMARY test = Hartigan's dip (H0=unimodal). GMM-BIC is only a TIE-BREAKER and is
    read with care: BIC routinely prefers k=2 just to absorb skew/fat tails, so a k=2
    preference is treated as real bimodality ONLY if the two fitted components are
    actually SEPARATED (see constants). This avoids calling a one-population spike
    'bimodal' merely because a second Gaussian improved the fit.
    """
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    dip, pval = diptest(x)
    X = x.reshape(-1, 1)
    bics = {}
    gm2 = None
    for k in (1, 2):
        gm = GaussianMixture(n_components=k, n_init=5, random_state=0).fit(X)
        bics[k] = gm.bic(X)
        if k == 2:
            gm2 = gm
    means = gm2.means_.ravel()
    stds = np.sqrt(gm2.covariances_.ravel())
    weights = gm2.weights_.ravel()
    sep = abs(means[0] - means[1])
    separated = (sep > SEP_STD_MULT * stds.max()) and (weights.min() >= MIN_COMP_WEIGHT)
    gmm_prefers_2 = bics[2] < bics[1]

    dip_multimodal = pval < DIP_ALPHA
    # Verdict: dip is authoritative. Only overrule toward bimodal if dip ALSO rejects
    # unimodality; a separated GMM with a non-significant dip is still 'continuous'.
    if dip_multimodal and gmm_prefers_2 and separated:
        verdict = "BIMODAL (two separated populations)"
    else:
        verdict = "CONTINUOUS / unimodal (single population)"
    print(f"  {name}:")
    print(f"    dip={dip:.4f}  p={pval:.3f}  -> {'MULTIMODAL' if dip_multimodal else 'unimodal'} (primary test)")
    print(f"    GMM k2 comps: means={means.round(3)} weights={weights.round(2)} "
          f"-> {'separated' if separated else 'OVERLAPPING (skew-absorbing, not a 2nd mode)'}")
    print(f"    BIC k1={bics[1]:.0f} k2={bics[2]:.0f} (prefers {'2' if gmm_prefers_2 else '1'})")
    print(f"    VERDICT: {verdict}")
    return verdict


def main():
    df = pd.read_csv(os.path.join(OUT, "wallet_metrics.csv"))
    pos = pd.read_csv(os.path.join(OUT, "positions.csv"))
    stats = json.load(open(os.path.join(OUT, "part1_stats.json")))

    print("=" * 72)
    print("PART 2 — BIMODALITY of the holder/trader split")
    print("=" * 72)
    v_ts = modality_verdict(df.trading_share, "trading_share")
    v_hfs = modality_verdict(df.holding_fraction_dollar_strict, "holding_fraction_dollar_STRICT")
    v_hfa = modality_verdict(df.holding_fraction_dollar_adjusted, "holding_fraction_dollar_ADJUSTED")
    print(f"\n  strict vs adjusted conclusion differs? "
          f"{'YES' if v_hfs != v_hfa else 'no — same verdict under both'}")

    # ---- plots ----
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(df.trading_share.dropna(), bins=40, color="#4C78A8", edgecolor="white")
    ax.set(title="trading_share (profit-weighted): ~0 holder, ~1 trader",
           xlabel="trading_share", ylabel="wallets")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "trading_share_dist.png"), dpi=110)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(df.holding_fraction_dollar_strict.dropna(), bins=40, alpha=0.6, label="strict", color="#4C78A8")
    ax.hist(df.holding_fraction_dollar_adjusted.dropna(), bins=40, alpha=0.6, label="adjusted", color="#F58518")
    ax.set(title="holding_fraction_dollar (strict vs adjusted)", xlabel="fraction", ylabel="wallets")
    ax.legend(); fig.tight_layout(); fig.savefig(os.path.join(OUT, "holding_fraction_dist.png"), dpi=110)

    # ---------------------------------------------------------------
    # RULING-2 EXCLUSION REPORT
    # ---------------------------------------------------------------
    print("\n" + "=" * 72)
    print("EXCLUSION REPORT (ruling 2) — what the clean decomposition leaves out")
    print("=" * 72)
    pos["vol"] = pos.buy_usd + pos.sell_usd
    total_positions_vol = pos.vol.sum()
    pure_sell_vol = float(stats.get("skipped_pure_sell_usd", 0.0))
    total_cohort_vol = total_positions_vol + pure_sell_vol   # positions.csv + skipped pure-sells

    oversold = pos[pos.oversold == 1]
    over_vol = oversold.vol.sum()
    over_pnl = oversold.pnl_total.sum()
    clean = pos[(pos.resolved == 1) & (pos.oversold == 0)]
    clean_pnl = clean.pnl_total.sum()

    # wallets touched by exclusions
    n_wallets_recon = pos.wallet.nunique()
    w_oversold = oversold.wallet.nunique()
    # per-wallet oversold intensity
    per_w = pos.groupby("wallet").apply(
        lambda g: pd.Series({"over_frac": (g.oversold == 1).mean(),
                             "over_vol_frac": g.loc[g.oversold == 1, "vol"].sum() / g.vol.sum() if g.vol.sum() > 0 else 0}),
        include_groups=False)
    heavy = per_w[per_w.over_vol_frac > 0.25]   # >25% of their volume is oversold/CTF

    print(f"reconstructed wallets                         : {n_wallets_recon}")
    print(f"wallets with ANY oversold/CTF position        : {w_oversold} ({w_oversold/n_wallets_recon:.0%})")
    print(f"wallets >25% of volume in oversold/CTF        : {len(heavy)} ({len(heavy)/n_wallets_recon:.0%})")
    print()
    print(f"total cohort volume (positions + pure-sells)  : ${total_cohort_vol/1e6:,.0f}M")
    print(f"  excluded — oversold/CTF volume              : ${over_vol/1e6:,.0f}M ({over_vol/total_cohort_vol:.1%})")
    print(f"  excluded — pure-sell (maker-sell) volume    : ${pure_sell_vol/1e6:,.0f}M ({pure_sell_vol/total_cohort_vol:.1%})")
    print(f"  => total volume outside clean decomposition : {(over_vol+pure_sell_vol)/total_cohort_vol:.1%}")
    print()
    print(f"resolved PnL — clean decomposable             : ${clean_pnl/1e6:,.1f}M")
    print(f"resolved PnL — excluded oversold/CTF          : ${over_pnl/1e6:,.1f}M "
          f"({over_pnl/(clean_pnl+over_pnl):.1%} of resolved PnL, excluded)")
    print()
    print("INTERPRETATION: the 'trading vs holding' split is measured on the clean")
    print("decomposable set only. Market-makers/arbitrageurs trade heavily as makers and")
    print("via CTF split/merge, so a large share of the EXCLUDED volume above is theirs —")
    print("their trading edge is invisible here. Carry this caveat prominently into Part 5.")


if __name__ == "__main__":
    main()
