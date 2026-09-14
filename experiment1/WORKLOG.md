# Work Log — a guided, checkable account of exactly what I did

This is the chronological record of **what I did, how it works, and how you can see it
for yourself**. It includes the dead-ends (the API cap, the rejected 36 GB fallback)
because those decisions are where trust is won or lost.

Every step has four parts:
- **DID** — what I ran / built
- **HOW IT WORKS** — the mechanics or formula, in plain terms
- **FOUND** — what came back (real numbers)
- **👀 SEE IT** — a copy-paste command (run from inside `/Users/somya/polymarket-whales/`)
  that shows you the actual evidence — usually by opening a file or printing a real record.

---

## Orientation — how to browse everything

```
polymarket-whales/
├── FINDINGS.md          ← the results / answer
├── README.md            ← how to run the pipeline
├── WORKLOG.md           ← THIS FILE (what I did + how to check)
│
├── 01_leaderboard.py    ← Step 1  honest realized-only leaderboard
├── 02_fetch_fills.py    ← Phase A fetch raw order fills (parallel)
├── 02b_prefetch_meta.py ← Phase A2 resolve token→market→winner + metadata
├── 03_fingerprints.py   ← Step 2  reconstruct positions → per-wallet metrics
├── 05_cluster.py        ← Step 3  cluster into species (behaviour only)
├── 06_plot.py           ← Step 4  the scatter
├── lib_subgraph.py      ← subgraph client + fill→(side,size,price) normaliser
├── lib_recon.py         ← position reconstruction + resolution lookups
│
├── data/                ← ALL raw + intermediate data (the evidence, 2.5 GB)
│   ├── lumid_full.json          the 500-wallet leaderboard, as pulled
│   ├── fills/<wallet>.json      every order fill for each wallet (raw, from subgraph)
│   ├── tok2cond.json            token id → market (conditionId)
│   ├── cond_payout.json         market → which outcome won
│   └── gamma_meta.json          market → category, open time, close time
│
└── out/                 ← everything I produced
    ├── leaderboard_honest.csv       Step 1 output, one row per wallet
    ├── fingerprints.csv             Step 2 output, one row per wallet, 33 columns
    ├── fingerprints_clustered.csv   cohort + assigned species
    ├── cluster_profile.csv          Step 3 summary table
    └── winrate_vs_roi.png           Step 4 the plot
```

**Three ways to look at things:**
- **CSV files** (`out/*.csv`) — open in Excel/Numbers/any spreadsheet, or:
  `python3 -c "import pandas as pd; print(pd.read_csv('out/fingerprints.csv').head().to_string())"`
- **JSON files** (`data/*.json`) — these are the raw evidence. Peek at any of them:
  `python3 -m json.tool data/cond_payout.json | head`
- **The scatter** — `open out/winrate_vs_roi.png`

**The single best way to see what I did** is the end-to-end worked example at the bottom
(§Worked example) — it follows ONE real wallet from a raw blockchain fill all the way to
its species label, showing every number.

---

## Phase 0 — Explore the data sources BEFORE building (as the brief required)

### 0.1 The primary leaderboard (lum.id)
- **DID** Pulled the professor's endpoint and saved it verbatim to `data/lumid_full.json`.
- **HOW IT WORKS** It's a plain JSON array, one object per wallet. Crucially it reports
  `realized_pnl` and `total_pnl` as **separate** fields — so the money already *is*
  split into "settled" vs "settled + open paper marks."
- **FOUND** Exactly **500 rows** (asking for 1000 still returns 500). Fields:
  `rank, wallet, total_pnl, realized_pnl, volume, roi, trades, win_rate, primary_style,
  is_whale, first_trade_at`. It is the **top-500 by total_pnl** → contains no losers →
  survivorship (flagged throughout).
- **👀 SEE IT**
  `python3 -c "import json; d=json.load(open('data/lumid_full.json')); print('rows:',len(d)); print('rank1:',d[0])"`
  and to prove it's genuinely the live data, re-pull and compare the count:
  `curl -s "https://lum.id/findata/prediction-markets/leaderboard?venue=polymarket&limit=500" | python3 -c "import sys,json; print('live rows:',len(json.load(sys.stdin)))"`

