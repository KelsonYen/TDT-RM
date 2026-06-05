# Production Fix Report — Daily Production Data Fetch (trade_date=2026-06-04)

## Executive Status

- PRODUCTION_READY: `false`
- data_status: `NOT_READY`
- pipeline_status: `failed`
- Final readiness score: `0/7 required prompt datasets passing`

## Root Cause

- The local execution of the GitHub Actions production-fetch entrypoint for `trade_date=2026-06-04` failed before any official endpoint payload reached a parser. Every TWSE/TAIFEX/CBC/Yahoo/Stooq HTTPS request attempted from this environment failed at tunnel setup with `Tunnel connection failed: 403 Forbidden`.
- FinMind remained fail-closed because it is intentionally disabled unless explicitly opted in and a `FINMIND_TOKEN` or `FINMIND_API_TOKEN` secret is present.
- A workflow-configuration blocker was also verified locally: `python -m pip install -e .` requires build isolation to download `setuptools>=68`, which fails in restricted production runners before fetch code can run. The minimal workflow fix removes this network-dependent editable install from the Daily Production Data Fetch workflow and exports `PYTHONPATH` instead.

## Fix Applied

- Updated `.github/workflows/daily-production-data-fetch.yml` to prepare `PYTHONPATH` directly instead of running the network-dependent editable package installation.
- Added a regression test that guards the production workflow against reintroducing `python -m pip install -e .` in the Daily Production Data Fetch path.

## Dataset Results

| Dataset | Provider used | HTTP status | Rows fetched | Parser result | Validation result | CSV output path | Blocking classification |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `price` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (price.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; STOOQ=NETWORK/network/proxy; TAIWAN_INDEX_PLUS_OFFICIAL=WORKFLOW/no-row; TWSE_OFFICIAL=NETWORK/network/proxy; YAHOO_FINANCE=NETWORK/network/proxy |
| `foreign_flow` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (foreign_flow.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; TWSE_OFFICIAL=NETWORK/network/proxy |
| `fx` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (fx.csv not generated)` | CBC_OFFICIAL=NETWORK/network/proxy; FINMIND_FALLBACK=CONFIG/auth/token; TAIFEX_OFFICIAL=NETWORK/network/proxy; YAHOO_FINANCE=NETWORK/network/proxy |
| `breadth` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (breadth.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; TWSE_OFFICIAL=NETWORK/network/proxy |
| `futures` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (futures.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; TAIFEX_OFFICIAL=NETWORK/network/proxy |
| `options` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (options.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; TAIFEX_OFFICIAL=NETWORK/network/proxy |
| `leadership` | `none` | n/a (request did not reach HTTP response) | 0 | `not_reached` | `not_reached` | `missing (leadership.csv not generated)` | FINMIND_FALLBACK=CONFIG/auth/token; TWSE_OFFICIAL=NETWORK/network/proxy; YAHOO_FINANCE=NETWORK/network/proxy |

## Exact Blocking Dataset(s)

- `price`: blocked; required CSV was not generated.
- `foreign_flow`: blocked; required CSV was not generated.
- `fx`: blocked; required CSV was not generated.
- `breadth`: blocked; required CSV was not generated.
- `futures`: blocked; required CSV was not generated.
- `options`: blocked; required CSV was not generated.
- `leadership`: blocked; required CSV was not generated.

## Datasets Passing

- None.

## Datasets Still Failing

- `price` — TWSE_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/FMTQIK?date=20260601&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); TAIWAN_INDEX_PLUS_OFFICIAL: WORKFLOW (missing enabled Taiwan Index Plus price source config); YAHOO_FINANCE: NETWORK (<urlopen error Tunnel connection failed: 403 Forbidden>); STOOQ: NETWORK (<urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `foreign_flow` — TWSE_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://www.twse.com.tw/fund/T86?date=20260604&selectType=ALL&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `fx` — TAIFEX_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://openapi.taifex.com.tw/v1/DailyForeignExchangeRates after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); CBC_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); YAHOO_FINANCE: NETWORK (<urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `breadth` — TWSE_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260604&type=ALLBUT0999&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `futures` — TAIFEX_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://openapi.taifex.com.tw/v1/DailyMarketReportFut after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `options` — TAIFEX_OFFICIAL: NETWORK (status=failed; https://openapi.taifex.com.tw/v1/PutCallRatio: URL fetch failed from https://openapi.taifex.com.tw/v1/PutCallRatio after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>; https://openapi.taifex.com.tw/v1/TAIFEXVIX: URL fetch failed from https://openapi.taifex.com.tw/v1/TAIFEXVIX after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>; no TAIFEX PCR/VIX row for 2026-06-04); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)
- `leadership` — TWSE_OFFICIAL: NETWORK (status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/STOCK_DAY?date=20260601&stockNo=2330&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>); YAHOO_FINANCE: NETWORK (<urlopen error Tunnel connection failed: 403 Forbidden>); FINMIND_FALLBACK: CONFIG (live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing)

## Final Readiness Score

- `0/7` required prompt datasets have strict CSVs for `trade_date=2026-06-04` in this environment.
- `PRODUCTION_READY=true` was not verifiable here because no real GitHub Actions dispatch facility (`gh`/remote/token) is available in this checkout, and local egress to the required public endpoints is blocked by the environment proxy.
