# Polymarket Whale Taxonomy — Findings

*What are the distinct species of profitable wallet, how does each make money, and
what fraction of profit does each capture?*

---

## TL;DR

1. **The leaderboard's number is a blend, and it misranks the middle.** lum.id's
   `total_pnl` mixes realized money with unrealized paper marks. Re-ranking by
   **realized-only** leaves the **top-10 stable** but reshuffles the 20–500 tier by a
   **median of 17 places** (max 487). **19 of 500** "top-PnL" wallets have *negative*
   realized PnL; one sits at rank #12 on paper but #499 on realized money.

2. **"Whale" is not one thing — but it's a continuum, not four clean types.**
   Behaviour splits cleanly along **one robust axis** (liquidity/high-frequency vs.
   directional betting), and **one group is genuinely distinct** — HFT market makers,
   the single largest profit share. Beyond that, a 4-way clustering was tried and
   found **statistically weak** (§4b) — the four labels below are useful, real
   *economic* regions of a continuum, not separable species. Read them that way.

3. **Most winners have no per-bet forecasting edge.** In 3 of the 4 labeled groups the
   median `excess_return` is **negative** — they win/profit *without* beating the price
   they paid. Profit comes from **conviction sizing** (bet bigger when right) and
   **market-making volume**, not from being a better forecaster per trade. This is why
   the #1 wallet earns +110% ROI at a **46% win rate**.

4. **Win rate does not determine profit** (see `out/winrate_vs_roi.png`) — and "win
   rate" itself is a slippery, multiply-defined number (§6). Profitable wallets appear
   at count-win-rates from **0.19 to 0.84**. Ranking by win rate — or by the blended
   PnL that correlates with it — is incoherent.

> **Read every number below against the hard limits in §2:** we see only the
> *top of the leaderboard* (no losers → survivorship), the behavioural cohort is
> **95 wallets holding 21% of top-500 realized profit**, and the 4-way clustering
> itself is statistically fragile (§4b) — stated up front, not buried in an appendix.

---

## 1. Data & method

| Need | Source | Note |
|---|---|---|
| Wallet leaderboard | lum.id `/leaderboard` | 500 rows; gives realized *and* total PnL separately |
| Full per-fill history | **Goldsky `orderbook` subgraph** (`orderFilledEvents`) | the data-api `/trades` is **hard-capped at 4,000 fills** and ignores time filters — unusable; the subgraph pages uncapped |
| Token → market | Goldsky `positions` subgraph (`tokenIdConditions`) | |
| Resolution / winner | Goldsky `pnl` subgraph (`Condition.payoutNumerators`) | |
| Category, open/close | CLOB `/markets/{cid}` (`tags`, `accepting_order_timestamp`, `end_date_iso`) | |

**Reconstruction.** For each wallet we pull every CLOB order fill, group into
per-outcome-token positions, and — using resolution known *only after the fact* —
compute realized PnL, entry VWAP, win/loss, sizing, timing. **Resolution never enters
any pre-resolution feature.** Reconstructed realized PnL correlates **0.85** with
lum.id's realized figure across the cohort (validates the method); we nonetheless use
**lum.id's realized_pnl as the authoritative profit number** and reconstruction only
for behaviour — see split/merge caveat in §7.

**We never sum realized and unrealized into one number.**

### Effective sample sizes (the funnel)

```
500  leaderboard wallets (top by total_pnl)
 66  first traded AFTER 2026-04-28  → invisible to the legacy subgraph
278  genuinely reconstructed (>0 fills)
197  fully reconstructed (not truncated at the 40k-fill cap)
102    …but < 50 resolved positions  → concentrated bettors, below the noise floor
 95  CLEAN COHORT (>= 50 resolved)   → this is what we cluster
 81  truncated at 40k fills (high-frequency) → typed, not in the clean cohort
```

The clean cohort of **95 wallets holds \$127M of realized profit = 21.3%** of the
top-500's \$598M. **The taxonomy characterises the engine room of active winners, not
the whole leaderboard.**

---

## 2. Limitations that bound every claim

- **Survivorship (structural).** The source is the *top-500 by PnL*. There are **no
  losing wallets in the data at all.** We can describe *species of winner*; we **cannot**
  say what distinguishes winners from losers, because we never observe a loser. Any
  "follow this type" conclusion is out of reach from this dataset alone. (Experiment 2,
  a separate later study, builds a survivorship-corrected cohort with real losers —
  see `../experiment2/`.)
- **Coverage.** (a) 66 wallets (13%, ~16% of realized profit) first traded after the
  **2026-04-28** subgraph cutoff and cannot be reconstructed. (b) Some wallets trade
  mainly via negRisk/AMM, not the CLOB order book, and are invisible to
  `orderFilledEvents` (this, plus the floor, is why **8 of the top-10 by PnL are absent
  from the cohort**). (c) `entry_timing` and `category_HHI` have only ~28% position-level
  coverage (older sports/hourly markets lack CLOB metadata); `category_HHI` was therefore
  **dropped from clustering** and `entry_timing` is flagged lower-confidence.
