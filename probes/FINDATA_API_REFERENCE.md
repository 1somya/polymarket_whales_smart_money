# lum.id `findata` API — Reference (Polymarket)

What we learned by probing the lum.id **findata** API during the "worth following?" study.
Everything below was verified by live requests (see `probes/probe*.py`); examples are real
responses captured 2026-07-21…23.

- **Base URL:** `https://lum.id/findata/prediction-markets`
- **Auth:** none. But send a browser `User-Agent` header (e.g. `Mozilla/5.0`) or you may get 403.
- **Format:** JSON. Endpoints return either a bare JSON **array** or an **object**.
- **One-line verdict:** usable for *aggregates* (leaderboard) and a *live per-market taker
  tape*; **not** usable for full history or maker-side data. We ultimately used the Goldsky
  subgraph instead (see `probes/README.md`).

---

## ✅ Endpoint 1 — Leaderboard (per-wallet AGGREGATES)

```
GET /leaderboard?venue=polymarket&limit=500
```

Returns a JSON **array** of the top wallets by `total_pnl`.

**Quirks**
- **Hard-capped at 500 rows** — `limit=1000` / `limit=5000` still return 500.
- Sorted by `total_pnl` descending (winners only → survivorship bias; no losers).

**Fields**

| field | type | meaning |
|---|---|---|
| `rank` | int | 1-based rank by `total_pnl` |
| `wallet` | str | address |
| `total_pnl` | float | mark-to-market PnL = realized **+** unrealized (paper) |
| `realized_pnl` | float | settled PnL only |
| `volume` | float | USDC traded |
| `roi` | float | return ratio (e.g. 1.10 = +110%) |
| `trades` | int | fill count |
| `win_rate` | float | 0–1 (note: a *count* win-rate — the metric this study argues is misleading) |
| `primary_style` | str | style label, e.g. `WHALE` |
| `is_whale` | bool | whale flag |
| `first_trade_at` | str | ISO-8601 UTC |

**Real example** (`rank 1`)
```json
{
  "rank": 1,
  "wallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
  "total_pnl": 22053933.34,
  "realized_pnl": 22000015.96,
  "volume": 20066524.36,
  "roi": 1.0963544808,
  "trades": 16002,
  "win_rate": 0.4634146341,
  "primary_style": "WHALE",
  "is_whale": true,
  "first_trade_at": "2024-10-14T15:15:52Z"
}
```

---

## ✅ Endpoint 2 — Per-market trades (a live TAKER tape)

```
GET /trades/polymarket/{conditionId}
```

Returns a JSON **array** of individual fills for **one market** (keyed by Polymarket
`conditionId`, the `0x…` hash). Default page size **500**, newest first.

**Fields**

| field | type | meaning |
|---|---|---|
| `trade_id` | str | fill hash |
| `token_id` | str | ERC-1155 outcome-token id (identifies market + YES/NO side) |
| `side` | str | `BUY` / `SELL` — **the taker's** side |
| `price` | float | token price 0–1 (= implied probability) |
| `size` | float | number of tokens |
| `taker` | str | wallet address — **the taker only** (see limitations) |
| `ts` | str | ISO-8601 UTC timestamp |

**Real example**
```json
{
  "trade_id": "0x8ca4e9526abb16c459869d28f2105d1a5aeccc7fb35fb2168df38094bf357f5b",
  "token_id": "69222761152567422456550754954182616722608546823277879350969354961713727175064",
  "side": "BUY",
  "price": 0.001,
  "size": 1000.0,
  "taker": "0x6ad5b3e7c8d14cc8ebaa075827224df309d8bdaa",
  "ts": "2026-07-23T09:54:54Z"
}
```

**Quirks / limitations** (these are why we didn't use it)
- **TAKER-ONLY.** There is no `maker` field. findata is a *taker tape*: one row per print,
  labeled with the taker. A wallet's **maker** fills are attributed to whoever took against
  them, so maker-side activity (market-makers) is invisible — and cannot be recovered by any
  query.
- **Only `limit` paginates.** `limit=3`→3 rows; `limit=2000`→ up to that market's full depth
  (e.g. 1263). `offset`, `page`, `before`, `cursor`, `days` are **silently ignored** (all
  return the default 500). So no time-window queries and no cursor paging — you pull one big
  `limit` and slice client-side.
- **Live / forward-capture, ~May 2026 onward.** Fills are recent (today's data appears); the
  tape does not backfill before ~May 2026 even for older markets. Non-overlapping in time with
  the legacy subgraph (which ends 2026-04-28).
- **Selective coverage.** High-volume markets retain their tape after resolution; thin or old
  markets return an empty `[]` (HTTP 200 with zero rows).

---

## ❌ What findata does NOT have

**No per-wallet trade/position/activity endpoint.** All of these return **404** (or ignore the
param):

```
/trades/polymarket?user={wallet}            -> 404
/trades/polymarket?wallet={wallet}          -> 404
/trades/polymarket/wallet/{wallet}          -> 404
/wallet/{wallet}/trades                     -> 404
/positions/polymarket/{wallet}              -> 404
/activity/polymarket/{wallet}               -> 404
/pnl|user|traders/polymarket/{wallet}       -> 404
/leaderboard?...&wallet={wallet}            -> 200 but the wallet param is ignored
/trades/polymarket/{wallet}                 -> 200 [] (path only keys on conditionId; a
                                                       wallet is treated as an unknown market)
```

**Consequences**
- You **cannot** query a wallet's trade history from findata — the trades endpoint keys only on
  market (`conditionId`).
- Even if a per-wallet route existed, it could only return trades where the wallet was the
  **taker** (findata is a taker tape), so **maker trades are unreachable** through findata by
  any route.

---

## When to use / not use

| Need | findata? | Use instead |
|---|---|---|
| Top-wallet aggregate leaderboard | ✅ leaderboard (cap 500, winners only) | — |
| A live tape of recent takers in one market | ✅ per-market trades | — |
| Full per-wallet history | ❌ | Goldsky orderbook subgraph |
| Maker-side / both-sides fills | ❌ (taker tape) | subgraph `orderFilledEvents` (has `maker`+`taker`) |
| Anything before ~May 2026 | ❌ (forward-capture) | subgraph (ends 2026-04-28) |
| Settled trade history with prices | ❌ | subgraph |

Full rationale for excluding findata from the study: `probes/README.md` and the memory note
`polymarket-follow-study-datasource`.
