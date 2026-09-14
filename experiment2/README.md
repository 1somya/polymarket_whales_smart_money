# "Is Any Wallet Worth Following?" (Polymarket) study — README

**Status: COMPLETE.** All 5 parts done, validated, and documented (written report + interactive
website). This file is the single source of truth for resuming in a new terminal.

**2026-08-14 review pass:** the whole pipeline was audited file-by-file, re-run end-to-end to
confirm reproducibility, and two real methodology bugs in Part 4 were found and fixed (see the
Gotchas section below). This file and `EXPERIMENT2_GUIDE.md` are current as of that date, as is
`site/index.html`/`pipeline.html`/`part4.html`/`part5.html`.
**`site/part1_explainer.html`, `part2.html`, `part3.html` still show pre-truncdrop-ruling cohort
numbers** (3,330 wallets / 54% losers / 2.38M positions instead of the current 2,055 / 59% /
963k) — their embedded data is deep per-page histograms/dip-test stats that need a dedicated
re-extraction pass, not a quick edit. See `EXPERIMENT2_GUIDE.md` §7.

**2026-09-14 reorg:** this repo holds two experiments (Experiment 1 — Whale Taxonomy, `01`-`06`;
Experiment 2 — this study, `10`-`34`). To make that clearer, all **docs and HTML** were sorted
into `experiment1/` and `experiment2/` folders — this file and `site/` now live under
`experiment2/`. **Nothing else moved**: every `.py` script, `data/`, `out/`, and `probes/` are
still flat at the repository root, exactly as every path below describes. Run code and look up
outputs exactly as before; only where the docs/website themselves sit on disk changed.

**2026-09-14 doc consolidation:** `FOLLOW_STUDY_FINDINGS.md` was retired — it was a near-total
subset of `EXPERIMENT2_GUIDE.md`; that file is now the one place for findings, methodology,
and strategy implications.

---

## ▶ How to resume in a new terminal

Persistent memory (`~/.claude/projects/-Users-somya/memory/`) **auto-loads every session**, and its
index already points here. So in a fresh terminal you can just say:

> "Read `/Users/somya/polymarket-whales/experiment2/README.md` and the memory notes
> `polymarket-follow-study-*`. The study is complete — I want to **<your next task>**."

That's all the context transfer you need. Nothing is stored only in the dead terminal.

---

## What this project is

The **feasibility gate** for a Polymarket copy-trading rule. Full rule = (a) is a wallet worth
following at all + (b) is a given trade worth copying. **This study covered (a) only.**
Question: is any wallet's edge (1) in *holding* (a copyable outcome view) not *trading* the price,
and (2) does it *persist out-of-sample*?

**Verdict:** Yes — but the edge is **small, lumpy, decays gradually over at least half a year
without fully disappearing, and cuts both ways (avoiding bad wallets and picking good ones are
comparably useful).** Genuine steady compounders are ~1% of holders. Part (a) cleared the gate,
so part (b) is worth doing.

---

## Where everything lives — `/Users/somya/polymarket-whales/`

**Code** (heavily commented; run order 10→12, 20→23, 30→34; all cached & resumable)
- `lib_subgraph.py` — Goldsky subgraph client · `fetch_fills` (both maker/taker) · `normalize`
- `lib_recon.py` — token→market, market→resolution (memoized, **atomic** saves)
- `lib_decompose.py` — FIFO/VWAP trading-vs-holding decomposition (the core)
- `10_part1_positions.py` — Part 1 driver
- `11_part2_wallets.py`, `12_part2_bimodality.py` — Part 2
- `20_enumerate_cohort.py`, `21_reconstruct_cohort.py`, `23_part3_report.py` — Part 3
- `30_market_dates.py`, `31_part4a_persistence.py`, `32_part4b_consistency.py`,
  `33_part4d_decay.py`, `34_part4c_equity.py` — Part 4
- `probes/` — findata API investigation (`FINDATA_API_REFERENCE.md`, `probe*.py`)

