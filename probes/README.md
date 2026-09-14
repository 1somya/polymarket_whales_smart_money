# probes/

Throwaway investigation scripts from the **FIRST TASK** of the "worth following?" study —
probing the lum.id findata per-market trades endpoint
(`/findata/prediction-markets/trades/polymarket/{conditionId}`) to decide whether it was a
usable second data source.

- `probe_findata_trades.py` — bare-endpoint schema (per-fill: trade_id, token_id, side, price, size, taker, ts)
- `probe2_depth.py` — fields / pagination: only `limit` works; **taker-only** (no maker leg)
- `probe3_resolved.py` — max-limit ceiling + **forward-capture starting ~May 2026** (no pre-May backfill)
- `probe4_retention.py` — tape retention after resolution (high-volume markets keep it; coverage is selective)

**Conclusion: findata was EXCLUDED from the pipeline** (taker-only would corrupt FIFO cost
basis and erase market-makers; splicing it onto the both-legs subgraph at the April seam would
manufacture a false edge-decay artifact). The study uses the Goldsky orderbook subgraph only,
window ≤ 2026-04-28. Full rationale in the durable memory note `polymarket-follow-study-datasource`.
