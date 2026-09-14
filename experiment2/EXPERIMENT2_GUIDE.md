# EXPERIMENT 2 — Complete Guide: "Is Any Wallet Worth Following?"

**One document, everything.** Purpose, every design decision and why it was made, what every
file does and where its output lives, the current findings, and pointers to every other doc.
Read this top to bottom once and you should never need to ask "where is X computed" again —
every section below tells you the exact file and the exact output path.

**Status as of 2026-08-14**: pipeline audited file-by-file, re-run end-to-end to confirm
reproducibility, two real methodology bugs found and fixed in Part 4 (details in §4 and §6).
All numbers in this document and `README.md` are current as of this date, including
`site/part4.html`, `part5.html`, `index.html`, and `pipeline.html` (fixed in the same pass).
**`site/part1_explainer.html`, `part2.html`, `part3.html` remain stale** — see §7, "Known
gaps," for why that's a separate, larger task.

**2026-09-14 reorg**: this repo holds two experiments (Experiment 1 — Whale Taxonomy, `01`-`06`;
Experiment 2 — this study, `10`-`34`). All **docs and HTML** were sorted into `experiment1/` and
`experiment2/` folders for clarity — this file and `site/` now live under `experiment2/`.
**Nothing else moved**: every `.py` script, `data/`, `out/`, and `probes/` are still flat at the
repository root, exactly as every path in this guide describes.

**2026-09-14 doc consolidation**: `FOLLOW_STUDY_FINDINGS.md` was retired — this was a near-total
subset of this file (same tables, same methodology notes, same caveats, just shorter). Its one
non-redundant piece, the "what this means for a following strategy" bullet list, now lives in
§6 below. `README.md` and `PART1_position_decomposition.md` remain separate: they serve
genuinely different jobs (fast session-resume, and a self-contained worked example +
output schema) rather than re-deriving the same numbers this file already has.

---

## Table of contents