**Outputs** — `out/`
- `positions.csv` (**276 MB, 963k rows** — one per wallet×token; the foundation. Don't open whole)
- `wallet_metrics.csv` (2,055 wallets × ~22 metrics), `cohort_labeled.csv` (winner/sampled + profitable)
- `part4a_persistence.csv`, `part4a_wallet_status.csv` (per-wallet good_past/good_fwd snapshot,
  added 2026-08-14 — this is what `part4b_consistency.csv` is built from), `part4b_consistency.csv`,
  `part4c_equity.csv`, `part4d_decay.csv`
- `part1_stats.json`, `candidates.json`, `part{1,2,3,4}_web_data.json` (**unused legacy
  snapshots** — no site page actually fetches these; each `site/*.html` page embeds its own
  data inline instead)

**Data caches** — `data/` (~a few GB; regenerable but slow)
- `fills/` (6,347 wallets), `tok2cond.json`, `cond_payout.json`, `clob_market_dates.json` (881k
  markets), `lumid_full.json` (the 500 winners), `gamma_meta.json`

**Docs**
- `EXPERIMENT2_GUIDE.md` — **start here.** One file, everything: purpose, every script's
  what/why/inputs/outputs, every ruling and why it was made, current findings, strategy
  implications, and links to every other doc and output file in this study.
- `PART1_position_decomposition.md` — deep-dive on Part 1
- `probes/FINDATA_API_REFERENCE.md` — the lum.id findata API map (why it was rejected)

**Website** — `site/` (open `site/index.html` in a browser)
- `index.html` (overview + verdict + "discoveries worth keeping" + full file inventory)
- `part1_explainer.html` (interactive FIFO decomposer) · `part2.html`–`part5.html`
- `study_styles.css` (shared). Every page: what/why/how + real data + Assumptions-&-errors + Files.
- Part 1 also published as an Artifact: `claude.ai/code/artifact/13cbd4a8-762f-45cb-97a2-1c2e5843fe51`

**Memory notes** (auto-load): `polymarket-follow-study-progress`, `polymarket-follow-study-datasource`,
`polymarket-whale-taxonomy`, `polymarket-data-access`.

---

## The 5 parts (one line each)

1. **Decomposition** — split every position's profit into trading vs holding via FIFO; reconciled
   to 7 decimals over 367k clean positions (post truncdrop ruling, see caveat below).
2. **Aggregation** — roll up to wallets; `trading_share` key variable; dip test → one continuous,
   holder-dominated population (not bimodal); ~98% of clean profit is holding-based.
3. **Survivorship** — PnL-neutral cohort of 6,347 wallets (2,055 qualify, **59% losers**) via
   activity sampling; findings survive.
4. **Persistence** — cumulative-historical / disjoint-forward persistence-RATE test (not rank
   correlation — see below): `P(good_fwd|good_past)` 54-67% vs. baseline 43-64% across 6 metric
   pairs, `holding_excess_return` strongest (gap significant in 100% of 9 windows), `sizing_gap`
   weak on returns but stable as a behavioral trait; profits are lumpy (54% of profitable
   holders get >50% of profit from one bet); ~1% steady climbers; edge decays gradually but has
   **no clean half-life inside 6 months** (66% of the 1-month persistence gap still present at 6
   months). **Re-run and re-verified against the current 367k/2,055 cohort on 2026-08-14**
   (see caveat below — this was stale until that date).
5. **Verdict** — the five questions answered; strategy = rank by forecasting skill, the signal
   cuts both ways (avoiding bad ≈ picking good), re-rank every 1-3 months, expect lumpy returns.

---

## Gotchas to remember (don't rediscover the hard way)

- **Data cutoff: 2026-04-28** (legacy subgraph v2 migration). Nothing after.
- **CTF split/merge is invisible to the fill log** → wallets that mint-then-sell look "oversold"
  (no cost basis) and are excluded. This is the **34.0%-volume / 19.6%-PnL blind spot**, concentrated
  in market-makers. All "trading vs holding" figures are on the clean, fill-reconstructable set.
- **No resolution timestamp anywhere** → Part 4 uses CLOB `end_date` as a proxy (the main Part-4
  caveat). 98.8% coverage.
- **lum.id findata = taker-only tape → excluded.** See `probes/FINDATA_API_REFERENCE.md`.
- **`trading_share` measures profit *source*, not trading *activity*.** ~0 = "no trading edge" —
  a literal holder OR a break-even active trader (61% of "holders" held <80% of capital).
- **Hedge flag catches sequential flips too** (bought YES, sold, bought NO) — ~41% of hedged pairs
  by count but ~18% by dollars; left as-is.
- **Bugs already fixed & hardened**: Py-3.9 `socket.timeout` escaping retries; a 92 MB/wallet disk
  write; a cache corruption from a mid-write kill (atomic temp+rename saves — as of 2026-08-05
  this now covers `lib_subgraph.fetch_fills()` too, the original per-wallet fills-cache writer,
  which had been missed when the fix was first applied elsewhere).
- **Truncated-history wallets now excluded (2026-08-03 ruling, `out/part1_run_truncdrop.log`).**
  Wallets whose fetch still hit the order cap are dropped rather than reconstructed on partial
  data (1,347 wallets). This cut clean positions ~1.02M→367k and qualifiers 3,330→2,055 wallets
  (54%→59% losers). **Part 3's report/labels were stale until 2026-08-05** (re-run, now current).
  **Part 4 was stale (computed pre-ruling) until 2026-08-14**, when it was re-run against the
  current cohort AND two methodology bugs were fixed in the same pass: (a) the holder-eligibility
  filter used `trading_share` (Part 2's profit-attribution metric, wrong tool for a behavioral
  filter — misclassified 91-98% of active traders as holders) instead of the count-based
  `trade_holding_rate`; (b) the persistence test used Spearman rank correlation (a different,
  broader claim than "does this wallet's own edge persist") instead of a literal
  `P(good_fwd|good_past)` rate. All Part 4 numbers in `EXPERIMENT2_GUIDE.md` and this file
  are current as of 2026-08-14. Full detail: `EXPERIMENT2_GUIDE.md`.
- **`holding_excess_return`** = return over the wallet's *entry price* → blends forecasting skill
  with entry timing; benchmark is what the wallet paid, not a fixed market probability.

---

## Likely next tasks

- **Regenerate `site/part1_explainer.html`, `part2.html`, `part3.html`.** These still embed
  pre-truncdrop-ruling cohort data (3,330 wallets, 2.38M positions, 888k clean resolved, etc.)
  in hand-built JSON blobs — histograms (bin-by-bin counts), Hartigan dip-test statistics, GMM
  parameters, and worked example wallets. Unlike `part4.html` (fixed 2026-08-14), these need new
  *instrumentation* added to `10`/`11`/`12`/`23` to re-extract chart-ready bin-level data, not
  just re-running the existing scripts — a genuinely separate task from the doc/website text
  fixes done in this pass.
- **Part (b): which-trade-to-copy** — given a followable wallet, is *this* trade worth copying?
  Watch for **entry slippage** (a follower gets a worse price than the wallet, so realized edge <
  `holding_excess_return`).
- **CTF modeling** (optional) — add `PositionSplit/Merge/Redeem` events per wallet to recover the
  market-maker population we excluded. Deliberately skipped (they aren't followable), but doable.
- **More part docs / site polish** — Parts 2–5 pages exist; Part 1 has the richest interactivity.
- **Restore `out/cohort_qualifiers.json`** (missing on disk) if the audit trail of exactly which
  sampled wallets were selected by `21_reconstruct_cohort.py`'s tiering matters later — nothing
  downstream reads it, so its absence doesn't block anything, but the provenance is gone.

To reproduce end-to-end: run `10`→`12`, then `20`→`23` (the long fetch), then `30`→`34`.
Everything is cached; re-runs are cheap.