- **Cost basis.** CTF split/merge/redeem operations aren't modeled, so reconstructed
  *cost basis* is approximate for heavy full-set minters (some market-makers); we defer
  to lum.id for profit magnitude and use reconstruction only for behaviour.
- **The 4-way clustering is statistically weak** (silhouette ≈0.18, algorithms
  disagree, density methods reject it — full audit in §4b). Treat the four labels as
  descriptive regions, not proven species.
- **Small n.** 95 wallets is a modest sample for clustering at all, which contributes
  to the fuzzy structure in §4b.

---

## 3. Step 1 — the honest (realized-only) leaderboard

Ranking by `realized_pnl` instead of `total_pnl`:

- **Top-10 unchanged** — the headline names *are* backed by realized money.
- **20–500 tier reshuffles:** Spearman ρ = 0.82, **median rank change 17**, max **487**.
- **19/500** wallets have **negative** realized PnL despite being on a top-PnL board.
- Worst offender: rank **#12 → #499**. Its \$7.3M "PnL" is **−\$4.8M realized + \$12.1M
  unrealized** paper on open positions, reported by lum.id with a fake **100% win rate**
  (unresolved positions counted as wins). → `out/leaderboard_honest.csv`.

**Result: the standard leaderboard correctly identifies the very top, but misranks the
body of the list by conflating settled money with open-position marks.**

---

## 4. Steps 2–3 — behaviour is a continuum, with one distinct extreme

Clustering used 6 reliable strategy-signature features (entry price, entry timing, hold
duration, maker/taker ratio, trade frequency, position size) — **never** PnL/ROI/win
rate. **What's actually robust here is narrower than "4 species":** one binary split
(liquidity/high-frequency market-making vs. directional betting) and one genuinely
distinct extreme (HFT market makers). The four labels below are real, economically
meaningful *regions* of a continuum — their profit shares and behaviour genuinely
differ — but a full statistical audit (§4b) found they are **not separable clusters**.
Read the table as "four interpretive regions," not four discovered species.

| Species | n | med realized PnL | med ROI | med count-win | med \$-win | med sizing-gap | med excess-ret | **% of cohort profit** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **HFT market maker** | 30 | \$0.93M | 7.6% | 0.52 | 0.57 | +0.06 | −0.03 | **39.6%** |
| **Favorite conviction bettor** | 23 | \$0.64M | 5.6% | **0.59** | **0.84** | **+0.24** | −0.09 | **25.6%** |
| **Mid-price active trader** | 28 | \$0.64M | 11.7% | 0.49 | 0.62 | +0.12 | −0.02 | **19.7%** |
| **Large directional taker** | 14 | \$0.92M | 12.0% | 0.52 | 0.55 | +0.05 | **+0.04** | **15.1%** |

**How each region makes money (one sentence each):**

- **HFT market maker** *(maker ratio 0.81, ~235 trades/day, instant flips, ~50% win,
  negative edge)* — earns the **spread on huge two-sided volume**, not by predicting
  outcomes; thin ROI × enormous turnover = the single largest profit share.
- **Favorite conviction bettor** *(entry price 0.76, holds ~1.2 days, wins 59% but stakes
  84% of dollars on winners)* — buys **likely favorites and sizes up hard when right**;
  negative excess-return means it *overpays* per bet but **conviction sizing** (sizing-gap
  +0.24) more than compensates. This is the mechanism behind the #1 wallet's 46%-win /
  +110%-ROI paradox.
- **Mid-price active trader** *(moderate frequency, sub-50% win, sizing-gap +0.12)* —
  a **generalist directional book** that loses more bets than it wins but wins the bigger
  ones; the middle of the continuum.
- **Large directional taker** *(taker-heavy 0.33 maker, largest positions ~\$18k, the only
  **positive** excess-return)* — **crosses the spread with size on genuine directional
  views** and is the one group that actually beats the price it pays.

**Cross-cutting finding — profit ≠ forecasting skill.** Three of four regions have
**negative median excess-return**: they are *right* often enough, or *big* enough, or
*high-volume* enough to profit **without paying below fair value**. Only the large
directional takers show a real per-bet edge. Skill on this platform is mostly **sizing
and liquidity provision, not calibration** (median Brier 0.10–0.22).

**External cross-check.** lum.id's own per-wallet style flags corroborate 2 of 3 axes:
`is_high_conviction` concentrates in the Favorite group (40% vs ~0% elsewhere);
`is_value_hunter` is low in Favorites (they overpay) and higher elsewhere (matching
excess-return). One disagreement: lum.id flags **0%** of our "HFT market maker" cluster
as `is_market_maker` — so that label is behavioural (maker-heavy, high-frequency), not
lum.id's stricter definition.

### 4b. Why "4 species" doesn't hold up statistically

A full multi-algorithm audit was run specifically to stress-test the clustering, and it
came back weak:

**Every algorithm at k=4 (silhouette):** KMeans 0.183 · GaussianMixture **0.105** · Ward
0.155 · Spectral 0.170 · Birch 0.207 · PCA(3)→KMeans 0.168 — all weak, and they
**disagree with each other**: ARI(kmeans, GMM) = **0.17**, vs Ward 0.41, vs Spectral
0.58 → the 4-way partition is partly a method artifact, not a robust structure.

