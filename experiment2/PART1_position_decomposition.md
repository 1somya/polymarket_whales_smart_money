# Part 1 — Position-Level PnL Decomposition

The foundation of the "Is Any Wallet Worth Following?" study. Everything in Parts 2–5 is built
on the table Part 1 produces.

---

## 1. Why Part 1 exists — the measurement problem

Wallets don't just "bet and wait." They buy and sell the same outcome repeatedly, then hold
whatever is left to resolution. So *"did they win?"* has **no single answer**, and any `win_rate`
column that pretends otherwise measures the wrong thing.

Example: a wallet buys 10k YES @ 0.30, buys 5k @ 0.40, sells 14k @ 0.65 before resolution, and
holds 1k to a resolution that **loses**. That wallet was *wrong about the outcome* and still
*made money*. Was it a winner?

Part 1's job: split every position's realized profit into two **economically distinct** sources.

| source | what it is | copyable? |
|---|---|---|
| **`pnl_trading`** | money from price movement — bought low, sold high, *before* resolution | ❌ no — it's an execution/spread edge |
| **`pnl_holding`** | money from being right about the outcome — tokens carried to $1/$0 settlement | ✅ yes — a copyable outcome view |

Following a wallet only makes sense if its edge is in **holding**. A wallet that earns everything
from **trading** has no copyable outcome view.

---

## 2. What a "position" is

One row = one **(wallet, market, outcome-token)**. All of a wallet's fills for a single token are
grouped into one position. A market with YES/NO tokens can therefore yield up to two positions per
wallet (flagged `hedged` if they bought both).

---

## 3. The method — worked on a real position

Real position: wallet `0x000d25…`, token `…977194`, market `0xd00f74…`. Four fills:

**Step 1 — raw fills** (from `lib_subgraph.normalize`, in time order):

| time | side | price | size | role |
|---|---|---|---|---|
| Jul-29 14:50 | BUY | 0.740 | 20.0 | taker |
| Jul-29 14:50 | BUY | 0.736 | 1,413.2 | maker |
| Jul-31 05:25 | BUY | 0.820 | 1,245.9 | maker |
| Aug-06 20:55 | SELL | 0.830 | 600.0 | maker |

Totals: bought **2,679** tokens for **$2,077**, sold **600** for **$498**, **held 2,079** to resolution.

**Step 2 — resolution** enters *only* as the payout. This token **WON → $1**. (Resolution never
touches any pre-resolution quantity — no leakage.)

**Step 3 — FIFO matching.** The 600-token SELL consumes the **earliest** buys first:

- 20 tokens from the 0.740 lot → trading gain (0.830 − 0.740) × 20 ≈ **$1.8**
- 580 tokens from the 0.736 lot → trading gain (0.830 − 0.736) × 580 ≈ **$54.5**
- → **`pnl_trading` ≈ $56**

The **unsold FIFO remainder** is what's held to settlement:

- 833 left from the 0.736 lot → (1.00 − 0.736) × 833 ≈ **$220**
- 1,246 from the 0.820 lot → (1.00 − 0.820) × 1,246 ≈ **$224**
- → **`pnl_holding` ≈ $444**

**Result:** `pnl_total = $56 + $444 = $500.02`.

**Step 4 — reconciliation (the validation gate).** The two buckets must re-sum to raw cash flow:

```
sells ($498.00) + payout ($2,079.02) − buys ($2,077.00) = $500.02
pnl_trading + pnl_holding                                = $500.02   ✓  (error 1.7e-13)
```

**Why FIFO?** It respects time order — early cheap buys are credited to the early sell that
consumed them. We *also* compute an average-cost (VWAP) version (`*_vwap` columns) as a
robustness check; no conclusion changed between the two.

---

## 4. Conventions (each is a named constant in `lib_decompose.py`)

*(These three are Part-1-specific, kept here for the worked example above. The full rationale
for every ruling across all of Part 4 lives in `EXPERIMENT2_GUIDE.md` §4 — this is a subset.)*

- **Sell-at-resolution tolerance** (`HOLD_PRICE_HI = 0.97`, `HOLD_PRICE_LO = 0.03`): a sell at
  $0.99 a minute before a YES resolution is economically a *hold*. So a sell above 0.97 (or below
  0.03) has its PnL routed to the **holding** bucket, not trading. This only re-labels which
  bucket the PnL lands in — it never changes the cash, so reconciliation still holds.
  - The brief's third trigger — "within 60 minutes of resolution" — is **not computed**: there is
    no resolution timestamp in our data. We use the two price triggers and say so.
- **`direction_correct`**: did the held tokens resolve the way the wallet bet? Defined **only if
  tokens were actually held to resolution**. A wallet that fully exited before resolution gets
  `NULL`, *not* "wrong" — a full exit means they took no view on the event. (Recording it as a
  loss is exactly the leaderboard bug this study avoids.)