### 0.2 Per-wallet trades (Polymarket data-api) — the wall that shaped the project
- **DID** Tried to page a wallet's full trade history from `/trades?user=…`.
- **HOW IT WORKS** You page with `limit` + `offset`. I probed the offset ceiling, the
  `takerOnly` flag, and every plausible time-filter parameter.
- **FOUND** Three hard facts: (1) default returns **taker fills only** (799 for rank #1);
  `takerOnly=false` is needed for maker fills. (2) Paging **stops dead at offset ~4,000**
  no matter the wallet — rank #3 (175,287 trades per lum.id) returns exactly 4,000 then
  empties. (3) **Every** time parameter (`before/after/startTs/from/to/…`) is silently
  ignored. → The endpoint only ever yields the last ~4,000 fills and **cannot** rebuild
  an active wallet's history. *This is the "APIs fight back" scenario, and finding it
  (plus proving no workaround exists) is what made the early phase slow.*
- **👀 SEE IT** — reproduce the cap live on a 175k-trade wallet:
  ```
  python3 - <<'PY'
  import urllib.request, json
  UA={"User-Agent":"Mozilla/5.0"}; g=lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA)))
  w="0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee"   # lum.id says 175,287 trades
  tot,off=0,0
  while True:
      b=g(f"https://data-api.polymarket.com/trades?user={w}&limit=1000&offset={off}&takerOnly=false")
      if not b: break
      tot+=len(b); off+=1000
      if off>7000: break
  print("data-api returned", tot, "fills, then stopped — vs 175,287 claimed")
  PY
  ```

### 0.3 The sanctioned fallback (36 GB dataset) — evaluated, then rejected
- **DID** Read the repo + schema doc for `jon-becker/prediction-market-analysis`; probed
  the download object with `curl -I`.
- **HOW IT WORKS** It's a 36 GB zstd tarball of parquet files (raw on-chain `OrderFilled`
  events: maker/taker/asset_id/amounts/block) — no wallet→trade convenience, no
  token→market map.
- **FOUND** `content-length: 36 GB`, `last-modified: 2026-02-05` (stale ~5 months). It's
  complete but old and needs heavy decoding. Kept as a last resort while I looked for
  something live and uncapped.

### 0.4 The unlock — Polymarket's Goldsky subgraphs (live, uncapped)
- **DID** Introspected the legacy Goldsky subgraphs and tested cursor pagination on a
  wallet the data-api had capped.
- **HOW IT WORKS** A subgraph is a GraphQL database of blockchain events. The `orderbook`
  subgraph's `orderFilledEvents` is the complete CLOB fill log. The 4,000-row limit is
  dodged with a **timestamp cursor**: ask for fills `where timestamp ≥ last_seen`, sort
  ascending, dedupe, repeat — you can walk the entire history 1,000 at a time.
- **FOUND** **12,980 fills in 16 s** for the wallet the data-api stopped at 4,000 — full
  history, no cap. This became the data spine. Caveat discovered and flagged everywhere:
  the legacy subgraphs stop indexing at the **2026-04-28** contract migration, so wallets
  first active after that date are invisible.
- **👀 SEE IT** — pull rank #1's *entire* history right now and see it dwarf the 4,000 cap:
  `python3 lib_subgraph.py 0x56687bf447db6ffa42ffe2204a05edaa20f55839`
  → `20498 fills … 28 distinct tokens`. The raw fills are cached at
  `data/fills/0x56687bf447db6ffa42ffe2204a05edaa20f55839.json` — open it and you'll see
  individual blockchain fills (see the worked example for what one looks like).

### 0.5 Resolution + market metadata (who won, what category, when it opened/closed)
- **DID** Tested the subgraph's `Condition` entity and the CLOB `/markets/{cid}` endpoint.
- **HOW IT WORKS** A market ("condition") has two outcome tokens. `payoutNumerators`
  like `['0','1']` means the **second** token won. The CLOB endpoint adds `tags`
  (category), `accepting_order_timestamp` (open), `end_date_iso` (close).
- **FOUND** Winner, category and open/close are all recoverable per market. (Gamma's
  batch filter missed most older markets, so I used CLOB per-market instead.)
- **👀 SEE IT** `python3 -c "import json,itertools; c=json.load(open('data/cond_payout.json')); print(dict(itertools.islice(c.items(),3)))"`
  → each market maps to `{'resolved': True, 'winners': ['<winning token id>']}`.