**Density methods reject 4 clusters outright:** DBSCAN finds only **2** clusters
(dumping 26–71 wallets as noise); HDBSCAN (min_size≥6) finds **zero** clusters (all
noise) — these methods look for dense clumps and don't see four.

**Clusterability:** Hopkins statistic ≈ **0.69** (0.5 = random/no structure; >0.75 =
genuinely clustered) → weak-to-moderate structure, i.e. a **continuum**, not distinct
groups. The **best silhouettes are actually at k=2** (0.236, perfectly stable across
seeds) — the binary liquidity-vs-directional split in the TL;DR. PCA: the first 3
components explain **66%** of variance → behaviour genuinely lives on ~3 continuous
axes, not 4 discrete bins.

**Honest interpretation:** this isn't a bad-algorithm problem — the data genuinely
lacks crisp cluster structure. What survives: (a) the robust binary split; (b) one
genuinely distinct extreme (HFT market makers, silhouette +0.29 on its own, ~40% of
profit); (c) the four labels above as **interpretive regions** whose *economics* really
do differ (profit shares 15–40%), but which are **not** statistically separable
species. Use the table in §4 for the economics; use this section for how much
weight the "4 species" framing itself can bear.

---

## 5. Step 4 — the plot

`out/winrate_vs_roi.png`: count-win-rate (x) vs ROI (y), dot size = volume, color =
species, top-10 annotated where present. Profitable wallets span the **entire win-rate
axis (0.19–0.84)**; HFT makers pile up at ~0.5 win, favorite bettors stretch to 0.84,
and ROI shows no dependence on win rate. **Win rate is not a ranking criterion.**

---

## 6. The "win rate" definitional trap

Part of why win rate is such a bad ranking criterion: it isn't one number. The same
wallet (rank #1) has **four** legitimate, very different "win rates," because two
hidden choices are never stated — the **unit** (per trade vs. per bet/market) and the
**definition of a win** (was the prediction right vs. did it make money):

| definition | value | question it answers |
|---|--:|---|
| per-trade (lum.id) | **46%** | were the individual fills up? |
| per-bet, outcome-based (ours) | **64%** | did the predicted outcome happen? |
| per-bet, profit-based | **~86–89%** | did the market end profitable? (matches 3rd-party dashboards) |
| dollar-weighted outcome | **97%** | share of $ staked on winners |

You can *make money without being right* (sell before resolution) and *be right
without profiting much* (overpay for a favorite). A single "win rate" column ranking
is therefore meaningless. Note: for **HFT market makers, win rate is irrelevant
entirely** — they're directionally neutral, so ~50% is noise; their economics are
volume × spread.

---

## 7. What could NOT be computed (stated, not proxied)

- **maker/taker at the fill level is available**, but a clean **maker–taker *fee*** split
  is not — we report maker *ratio* from fill roles.
- **Domain-specialist** archetype: `category_HHI` coverage (28%) is too low to trust; we
  neither confirm nor deny it.
- **Longshot punter** archetype: absent as a distinct cluster in the ≥50-resolved cohort
  (min entry price 0.37); such players likely sit in the sub-floor concentrated group.
- **Split/merge/redeem** CTF operations are not modeled, so reconstructed *cost basis* is
  approximate for heavy full-set minters (some MMs); this is why we defer to lum.id for
  profit magnitude.

---

## 8. Open questions & next steps

1. **Enlarge the cohort.** Reconstruct the 81 truncated + 150 un-targeted wallets to
   roughly double n and firm up whatever structure exists (won't manufacture clusters
   that aren't there, but sharpens the picture).
2. **Feature work.** The 6 clustering features may be noisy (`entry_timing` is
   imputed for missing cases). Would a smaller, cleaner feature set — or rule-based
   segmentation on the genuinely bimodal features (maker ratio, frequency) — beat
   fragile clustering?
3. **Address survivorship properly.** Taken up in Experiment 2 (`../experiment2/`),
   which builds a PnL-neutral cohort including real losers — a different data pull
   than this experiment's winners-only leaderboard start.
4. **The ≥50-resolved floor excludes conviction whales** (rank #1 has only 22 bets).
   Is there a defensible way to characterise concentrated bettors with high-variance
   win rates?

---

## Files

| File | Contents |
|---|---|
| `out/leaderboard_honest.csv` | Step 1: realized vs total ranking, per wallet |
| `out/fingerprints.csv` | Step 2: one row per wallet, all metrics + coverage flags |
| `out/fingerprints_clustered.csv` | cohort with cluster label + name |
| `out/cluster_profile.csv` | Step 3: cluster summary table |
| `out/cluster_criteria.png` | signature heatmap + parallel-coordinates of the 6 clustering features |
| `out/winrate_vs_roi.png` | Step 4: the scatter |
| `whale_explorer.html` | interactive explorer (habitat map, specimen cards, per-wallet trade tape, win-rate-illusion widget) |
| `01_leaderboard.py … 06_plot.py` | reproducible pipeline (see `README.md`) |