- **`held_fraction_strict` vs `held_fraction_adjusted`**: strict = tokens literally held to
  settlement; adjusted = near-resolution sells counted as holds too. Both are carried forward.

---

## 5. Edge cases — flagged, counted, never silently dropped

| case | flag | handling |
|---|---|---|
| Bought both YES and NO in a market | `hedged` | direction undefined; kept in $ aggregates, excluded from outcome metrics |
| Sold more than ever bought | `oversold` | CTF split/merge gap (tokens minted off-book, no cost basis) → excluded from clean metrics |
| Market not resolved (or resolved after the subgraph cutoff) | `resolved = 0` | recorded but excluded; `pnl_holding` left blank — never blend unrealized into realized |
| No net-long entry (pure maker-sell / short) | — | skipped (not a "position"); volume tallied for the exclusion report |

---

## 6. Files & reading order

**Created for Part 1**
- `lib_decompose.py` — the decomposition engine (FIFO/VWAP → trading/holding).
- `10_part1_positions.py` — the driver (loops wallets, edge cases, validation, output).

**Used by Part 1 (existing infrastructure)**
- `lib_subgraph.py` — loads & normalizes raw fills.
- `lib_recon.py` — token→market and market→resolution lookups.

**Read in this order to trace the whole process:**

1. **`lib_subgraph.py`** — the input. `fetch_fills()` (L44) pulls a wallet's full fill history;
   `normalize()` (L76) decodes one raw fill into `{token, side, size, price, ts, is_maker}`.
2. **`lib_recon.py`** — `resolve_tokens()` (L42): token→`conditionId`, market→`{resolved, winners}`.
   The only place resolution enters.
3. **`lib_decompose.py`** — the core. Constants (L29–59) → `_fifo_match()` (L63) → `decompose()` (L106).
4. **`10_part1_positions.py`** — the driver. Docstring (L1–40) → `build_positions()` (L46, the main
   loop + edge cases + reconciliation) → `main()` (L207, writes outputs + prints the gate).
5. **`out/positions.csv`** — the deliverable (⚠️ 652 MB / 2.38M rows — read a slice, not the whole file).
6. **`out/part1_stats.json`** + **`out/wallet_meta.csv`** — edge-case counts / reconciliation, and
   the per-wallet fill-activity summary Part 2 joins onto.

*Shortest path to the logic:* `lib_decompose.py` L29–130.

---

## 7. Output schema — `out/positions.csv` (33 columns)

**Identity & flags**
`wallet`, `condition`, `token`, `resolved`, `won`, `direction_correct`, `hedged`, `oversold`,
`n_fills`, `maker_fills`

(There is no per-row "truncated" column — wallets with an incomplete fetch are excluded from
this file entirely upstream, in `build_positions()`; see §5.)

**Position quantities**
`tokens_bought`, `tokens_sold`, `tokens_held_to_res`, `held_fraction_strict`,
`held_fraction_adjusted`, `vwap_buy`, `vwap_sell`, `buy_usd`, `sell_usd`, `usd_held`,
`usd_held_adjusted`

**Decomposition — FIFO (primary)**
`pnl_trading`, `pnl_holding`, `pnl_holding_settle`, `pnl_total`, `cash_flow`, `recon_err`

**Decomposition — VWAP (robustness)**
`pnl_trading_vwap`, `pnl_holding_vwap`, `pnl_total_vwap`

**Tolerance transparency**
`res_equiv_sold_tokens`, `res_equiv_sold_usd`, `oversold_tokens`

---

## 8. Scale & validation results

**Current** (re-run 2026-08-14, on the 6,347-wallet fill cache, post the 2026-08-03
truncated-history-wallet ruling — see `README.md`'s Gotchas — which excludes 1,347 wallets
whose fetch still hit the order cap, leaving 4,990 reconstructed):

| | |
|---|---|
| positions written | **963,376** |
| resolved | 527,109 |
| clean resolved (not oversold/hedged) | **367,178** |
| **reconciliation gate** | **PASS** — max \|pnl_trading + pnl_holding − cash_flow\| = **6.40e-07 USD** |
| FIFO vs VWAP \|Δ pnl_trading\| per clean resolved position | median $0.00, mean $11.75, max $120,772.51 |

The gate passing is the guarantee that the trading/holding split is arithmetically sound for
every clean position — the precondition for trusting anything in Parts 2–5. Re-running `10`
is fully deterministic (pure computation over already-cached fills, no network I/O) and
reproduces these numbers exactly — verified during the 2026-08-14 pipeline review.

*(Superseded prior runs, kept for provenance: an original 284-wallet winners-only pass —
212,471 positions, 73,541 clean resolved; then a pre-truncdrop-ruling full-cohort pass —
2,377,625 positions, 1,290,308 resolved, ~888,000 clean, gate PASS at 8.4e-07 USD — cut down
to the numbers above once the 1,347 incomplete-history wallets were excluded. Same gate, same
conventions throughout — only the included wallet set changed.)*