> The full data-access map is also saved to my long-term memory (`polymarket-data-access.md`)
> so a future session doesn't have to rediscover the 4,000 cap.

---

## Phase 1 — Step 1: the honest leaderboard (`01_leaderboard.py`)

- **DID** Recomputed the ranking on realized money alone and measured how much it moves.
- **HOW IT WORKS** For each wallet I split
  `unrealized_implied = total_pnl − realized_pnl`, then rank once by `total_pnl` (as given)
  and once by `realized_pnl` (honest). `rank_delta` is how far each wallet moves. **The
  two PnL types are never added into a single ranking number.**
- **FOUND** Top-10 **unchanged**; the 20–500 tier reshuffles (Spearman ρ = 0.82, median
  move **17** places, max **487**); **19/500** wallets have **negative** realized PnL; the
  worst falls **#12 → #499** (−$4.8M realized hidden behind +$12.1M of open-position paper,
  reported by lum.id with a fake 100% win rate). Conclusion: the board is right at the very
  top but **misranks the body** by blending settled money with open marks.
- **👀 SEE IT** Run it (recomputes from the raw leaderboard):
  `python3 01_leaderboard.py`
  Then open the result and look at the biggest movers:
  `python3 -c "import pandas as pd; d=pd.read_csv('out/leaderboard_honest.csv'); print(d.sort_values('rank_delta',ascending=False)[['wallet','rank_total','rank_realized','total_pnl','realized_pnl','unrealized_pnl_implied','win_rate']].head(5).to_string(index=False))"`

---

## Phase 2 — Fetch the raw fills (`02_fetch_fills.py`)

- **DID** Downloaded the full order-fill history for the reconstructable cohort, in
  parallel, to `data/fills/`.
- **HOW IT WORKS** 6 worker threads, each walking one wallet's history via the timestamp
  cursor from Phase 0.4. I process the **top 350 by total_pnl**, but **skip** wallets that
  are post-cutoff (first trade > 2026-04-28, invisible) or bot-scale (>250k trades, too
  many fills), and **cap each wallet at 40,000 fills** (anything larger is flagged
  `truncated`). *Correctness fix made here:* a network error now **raises** instead of
  being cached as "0 fills," so a transient failure can never masquerade as an empty
  history.
- **FOUND** **278 wallets, 5.7 million fills, ~12.5 minutes, 0 failures** (~8,000 fills/s).
- **👀 SEE IT** How many wallets and fills are on disk:
  `ls data/fills | wc -l`
  `python3 -c "import glob,json; print(sum(len(json.load(open(f))['fills']) for f in glob.glob('data/fills/*.json')), 'fills cached')"`
  Look at one wallet's raw fills:
  `python3 -c "import json; o=json.load(open('data/fills/0x56687bf447db6ffa42ffe2204a05edaa20f55839.json')); print('truncated:',o['truncated'],'fills:',len(o['fills'])); print(o['fills'][0])"`

---

## Phase 3 — Resolve every market (`02b_prefetch_meta.py`)

- **DID** Turned the raw token ids in the fills into "which market, and who won,"
  plus category/timing.
- **HOW IT WORKS** Collect every distinct outcome-token across all cached fills →
  batch-map token→market (`tok2cond.json`) → batch-map market→winner (`cond_payout.json`)
  → parallel-fetch category/open/close from CLOB (`gamma_meta.json`).
- **FOUND** **148,535 tokens → 57,679 markets** resolved. Category/timing coverage is only
  ~**33%** (old sports/hourly markets lack CLOB metadata) — which is why `entry_timing`
  is treated as lower-confidence and `category_HHI` is dropped from clustering later.
- **👀 SEE IT**
  `python3 -c "import json; print('markets resolved:',len(json.load(open('data/cond_payout.json')))); g=json.load(open('data/gamma_meta.json')); print('with category:',sum(1 for v in g.values() if v.get('category')))"`

---

## Phase 4 — Reconstruct positions → the fingerprint (`03_fingerprints.py`, `lib_recon.py`)