1. [Purpose — what question this experiment answers, and why](#1-purpose)
2. [The pipeline, end to end](#2-the-pipeline-end-to-end)
3. [The data sources and their limits](#3-the-data-sources-and-their-limits)
4. [Every design decision and ruling, with rationale](#4-every-design-decision-and-ruling-with-rationale)
5. [File-by-file: what it does, why, inputs, outputs](#5-file-by-file-what-it-does-why-inputs-outputs)
6. [Findings, consolidated](#6-findings-consolidated)
7. [Known gaps and things that still need work](#7-known-gaps-and-things-that-still-need-work)
8. [Full index — every file this experiment touches](#8-full-index)
9. [How to reproduce anything in this document](#9-how-to-reproduce-anything-in-this-document)

---

## 1. Purpose

This is **Experiment 2** of the polymarket-whales project (distinct from Experiment 1, the
earlier "Whale Taxonomy" clustering study in `01`-`06`, documented separately in
`../experiment1/FINDINGS.md`/`README.md`/`WORKLOG.md` — not covered by this guide).

**The goal**: a feasibility gate for a Polymarket copy-trading rule. The full rule would need
two things: (a) is a wallet worth following *at all*, and (b) is a *given trade* worth copying.
**This experiment covers (a) only.** Part (b) is future work (see §7).

**The precise question**: is there a real, repeatable, forward-looking edge in any wallet,
beyond chance — and specifically, does that edge live in **holding** (correctly picking an
outcome and waiting for settlement — an outcome view a follower *can* copy) rather than
**trading** (buying low and selling high before resolution — an execution/timing edge a
follower *cannot* copy after the fact, because by the time you see the trade the price has
already moved)?

If no wallet's edge survives out-of-sample testing, there is no "when to follow" — the honest
answer would just be *never*. So everything in this pipeline builds toward one number: does
picking a wallet based on its past behavior actually predict anything about its future
behavior, and if so, how much, how reliably, and for how long.

**The one-line answer** (full detail in §6): **Yes — but the edge is small, lumpy, decays
gradually over at least half a year without fully disappearing, and cuts both ways (avoiding
bad wallets and picking good ones are comparably useful). Genuine steady compounders are ~1% of
the field.**

---

## 2. The pipeline, end to end

```
lib_subgraph.py ──► raw order fills (Goldsky subgraph, cached to data/fills/<wallet>.json)
lib_recon.py    ──► token → market → winner resolution (cached, memoized)
lib_decompose.py──► THE CORE IDEA: split one position's PnL into
                     pnl_trading (price movement — NOT copyable)
                     pnl_holding (right about the outcome — copyable)
        │
10_part1_positions.py  ──► out/positions.csv          (Part 1: the foundation table)
        │
11_part2_wallets.py    ──► out/wallet_metrics.csv      (Part 2 step 1: per-wallet profile,
        │                                                incl. trading_share, the key variable)
        │
12_part2_bimodality.py ──► printed report + 2 PNGs     (Part 2 step 2: one population or two?)
        │
20_enumerate_cohort.py ──► out/candidates.json         (Part 3 step 1: PnL-neutral wallet pool,
        │                                                live network)
21_reconstruct_cohort.py► out/cohort_qualifiers.json   (Part 3 step 2: fetch + qualify sampled
        │                                                wallets, live network — feeds data/fills/)
23_part3_report.py     ──► out/cohort_labeled.csv      (Part 3 report: survivorship fixed)
        │
30_market_dates.py     ──► data/clob_market_dates.json (Part 4 prerequisite: resolution-date proxy)
        │
31_part4a_persistence.py► out/part4a_persistence.csv,  (Part 4A: does the edge persist
        │                  out/part4a_wallet_status.csv  out-of-sample?)
32_part4b_consistency.py► out/part4b_consistency.csv   (Part 4B: is it repeatable skill or luck?)
33_part4d_decay.py     ──► out/part4d_decay.csv        (Part 4D: how fast does it fade?)
34_part4c_equity.py    ──► out/part4c_equity.csv,      (Part 4C: what does the profit curve
                           out/equity_examples.png       look like?)
```

Everything through `23` runs on cached data (no network needed once `data/fills/` is
populated) and is fully deterministic — verified by re-running `10`→`12`→`23` and `31`→`34`
fresh on 2026-08-14 and confirming every number reproduced exactly. `20`/`21` are the only
live-network steps and are one-time cohort-selection operations.

---

## 3. The data sources and their limits

| Source | What it gives | Limit |
|---|---|---|
| **Goldsky `orderbook` subgraph** (`lib_subgraph.py`) | Complete on-chain CLOB order-fill log, paginated via a timestamp cursor past the 1,000-row page limit | Stops indexing at the **2026-04-28** legacy v2 contract migration — wallets first active after that are invisible |
| **Goldsky `positions`/`pnl` subgraphs** (`lib_recon.py`) | token→condition map, condition→winner (`payoutNumerators`) | None significant |
| **CLOB `/markets/{cid}`** (`lib_recon.py`, `30_market_dates.py`) | Category, `accepting_order_timestamp`, `end_date_iso` | No true resolution timestamp exists anywhere — `end_date_iso` is used as a **proxy** (resolution follows within days); fine for monthly binning, not exact |
| **Polymarket data-api `/trades`** | — | **Not used.** Hard-capped at ~4,000 most-recent fills per wallet, ignores every time-window parameter. Discovered early and rejected — see `../experiment1/WORKLOG.md` §0.2 |
| **lum.id leaderboard** (`data/lumid_full.json`) | Top-500-by-PnL wallets, used only to *tag* which qualifiers are "winners" in Part 3 | Survivorship: top-500-by-PnL contains no losers, which is exactly why Part 3 builds an independent, activity-sampled cohort instead of relying on this list |

**CTF/market-maker blind spot** (structural, carried through the whole pipeline): position
splitting/merging/redeeming via the CTF contract is invisible to the fill log — a wallet that
mints a full YES+NO set and sells one side has no recoverable cost basis for what it kept. This
shows up as the `oversold` flag and is excluded from every "clean" metric. Measured impact (see
§6): **34.0% of cohort volume and 19.6% of resolved PnL** sit outside the clean, decomposable
set — concentrated in market-makers, whose edge this study cannot measure.

---

## 4. Every design decision and ruling, with rationale

These are the choices that shape every number downstream. Each is a deliberate, documented
call — not an accident — and each has a concrete reason.

**Cost-basis method: FIFO primary, VWAP as robustness check** (`lib_decompose.py`). FIFO
matches an early cheap buy to the early sell that consumed it — the natural reading of "bought
low, sold high." VWAP (average-cost) is computed in parallel on every position as a check; the
two never disagreed enough to change a conclusion (median |Δ pnl_trading| = $0.00 across 367k
clean positions).

**Sell-at-resolution tolerance** (`HOLD_PRICE_HI=0.97`, `HOLD_PRICE_LO=0.03` in
`lib_decompose.py`). A sell at $0.99 a minute before a market resolves YES is economically a
*hold* — the price already equals the ~$1 payout, so the profit is an outcome result, not a
trade. Such sells are routed into the holding bucket. The brief's third trigger — "within 60
minutes of resolution" — is **deliberately not computed**: no resolution timestamp exists in
the data, and the study's global rule is never to silently substitute a proxy where a real
number was asked for. The two price triggers economically subsume most such cases anyway.

**`direction_correct` is `NULL`, not "wrong," for a fully-exited position** (`lib_decompose.py`).
A wallet that sold everything before resolution took no view on the outcome; scoring that as a
loss is exactly the leaderboard-quality bug this study exists to avoid (a wallet with a fake
100% win rate from unresolved positions was found in Part 1 of the earlier Experiment-1 study —
`../experiment1/WORKLOG.md` §Phase-1).

**Hedged positions kept in aggregates, not excluded** (`11_part2_wallets.py`). The `hedged`
flag (did the wallet ever buy both outcome tokens in one market?) was measured to have a
**76-85% false-positive rate** — it usually fires when a wallet simply changed its mind
(sold one side, later bought the other) rather than genuinely holding both sides at once.
Excluding these positions was silently dropping ~174k genuinely single-directional positions
across the cohort, so the ruling is: keep them in the dollar aggregates and outcome metrics,
report `hedge_share` per wallet so the exposure stays visible, revisit only if the detection
logic itself is fixed.

**Oversold/CTF positions excluded from the "clean" set** (`10_part1_positions.py`, ruling 2). No
reliable cost basis exists for tokens acquired via split/merge outside the order book, so these
are dropped from every profit-attribution metric rather than estimated. Measured cost:
34.0% of volume, 19.6% of resolved PnL excluded — carried as a caveat into every later part.

**Truncated-history wallets excluded entirely, not reconstructed on partial data**
(`10_part1_positions.py`, the **2026-08-03 ruling**, log at `out/part1_run_truncdrop.log`). A
wallet whose fetch still hit the fill/order cap has an unknown amount of missing history;
computing metrics on an arbitrary partial slice would be worse than having no data at all. This
dropped 1,347 wallets and cut clean positions from ~1.02M to **367,178** and qualifying wallets
from 3,330 to **2,055** (loser share moved 54%→59%, i.e. the dropped wallets were
disproportionately winners with incomplete-but-flattering partial histories).

**Survivorship fix via activity-weighted sampling, not the leaderboard**
(`20_enumerate_cohort.py`, `21_reconstruct_cohort.py`). lum.id only returns winners (top-500 by
PnL) and cannot supply losers no matter how it's queried. Instead, wallets are enumerated by
sampling raw fills at 200 timestamps spread across the whole trading window — this conditions
on *trading*, not on *winning*, so real losers appear. Known, stated tradeoff: inclusion
probability is roughly proportional to a wallet's fill count, so the resulting pool is
activity-weighted (over-represents high-frequency wallets) — reported, not hidden.

**Two behavioral metrics, deliberately kept separate — the single most important
methodology point in this experiment.**
- `trading_share` (`11_part2_wallets.py`) = Σpnl_trading / Σ|pnl_total|, **profit-weighted**.
  This is Part 2's central variable: it answers *where a wallet's money came from*. It is
  explicitly documented (in its own docstring and printed CAUTION) as a profit-attribution
  metric, **not** a behavioral one — a wallet that trades constantly but nets ~$0 doing so
  looks identical here to a wallet that never trades at all.
- `trade_holding_rate` (introduced in `31_part4a_persistence.py`) = n_hold_positions /
  n_positions, **count-based**, bounded [0,1], immune to the profit-cancellation issue above.
  This is the correct tool for the *behavioral* question Part 4 actually needs to ask — "is
  this wallet, in practice, a directional holder we could follow?"
  
  Part 4 originally (incorrectly) used `trading_share < 0.2` for this behavioral eligibility
  question. Verified impact of that mistake: it misclassified **91-98%** of behaviorally-active
  traders as "holders." This was found and fixed on 2026-08-14 — see §5 and §6 for the specific
  before/after numbers. The fix was **not** a change to `trading_share` itself (it remains
  correct and unchanged for Part 2's question) — it was recognizing the metric was being
  reused for a job it was never designed for, exactly as Part 2's own docstring had already
  warned.

**Persistence test: a literal per-wallet rate, not a population-wide rank correlation**
(`31_part4a_persistence.py`, and — after the 2026-08-14 fix — `33_part4d_decay.py`). "Does a
wallet's edge persist" is a claim about an *individual* wallet, conditional on it having an
edge — not a claim about whether relative rank is preserved across the *whole* population.
Spearman rank correlation answers the second, broader question. The test used throughout Part 4
is instead: `good_past` = wallet's historical metric > 0; `good_fwd` = wallet's forward metric
> 0 in a disjoint evaluation window; report `P(good_fwd|good_past)` vs. `P(good_fwd|bad_past)`
vs. the unconditional baseline, with a chi-square p-value on the gap. `33_part4d_decay.py`
originally used Spearman at multiple horizons and was fixed to match on 2026-08-14.

**Cumulative-historical / disjoint-forward window design** (`31_part4a_persistence.py` and
descendants). At each monthly checkpoint `t`, a wallet is measured on *everything* resolved
through `t` (cumulative — historical windows overlap each other, so consecutive measurements
look "sticky" by construction) but evaluated only on the *disjoint* window `(t, t+3mo]`
(genuinely out-of-sample — nothing in that window could have influenced the historical side).
Historical-to-historical churn is never reported as persistence, only historical-to-forward.

**Sample-size floors, throughout**: `MIN_RESOLVED_POSITIONS=30` (Part 2 — below this, wallet
percentages are noise), `MIN_GROUP_SIZE=15` per good_past/bad_past subgroup (Part 4A/4D — a
persistence rate computed on a handful of wallets isn't trustworthy), `MIN_AVG_POSITION_SIZE=$10`
(excludes micro-betting bots: verified ~4-8% of an otherwise-qualified pool are sub-$5-bet bots
contributing up to 12% of position volume for ~0% of real PnL).

**4B's population is 4A's tested population, not an independent re-filter**
(`32_part4b_consistency.py`, fixed 2026-08-14). Originally 4B re-derived its own holder pool
from scratch using the old `trading_share` filter — a *different* population than the one 4A
actually ran the persistence test on. Now 4B reads `out/part4a_wallet_status.csv` directly:
the exact set of wallets 4A labeled `good_past` at its primary threshold/pair, so 4B's
concentration analysis and the "does consistency predict persistence" test are about the same
wallets 4A's headline numbers are about.

**4C computes its own concentration metric rather than borrowing 4B's** (`34_part4c_equity.py`,
fixed 2026-08-14). A knock-on effect of the previous fix: 4B's population shrinking to 4A's 252
tested wallets meant borrowing its `top1_share` column left ~84% of 4C's own ~1,591-wallet
population with no concentration value and unable to be classified `one_jump`. 4C now computes
`top1_share` from its own data.

---

## 5. File-by-file: what it does, why, inputs, outputs

### `lib_subgraph.py`
**What**: Goldsky GraphQL client. `fetch_fills(wallet, cap)` walks `orderFilledEvents` ascending
by timestamp cursor, caches to `data/fills/<wallet>.json`, raises `FetchError` on a real network
failure (never silently caches an empty/partial result as success). `normalize(fill, wallet)`
turns one raw fill into `{token, side, size, price, ts, is_maker}`.
**Why it exists**: the data-api alternative is capped at ~4,000 fills and ignores time filters
— unusable for any wallet with real trading history (§3).
**Consumes**: Goldsky subgraph (network) or `data/fills/*.json` (cache).
**Produces**: `data/fills/<wallet>.json` per wallet.

### `lib_recon.py`
**What**: `resolve_tokens(tokens)` — token→conditionId→{resolved, winners}, batched, cached
in-memory and on-disk with atomic temp+rename writes (a mid-write kill once corrupted this
cache; fixed). `gamma_meta`/`prefetch_market_meta` — category/open/close via CLOB.
**Why**: the only place market resolution enters the pipeline; kept as a single, cached,
correctness-critical lookup so every downstream script agrees on "did this market resolve, who
won."
**Consumes**: Goldsky `positions`/`pnl` subgraphs, CLOB `/markets/{cid}`.
**Produces**: `data/tok2cond.json`, `data/cond_payout.json`, `data/gamma_meta.json`.

### `lib_decompose.py`
**What**: `decompose(buys, sells, resolved, won, mode)` — the core economic engine. FIFO- or
VWAP-matches sells against buys, splits realized PnL into `pnl_trading` (price movement) and
`pnl_holding` (settlement outcome), with the resolution-equivalent-sell tolerance from §4
applied. Every clean position's two buckets are asserted to re-sum to raw cash flow.
**Why**: this *is* the study's thesis, made computable — see §4 for the specific conventions
and §1 for why the trading/holding split matters at all.
**Consumes**: normalized fills for one token + that token's resolution.
**Produces**: a dict of decomposition fields (consumed by `10_part1_positions.py`, never
written to disk on its own). Full worked example: `PART1_position_decomposition.md` §3.

### `10_part1_positions.py` — Part 1
**What**: loops every wallet with cached fills, every (market, token) it took a net-long
position in, calls `decompose()` in both FIFO and VWAP mode, tallies edge cases (hedged,
oversold, resolution-equivalent sells, pure-sells), runs the reconciliation gate.
**Why**: the foundation table everything else joins onto. If the gate fails, nothing downstream
can be trusted — see §4's ruling on truncated wallets for why bad inputs are excluded rather
than included-with-caveats here specifically.
**Consumes**: `data/fills/*.json`, `data/tok2cond.json`, `data/cond_payout.json`.
**Produces**: `out/positions.csv` (**33 columns, 963,376 rows** as of 2026-08-14 — see
`PART1_position_decomposition.md` §7 for the full schema), `out/wallet_meta.csv`,
`out/part1_stats.json`.
**Current run** (re-verified 2026-08-14, reproduces exactly): 527,109 resolved positions,
367,178 clean (not oversold, not hedged), reconciliation gate **PASS** (max error 6.40e-07
USD), FIFO-vs-VWAP median delta $0.00.

### `11_part2_wallets.py` — Part 2, step 1
**What**: collapses `positions.csv` to one row per wallet (≥30 resolved positions), computes
`trading_share` (the key variable — §4) plus supporting metrics: `holding_fraction_dollar`
(strict/adjusted), `hold_win_rate`, `hold_dollar_win_rate`, `sizing_gap`,
`holding_excess_return`, `trading_return`, `maker_ratio`, `trade_frequency`.
**Why**: turns individual bets into one profile per wallet, and computes the metric everything
downstream ranks on.
**Consumes**: `out/positions.csv`, `out/wallet_meta.csv`.
**Produces**: `out/wallet_metrics.csv` (**2,055 wallets** as of 2026-08-14) + an extensively
self-documenting printed report (every metric gets a WHAT/HOW/WHY block).
**Current run**: median `trading_share` ≈ 0.00 (holder-dominated); 1,895 wallets
holding-profit-dominated (<0.2), 159 middle, 1 trading-profit-dominated (>0.8); **98.2%** of
all positive-PnL wallets' profit sits in the holding-profit-dominated bucket.

### `12_part2_bimodality.py` — Part 2, step 2
**What**: Hartigan's dip test + 1-vs-2-component Gaussian mixture (BIC-compared, with a
separation check so BIC preferring k=2 to absorb skew isn't mistaken for real bimodality) on
`trading_share` and both `holding_fraction_dollar` variants. Plus the ruling-2 CTF-exclusion
size report.
**Why**: answers whether "holder vs. trader" is two real populations or one continuum — this
determines whether any hard threshold (like `trading_share<0.2`) is drawing a real boundary or
an arbitrary cut on a spectrum.
**Consumes**: `out/wallet_metrics.csv`, `out/positions.csv`, `out/part1_stats.json`.
**Produces**: `out/trading_share_dist.png`, `out/holding_fraction_dist.png` + printed report.
**Current run**: all three variables verdict **CONTINUOUS / unimodal** (dip p=0.997 for
`trading_share`); 34.0% of cohort volume and 19.6% of resolved PnL excluded by the CTF ruling.
*(Note: this script's console output includes ~90 benign `RuntimeWarning`s from sklearn's
k-means initialization — a spurious BLAS floating-point flag, not a real numeric problem; see
§7.)*

### `20_enumerate_cohort.py` — Part 3, step 1
**What**: samples 200 timestamps across the whole fill window, pulls 1,000 fills at each,
collects distinct maker+taker addresses with an appearance count.
**Why**: the PnL-neutral (loser-inclusive) candidate pool — see §4's survivorship-fix rationale.
**Consumes**: Goldsky `orderbook` subgraph (live network).
**Produces**: `out/candidates.json`.

### `21_reconstruct_cohort.py` — Part 3, step 2
**What**: fetches (parallel, network-bound) and qualifies (≥30 resolved positions) a
stratified sample of the candidates, tiered by appearance count.
**Why**: turns the raw candidate pool into an actually-reconstructed, qualifying cohort.
**Consumes**: `out/candidates.json`, Goldsky subgraph (live).
**Produces**: `out/cohort_qualifiers.json` in `full` mode (**currently missing from disk** —
see §7; not a broken dependency, nothing downstream reads it, just lost audit trail). Its real
lasting effect is the wallets it adds to `data/fills/`.

### `23_part3_report.py` — Part 3 report
**What**: compares the enlarged, PnL-neutral cohort against the original top-500 winners,
tags each wallet `winner`/`sampled`, states which claims become possible now that losers exist
in-sample.
**Consumes**: `out/wallet_metrics.csv`, `data/lumid_full.json`.
**Produces**: `out/cohort_labeled.csv`.
**Current run**: 2,055 qualifiers (121 winners, 1,934 sampled), **59% unprofitable** overall
(vs. ~all-profitable in the old winners-only view) — this is what makes Part 4's baselines and
"beats the field" claims meaningful; without real losers in-sample there'd be nothing to beat.

### `30_market_dates.py` — Part 4 prerequisite
**What**: pages the CLOB bulk `/markets` endpoint once, caches `condition_id →
{end_date_iso, winner_token}`.
**Why**: no resolution timestamp exists anywhere in the subgraph data; `end_date_iso` is the
best available proxy (§3).
**Produces**: `data/clob_market_dates.json` (**~98% coverage** of the cohort's conditions).

### `31_part4a_persistence.py` — Part 4A: does the edge persist?
**What**: the core persistence-rate test (§4) across 6 metric pairs and 3 eligibility
thresholds (`trade_holding_rate ≥ 0.5/0.7/0.9`), plus a wallet-level snapshot at the latest
fully-resolved checkpoint identifying exactly which wallets are `good_past`/`good_fwd`/
`persisted`.
**Consumes**: `out/positions.csv`, `data/clob_market_dates.json`.
**Produces**: `out/part4a_persistence.csv` (aggregated rates per window/threshold/pair),
`out/part4a_wallet_status.csv` (per-wallet snapshot — 477 eligible holders, 252 `good_past`,
116 `persisted`, at the primary threshold 0.5 / pair `realized_pnl→fwd_roi`).
**Current findings**: full table in §6.

### `32_part4b_consistency.py` — Part 4B: skill or luck?
**What**: for the 252 `good_past` wallets from 4A's snapshot, computes profit concentration
(top1/top5 share, Herfindahl), median-position profitability, and profitable-quarter fraction —
all on the *historical* slice only (no leakage from the forward window). Then the KEY TEST:
do low-concentration ("consistent") wallets forward-persist more often than concentrated ones?
**Consumes**: `out/positions.csv`, `out/part4a_wallet_status.csv`, `data/clob_market_dates.json`.
**Produces**: `out/part4b_consistency.csv`.
**Current findings**: §6.

### `33_part4d_decay.py` — Part 4D: how fast does it fade?
**What**: the same persistence-rate test as 4A, run at three forward horizons (1/3/6 months)
instead of one, to see how the good_past/bad_past gap shrinks with distance.
**Consumes**: `out/positions.csv`, `data/clob_market_dates.json`.
**Produces**: `out/part4d_decay.csv`.
**Current findings**: §6.

### `34_part4c_equity.py` — Part 4C: what does the profit curve look like?
**What**: builds each wallet's cumulative-PnL-vs-resolution-date curve, fits its steadiness
(R²), max drawdown, and recent-vs-historical slope (a second decay signal, independent of 4D's),
classifies into `steady_climber`/`one_jump`/`decayed`/`volatile_rising`/`flat_or_down`.
**Consumes**: `out/positions.csv`, `out/wallet_metrics.csv`, `data/clob_market_dates.json`.
**Produces**: `out/part4c_equity.csv`, `out/equity_examples.png` (4 example curves).
**Current findings**: §6. *(Note: ~113 of 1,591 wallets trigger a benign BLAS matmul
`RuntimeWarning` in the curve-fitting step — confirmed harmless, no NaN/Inf in the actual
output; see §7.)*

---

## 6. Findings, consolidated

### Part 1 — the split is arithmetically sound
367,178 clean resolved positions reconcile to raw cash flow to within 6.4e-07 USD. This is the
precondition for trusting everything below.

### Part 2 — profit is overwhelmingly holding-based, and it's a spectrum, not two types
**98.2%** of all profit among positive-PnL wallets sits in the holding-profit-dominated bucket
(`trading_share<0.2`) — encouraging, since holding-based profit is the copyable kind.
Bimodality testing finds **no real two-population split** — `trading_share` and
`holding_fraction_dollar` are both unimodal (dip p≈1.0); "holder vs. trader" is one continuum.

### Part 3 — survivorship fixed, real losers now in-sample
2,055 qualifying wallets, **59% unprofitable** — the honest picture, vs. the top-500 leaderboard
where nearly everyone is a winner by construction. This is what makes Part 4's "beats baseline"
claims meaningful.

### Part 4A — persistence, by metric pair (primary threshold `trade_holding_rate≥0.5`)

| historical metric → forward target | P(good⏐good_past) | P(good⏐bad_past) | baseline | gap significant |
|---|---|---|---|---|
| `holding_excess_return → fwd_roi` | **59%** | 42% | 49% | 100% of 9 windows |
| `holding_excess_return → fwd_holding_excess_return` | 57% | 34% | 43% | 100% |
| `realized_pnl → fwd_roi` | 54% | 44% | 49% | 44% |
| `roi → fwd_roi` | 54% | 44% | 49% | 44% |
| `sizing_gap → fwd_sizing_gap` | 67% | 53% | 64% | 67% |
| `sizing_gap → fwd_roi` | 50% | 43% | 49% | 11% |

Forecasting skill (`holding_excess_return`) persists best and most reliably. Conviction-sizing
behavior is a stable trait but doesn't reliably translate into better forward *returns*.
(Results at thresholds 0.7 and 0.9 are directionally the same — see `out/part4a_persistence.csv`.)

### Part 4B — mostly lucky hits, but real skill underneath
Among the 252 `good_past` holders: median 54% of profit from a single position (54% get >50%
from one bet) — but 78% still have a profitable *median* position and the median wallet is
profitable in 67% of active quarters. Splitting into "consistent" (n=108) vs. "concentrated"
(n=144): consistent wallets persist forward at **49%** vs. **44%** — a real, modest extra edge.

### Part 4D — decays gradually, no clean half-life inside 6 months
Good-past/bad-past gap: **+20pp at 1 month → +16pp (84%) at 3 months → +13pp (66%) at 6
months.** The "good wallet" signal stays meaningfully informative for at least half a year,
just with steadily diminishing force — quarterly re-ranking is sound, but there's no sharp
cliff to time it against.

### Part 4C — steady climbers are ~1%, and that's most of what's followable
Of 1,591 eligible directional holders: `steady_climber` 19 (1%, holding 1% of cohort profit),
`volatile_rising` 229 (14%, 48% of profit), `one_jump` 388 (24%, 45% of profit), `decayed` 65
(4%, 6% of profit), `flat_or_down` 890 (56%, 0% of profit — unprofitable). **93% of cohort
profit comes from lumpy volatile-rising or one-hit wallets**, not steady grinders.

### The verdict
A real, statistically significant, but modest and lumpy edge exists in wallet holding behavior.
It's strongest for pure forecasting skill, weak for conviction-sizing-as-a-return-predictor,
decays gradually rather than sharply, and works roughly symmetrically for avoiding bad wallets
and picking good ones. The closest thing to a reliable follow target is the ~1% of wallets that
are genuine steady climbers with low profit concentration and a profitable median bet.

### What this means for an actual following strategy
Viable, but modest and defensive — not a money printer:

- **Rank holders by forecasting skill** (`holding_excess_return`), restricted to directional
  holders (`trade_holding_rate ≥ 0.5`), not by raw PnL (which rewards bankroll, not skill).
- **The signal cuts both ways, roughly symmetrically** — a wallet with a positive historical
  edge is ~10 points more likely than baseline to keep it forward; one with a negative edge is
  ~5-7 points less likely. Avoiding bad wallets and picking good ones are comparably useful.
- **Re-rank every ~1-3 months** — the edge doesn't fully decay within 6 months, but it visibly
  erodes, so a near-term ranking stays more accurate.
- **Expect lumpy returns** — 93% of cohort profit among directional holders comes from lumpy or
  one-hit wallets, not steady grinders. Position-sizing and patience matter more than in a
  steady strategy.
- **Best targets are the ~1% "steady climbers"** with low profit concentration and a positive
  median bet. Among already-good-history wallets, additionally filtering for low concentration
  + profitable median lifts forward persistence from 44% to 49% (§4B).

Part (b) — *which trade* to copy, given a followable wallet — is worth doing, because part (a)
cleared the gate here: an out-of-sample edge exists. But size expectations to "small and
defensive," not "follow the leaderboard and get rich."

---

## 7. Known gaps and things that still need work

- **`site/part1_explainer.html`, `part2.html`, `part3.html` are stale** — they still embed
  pre-truncdrop-ruling cohort numbers (3,330 wallets, 2.38M positions, 888k clean resolved,
  54% losers) in hand-built JSON blobs containing histograms (bin-by-bin counts), Hartigan
  dip-test statistics, GMM parameters, and a worked example wallet. No generator script exists
  for these — fixing them needs new instrumentation added to `10`/`11`/`12`/`23` to re-extract
  chart-ready, bin-level data (not just re-running the existing scripts), a materially larger
  task than the text/data fixes below. **`site/part4.html`, `part5.html`, `index.html`, and
  `pipeline.html` were fixed as part of this 2026-08-14 review** — all current.
- **`out/cohort_qualifiers.json` is missing from disk.** `21_reconstruct_cohort.py`'s `full`
  mode is documented to write it, but it isn't there. Nothing downstream reads it (`10`/`11`/
  `23` all work from `data/fills/` and `positions.csv`/`wallet_metrics.csv` directly), so this
  doesn't break anything — it just means the exact tiered-sampling provenance of which wallets
  were selected is no longer inspectable.
- **Benign floating-point warning noise** in `12_part2_bimodality.py` (~90 lines, sklearn
  k-means init) and `34_part4c_equity.py` (113 of 1,591 wallets, numpy `lstsq`/matmul). Both
  confirmed to produce fully correct output (no NaN/Inf) — traced to spurious BLAS exception
  flags on macOS Accelerate, most likely triggered by design matrices with many duplicate
  timestamps. Cosmetic only; would be worth wrapping in `np.errstate` if the noise ever
  obscures a real problem.
- **`PART1_position_decomposition.md`'s §7/§8 were stale** (wrong column count, a
  never-shipped `truncated_wallet` column, pre-truncdrop-ruling scale numbers) — **fixed** as
  part of this same 2026-08-14 pass.
- **Part (b) — which trade to copy** is entirely unstarted. Watch for entry slippage (a
  follower gets a worse fill than the wallet did, so realized edge < `holding_excess_return`).
- **CTF modeling** (optional): adding `PositionSplit/Merge/Redeem` events per wallet would
  recover the market-maker population currently excluded — deliberately skipped since
  market-makers aren't a followable population anyway, but doable if ever needed.

---

## 8. Full index

### Documentation
Both files below live alongside this one, in `experiment2/`.

| File | What it is |
|---|---|
| `EXPERIMENT2_GUIDE.md` | this file |
| `README.md` | terse resume-context file; points here |
| `PART1_position_decomposition.md` | deep-dive worked example on Part 1's FIFO decomposition |

In `../experiment1/`: `WORKLOG.md`, `README.md`, `FINDINGS.md` —
**Experiment 1** (Whale Taxonomy, `01`-`06`) — not this experiment.

### Code — libraries
`lib_subgraph.py` · `lib_recon.py` · `lib_decompose.py`

### Code — pipeline, in run order
`10_part1_positions.py` → `11_part2_wallets.py` → `12_part2_bimodality.py` →
`20_enumerate_cohort.py` → `21_reconstruct_cohort.py` → `23_part3_report.py` →
`30_market_dates.py` → `31_part4a_persistence.py` → `32_part4b_consistency.py` →
`33_part4d_decay.py` → `34_part4c_equity.py`

### Key outputs (`out/`)
| File | Produced by | Contents |
|---|---|---|
| `positions.csv` | `10` | one row per wallet×token position (the foundation, 33 cols, 963k rows) |
| `wallet_meta.csv` | `10` | per-wallet fill-activity summary |
| `part1_stats.json` | `10` | edge-case counts for the exclusion reports |
| `wallet_metrics.csv` | `11` | one row per wallet, ~22 metrics incl. `trading_share` |
| `trading_share_dist.png`, `holding_fraction_dist.png` | `12` | bimodality histograms |
| `candidates.json` | `20` | PnL-neutral wallet candidate pool |
| `cohort_labeled.csv` | `23` | full cohort, winner/sampled tagged, survivorship-fixed |
| `part4a_persistence.csv` | `31` | aggregated persistence rates per window/threshold/pair |
| `part4a_wallet_status.csv` | `31` | per-wallet good_past/good_fwd/persisted snapshot |
| `part4b_consistency.csv` | `32` | per-wallet concentration + consistency metrics |
| `part4d_decay.csv` | `33` | persistence rates at 1/3/6-month horizons |
| `part4c_equity.csv`, `equity_examples.png` | `34` | equity-curve shape classification |

### Data caches (`data/`)
`fills/<wallet>.json` (6,347 wallets) · `tok2cond.json` · `cond_payout.json` ·
`clob_market_dates.json` · `gamma_meta.json` · `lumid_full.json`

### Website (`site/`) — presentation layer, partially stale (see §7)
`index.html` ✓ · `pipeline.html` ✓ · `part1_explainer.html` ⚠️ · `part2.html` ⚠️ ·
`part3.html` ⚠️ · `part4.html` ✓ · `part5.html` ✓  (✓ = current as of 2026-08-14,
⚠️ = still shows pre-truncdrop-ruling numbers)

---

## 9. How to reproduce anything in this document

Everything through Part 3 runs on cached data with **no network required**:
```bash
python3 10_part1_positions.py    # ~80s, pure computation
python3 11_part2_wallets.py      # seconds
python3 12_part2_bimodality.py   # seconds (ignore the sklearn warning noise, §7)
python3 23_part3_report.py       # seconds
```
Part 4 also runs entirely on cached data, in this order (32 depends on 31's output):
```bash
python3 30_market_dates.py       # only if data/clob_market_dates.json is missing
python3 31_part4a_persistence.py
python3 32_part4b_consistency.py
python3 33_part4d_decay.py
python3 34_part4c_equity.py
```
`20_enumerate_cohort.py` and `21_reconstruct_cohort.py` hit the live Goldsky subgraph and are
one-time cohort-building steps — only re-run these if you actually want to change or extend the
sampled wallet pool, not to verify existing numbers.

Every number in §6 above was produced by exactly these commands on 2026-08-14 and reproduced
identically on a second run in the same session — the whole pipeline is deterministic given the
cached `data/fills/`.
