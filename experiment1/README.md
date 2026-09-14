# Polymarket Whale Taxonomy

Identify and categorise profitable Polymarket wallets into behavioural *species*.
Read **`FINDINGS.md`** for results. This file documents how to reproduce them.

> This is Experiment 1 of two in this repository (Experiment 2, a separate later study, lives in
> `../experiment2/`). Only this doc, `FINDINGS.md`, `WORKLOG.md`, and `whale_explorer.html`
> live under `experiment1/` — every `.py` script below, plus `data/`, `out/`, and `probes/`, are
> still flat at the repository root. Run all commands below from the repo root, not from here.

## Thesis
"Whale" is not one thing. Wallets at the top of a PnL leaderboard are structurally
different businesses (market makers, conviction bettors, directional takers…). The
leaderboard's single PnL number blends realized money, unrealized paper marks,
market-making flow, and directional skill — so its ranking is incoherent.

## Pipeline (run in order)

```bash
python3 01_leaderboard.py        # Step 1: honest realized-only leaderboard (all 500)
python3 02_fetch_fills.py 350    # Phase A: parallel-fetch order fills (cached to data/fills/)
python3 02b_prefetch_meta.py     # Phase A2: resolve token→market→winner + market metadata
python3 03_fingerprints.py 500   # Step 2: reconstruct positions → out/fingerprints.csv
python3 05_cluster.py            # Step 3: cluster on behaviour → cluster_profile.csv
python3 06_plot.py               # Step 4: out/winrate_vs_roi.png
```

Everything network-fetched is cached under `data/` (fills, token/condition maps,
market metadata), so re-runs are cheap and the run is resumable.

## Modules
- `lib_subgraph.py` — Goldsky client; `fetch_fills()` pages full history via a
  timestamp cursor (the data-api `/trades` endpoint is capped at 4,000 fills and is
  **not** used); `normalize()` turns a raw fill into side/size/price/timestamp.
- `lib_recon.py` — token→condition→winner resolution (cached) and `reconstruct()`,
  which builds per-position entry price, stake, realized PnL, win/loss, timing.
- `03_fingerprints.py` — per-wallet feature row (`fingerprint()`), incl. the
  clustering signature and the skill metrics (win rates, sizing_gap, excess_return,
  brier), with coverage flags.

## Key correctness rules enforced
- Realized and unrealized PnL are **never summed** into one ranking number.
- Market resolution is used **only after the fact** — never in a pre-resolution
  feature (entry price, timing, size, side).
- **≥ 50 resolved positions** floor for the clustering cohort; effective sample size
  reported at every step (see the funnel in `FINDINGS.md`).
- Clustering uses **behaviour only**, never PnL/ROI/win-rate.
- Metrics that cannot be computed from available data are stated, not proxied.

## Results, limitations & the honest caveats
All of that — including the biggest one (the 4-way clustering itself is statistically
weak — see `FINDINGS.md` §4b) — lives in **`FINDINGS.md`**, kept as the single source
of truth so it can't drift out of sync with this file. Read it before quoting any
number from this project.

## Requirements
Python 3.9+, `pandas numpy scikit-learn scipy matplotlib`. No API keys.