- **DID** Turned each wallet's raw fills into **positions**, then into one row of metrics.
- **HOW IT WORKS** — this is the analytical heart, so here are the exact formulas.
  Group a wallet's fills by outcome token. For each token (= one bet):
  - `entry_price` = total USDC spent on **buys** ÷ tokens bought  (volume-weighted price paid)
  - `stake` = total USDC spent on buys  (how much they wagered)
  - `realized_pnl` = money from sells + (tokens still held × payout) − money spent buying
    — where payout is $1 if that token won, else $0
  - `won` = did this token win (from `cond_payout.json`)
  Then per wallet:
  - `count_win_rate` = winning positions ÷ resolved positions
  - `dollar_win_rate` = $ staked on winners ÷ $ staked on all resolved positions
  - **`sizing_gap` = dollar_win_rate − count_win_rate** (positive ⇒ bets bigger when right)
  - `excess_return` = average of (outcome − entry_price)/entry_price (did they beat the
    price they paid?)
  - `brier_score` = average of (entry_price − outcome)² (calibration)
  **The winner is used only AFTER resolution** — it never touches entry_price, size, side
  or timing (all computed from fills alone). Ran in **98 seconds** for all 500.
- **FOUND** Reconstructed realized PnL correlates **0.85** with lum.id's realized figure
  (method validated). *Sample-size funnel:*
  ```
  500 leaderboard → 66 post-cutoff invisible → 278 reconstructed
      → 197 fully reconstructed → 102 below the 50-resolved floor
      → 95 CLEAN COHORT  (+ 81 truncated at the 40k-fill cap)
  ```
- **👀 SEE IT** Reconstruct one wallet transparently and watch the numbers print:
  `python3 lib_recon.py 0x56687bf447db6ffa42ffe2204a05edaa20f55839`
  Check the validation correlation yourself:
  `python3 -c "import pandas as pd; d=pd.read_csv('out/fingerprints.csv'); c=d[(d.reconstructed==True)&(d.truncated==False)&(d.n_resolved>=50)]; print('recon vs lum.id realized corr:',round(c.recon_realized_pnl.corr(c.lz_realized_pnl),3))"`
  See the funnel:
  `python3 -c "import pandas as pd; d=pd.read_csv('out/fingerprints.csv'); print('reconstructed:',(d.n_fills>0).sum()); print('clean cohort:',((d.truncated==False)&(d.n_resolved>=50)).sum())"`

---

## Phase 5 — Cluster into species (`05_cluster.py`)

- **DID** Grouped the 95-wallet clean cohort into behavioural types.
- **HOW IT WORKS** I cluster on **behaviour only** — 6 signature features (avg_entry_price,
  entry_timing, hold_days, maker/taker ratio, trade_frequency, position_size), each
  standardised, heavy-tailed ones log-scaled. **PnL/ROI/win rate are NOT inputs** — profit
  is attached *afterwards* as an outcome, so I can't accidentally "cluster on the answer."
  I checked stability across k=3–6 (k-means vs Ward, reseed agreement) and fixed **k=4** as
  the interpretable, reproducible partition. `category_HHI` was dropped (too low coverage
  → produced a spurious HHI=1); `favorite_share` dropped (redundant with entry price).
- **FOUND** 4 species — HFT market maker (n30, **40%** of cohort profit), Favorite
  conviction bettor (n23, 26%), Mid-price active trader (n28, 20%), Large directional
  taker (n14, 15%). Separation is **soft** (silhouette ≈ 0.2) — a continuum, stated as
  such, not crisp islands. Cross-cutting result: **3 of 4 species have negative median
  excess-return** → profit comes from sizing and volume, not per-bet forecasting edge.
- **👀 SEE IT** Run it — the k-stability table and the full cluster profile print out:
  `python3 05_cluster.py`
  Prove profit was never a clustering input (read the feature list in the source):
  `grep -n -A3 "CLUSTER_FEATURES =" 05_cluster.py`
  See the summary table:
  `python3 -c "import pandas as pd; print(pd.read_csv('out/cluster_profile.csv')[['name','n_wallets','med_roi','med_count_win','med_sizing_gap','med_excess_ret','share_pos_profit']].to_string(index=False))"`

---

## Phase 6 — The plot (`06_plot.py`)

- **DID** Drew win-rate (x) vs ROI (y), dot size = volume, colour = species, top-10
  annotated where present; colourblind-safe palette.
