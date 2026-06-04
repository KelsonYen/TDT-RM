# Production public data providers

TDT-RM production provider CSV generation is configured in `config/public_data_sources.json` and intentionally uses official public sources before any disabled local fallback templates.

## Required production CSVs

A full production fetch validates and writes these generated inputs:

- `price.csv` — TAIEX close, moving averages, returns, turnover, and MA20 turnover.
- `foreign_flow.csv` — TWSE foreign investor net buy/sell aggregate.
- `fx.csv` — USD/TWD and 3-day/5-day changes.
- `breadth.csv` — TWSE advancing and declining issue counts.
- `futures.csv` — TAIFEX TX/TXF futures close, settlement, volume, and open interest.
- `options.csv` — TAIFEX TXO put/call ratio and TAIFEX VIX.
- `leadership.csv` — Main-7 constituents below MA20/MA60.

## Official source mapping

| Provider | Official source | Parser adapter |
| --- | --- | --- |
| TAIEX close and turnover | TWSE `FMTQIK` monthly market summary report | `twse_fmtqik_price` |
| Foreign investor net buy/sell | TWSE `T86` institutional flow report | `twse_t86_foreign_flow` |
| USD/TWD FX | TAIFEX `DailyForeignExchangeRates` OpenAPI | `taifex_daily_fx` |
| Market breadth | TWSE `MI_INDEX` after-trading market report | `twse_mi_index_breadth` |
| TAIEX futures | TAIFEX `DailyMarketReportFut` OpenAPI | `taifex_txf_futures` |
| TAIEX options PCR and VIX | TAIFEX `PutCallRatio` and `TAIFEXVIX` OpenAPI endpoints | `taifex_txo_options` |
| Main-7 leadership | TWSE `STOCK_DAY` per-constituent daily history | `twse_main7_leadership` |

The `cli_price_fallback_csv` runtime source remains available only as an operator break-glass path. It is not enabled in the production configuration and is not required for normal production runs.

## Validation behavior

- Price is required and must provide enough history to derive MA60 and turnover MA20.
- The TWSE price parser checks configured freshness before writing `price.csv`.
- Optional-but-required-for-full-production source failures prevent a no-`--allow-partial` production run from silently succeeding.
- `fetch_manifest.json` and `provider_health.json` record selected sources, failed attempts, freshness status, extracted fields, source type, and cache status for audit.

## Codex runtime and external-network-required providers

FinMind remains available as a fallback fetcher for environments with approved external HTTPS egress, but it is an `external-network-required` provider. Codex runtime should not assume FinMind, TWSE, TAIFEX, or any other live HTTPS provider is reachable because the Codex proxy can reject outbound CONNECT tunnels before provider traffic leaves the container.

For Codex-validated production runs, use the strict local CSV ingestion path documented in `docs/CODEX_NETWORK_LIMITATION.md`: all seven required CSVs must already exist under `inputs/daily/YYYY-MM-DD/`, must validate for schema and date consistency, and must pass before the model is scored. Missing local CSVs are blocking errors; the pipeline must not substitute mock, fallback, or neutral data.