- **FOUND** Winners span win rates **0.19–0.84** with no ROI dependence → win rate is not
  a valid ranking criterion; the leaderboard's implicit "more wins = better" is incoherent.
- **👀 SEE IT** `python3 06_plot.py && open out/winrate_vs_roi.png`

---

## Worked example — one wallet, raw fill → species (see the whole chain)

This traces **rank #1** (`0x5668…5839`) so you can watch a single number travel through
every stage. Run each ✅ and compare.

**1. A raw fill** (exactly as the subgraph returned it, stored in `data/fills/…5839.json`):
```json
{ "timestamp":"1728918952", "maker":"0x5668…5839", "taker":"0x3dc0…8941",
  "makerAssetId":"0", "takerAssetId":"42699…46128",
  "makerAmountFilled":"260000", "takerAmountFilled":"1000000" }
```
`makerAssetId:"0"` = the maker (our wallet) paid **USDC**; it paid 260,000 (÷1e6 = $0.26)
to receive 1,000,000 (÷1e6 = 1.0) tokens. → a **BUY of 1 token at $0.26**.
✅ `python3 -c "import lib_subgraph as s,json; o=json.load(open('data/fills/0x56687bf447db6ffa42ffe2204a05edaa20f55839.json')); print(s.normalize(o['fills'][0],'0x56687bf447db6ffa42ffe2204a05edaa20f55839'))"`
→ `{'side':'BUY','size':1.0,'price':0.26,...}`

**2. Fills grouped into a position** (all fills on one token → one bet):
one of rank #1's positions bought a token at avg **$0.369**, staked **$5.18M**, the token
**won**, and it realized **+$8.87M**, held ~14.7 days.
✅ `python3 -c "import lib_recon as R; p=[x for x in R.reconstruct('0x56687bf447db6ffa42ffe2204a05edaa20f55839')['positions'] if x['resolved']][0]; print({k:p[k] for k in ['entry_price','stake','won','realized_pnl','hold_days']})"`

**3. Positions rolled up into the fingerprint row** (`out/fingerprints.csv`):
22 resolved positions, **count_win_rate 0.64**, **dollar_win_rate 0.97**,
**sizing_gap +0.34**, recon realized **$29.9M** (lum.id says $22.0M). The sizing_gap is the
whole story — this wallet wins 64% of its bets but places **97% of its dollars** on the
winners.
✅ `python3 -c "import pandas as pd; d=pd.read_csv('out/fingerprints.csv'); r=d[d.wallet=='0x56687bf447db6ffa42ffe2204a05edaa20f55839'].iloc[0]; print({k:round(r[k],3) for k in ['n_resolved','count_win_rate','dollar_win_rate','sizing_gap']})"`

**4. Why it's NOT in the clustering cohort:** only 22 resolved positions < the 50 floor.
Rank #1 is a *concentrated conviction bettor* — too few bets to fingerprint reliably, so
it's reported but not clustered. (A wallet that *is* in the cohort, e.g. rank #2 with 67
resolved positions, lands in **"Favorite conviction bettor."**)
✅ `python3 -c "import pandas as pd; d=pd.read_csv('out/fingerprints_clustered.csv'); r=d[d.wallet=='0x1f2dd6d473f3e824cd2f8a89d9c69fb96f6ad0cf'].iloc[0]; print('rank#2 species:',r['cluster_name'],'| resolved:',int(r['n_resolved']))"`

---

## The caveats — keep these in view while checking
1. **Survivorship** — the source is top-500 by PnL; there are **no losing wallets** in the
   data. I can describe species of winner, not what separates winners from losers.
2. **Cohort scope** — the 95 clustered wallets hold **21%** of top-500 realized profit; the
   biggest concentrated whales fall below the 50-resolved floor (like rank #1 above).
3. **Cutoff** — the subgraph ends 2026-04-28; 66/500 wallets (incl. several top-10) are
   invisible.
4. **Order-book only** — wallets trading mainly via negRisk/AMM aren't captured.
5. **Cost basis** — split/merge/redeem CTF operations aren't modeled, so profit *magnitude*
   defers to lum.id (behaviour is still from the fills).
6. `category_HHI` excluded from clustering (28% coverage); `entry_timing` lower-confidence.
