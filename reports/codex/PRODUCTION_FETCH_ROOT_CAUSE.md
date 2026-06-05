# Production Fetch Root-Cause Audit

- Audit target trade date: `2026-06-03` (workflow default completed trading-day rerun).
- Audit artifact source: `reports/daily/2026-06-03/artifacts/production_fetch_summary.json` and `reports/daily/2026-06-03/artifacts/provider_health.json`.
- Verification command: `PYTHONPATH=src:. python scripts/run_github_actions_production_fetch.py --trade-date 2026-06-03`.
- Scope guard: this audit changes reports only; it does **not** modify TDT-RM logic, ETF logic, scoring logic, signal rules, CP formula, CAL logic, report generation, validation rules, or backtest logic.

## Executive conclusion

- `Daily Production Data Fetch` is blocked before parser success, strict validation success, and CSV artifact generation.
- The exact observed blocker is provider acquisition: every non-token live endpoint attempt fails at the network/connectivity layer with `Tunnel connection failed: 403 Forbidden`.
- Taiwan Index Plus cannot rescue price because the production config has no enabled concrete endpoint, and FinMind is intentionally unavailable unless `allow_finmind=true`/`TDT_RM_ALLOW_FINMIND_LIVE=true` **and** `FINMIND_TOKEN` or `FINMIND_API_TOKEN` is present.
- Therefore the strict fetch run remains `NOT_READY`, with required CSVs missing before the downstream `PRODUCTION_READY` artifact contract can be satisfied.

## Overall production status from audit artifact

- Overall status: `NOT_READY`.
- Missing datasets: `price.csv, foreign_flow.csv, fx.csv, breadth.csv, futures.csv, options.csv, leadership.csv, margin.csv`.
- FinMind fallback: allow_finmind=`False`, token_present=`False`, skipped=`True`, skip_reason=`allow_finmind false`.

## Dataset-by-dataset audit

### price

- Provider chain: `TWSE_OFFICIAL → TAIWAN_INDEX_PLUS_OFFICIAL → YAHOO_FINANCE → STOOQ → FINMIND_FALLBACK`.
- Endpoints:
  - `TWSE_OFFICIAL`: `https://www.twse.com.tw/exchangeReport/FMTQIK?date=20260601&response=json`.
  - `TAIWAN_INDEX_PLUS_OFFICIAL`: `configured endpoint is blank/disabled`.
  - `YAHOO_FINANCE`: `Yahoo chart API for ^TWII`.
  - `STOOQ`: `Stooq daily CSV for twii`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TWSE_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `TAIWAN_INDEX_PLUS_OFFICIAL`: No HTTP request; missing enabled Taiwan Index Plus source configuration.
  - `YAHOO_FINANCE`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `STOOQ`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for price`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TWSE_OFFICIAL`: `status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/FMTQIK?date=20260601&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `TAIWAN_INDEX_PLUS_OFFICIAL`: `missing enabled Taiwan Index Plus price source config`.
  - `YAHOO_FINANCE`: `<urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `STOOQ`: `<urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration; F. Workflow configuration / B. Authentication`.

### foreign_flow

- Provider chain: `TWSE_OFFICIAL → FINMIND_FALLBACK`.
- Endpoints:
  - `TWSE_OFFICIAL`: `https://www.twse.com.tw/fund/T86?date=20260603&selectType=ALL&response=json`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TWSE_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for foreign_flow`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TWSE_OFFICIAL`: `status=failed; URL fetch failed from https://www.twse.com.tw/fund/T86?date=20260603&selectType=ALL&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

### breadth

- Provider chain: `TWSE_OFFICIAL → FINMIND_FALLBACK`.
- Endpoints:
  - `TWSE_OFFICIAL`: `https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260603&type=ALLBUT0999&response=json`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TWSE_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for breadth`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TWSE_OFFICIAL`: `status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260603&type=ALLBUT0999&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

### futures

- Provider chain: `TAIFEX_OFFICIAL → FINMIND_FALLBACK`.
- Endpoints:
  - `TAIFEX_OFFICIAL`: `https://openapi.taifex.com.tw/v1/DailyMarketReportFut`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TAIFEX_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for futures`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TAIFEX_OFFICIAL`: `status=failed; URL fetch failed from https://openapi.taifex.com.tw/v1/DailyMarketReportFut after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

### options

- Provider chain: `TAIFEX_OFFICIAL → FINMIND_FALLBACK`.
- Endpoints:
  - `TAIFEX_OFFICIAL`: `https://openapi.taifex.com.tw/v1/PutCallRatio and https://openapi.taifex.com.tw/v1/TAIFEXVIX`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TAIFEX_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for options`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TAIFEX_OFFICIAL`: `status=failed; https://openapi.taifex.com.tw/v1/PutCallRatio: URL fetch failed from https://openapi.taifex.com.tw/v1/PutCallRatio after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>; https://openapi.taifex.com.tw/v1/TAIFEXVIX: URL fetch failed from https://openapi.taifex.com.tw/v1/TAIFEXVIX after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>; no TAIFEX PCR/VIX row for 2026-06-03`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

### fx

- Provider chain: `TAIFEX_OFFICIAL → CBC_OFFICIAL → YAHOO_FINANCE → FINMIND_FALLBACK`.
- Endpoints:
  - `TAIFEX_OFFICIAL`: `https://openapi.taifex.com.tw/v1/DailyForeignExchangeRates`.
  - `CBC_OFFICIAL`: `https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en`.
  - `YAHOO_FINANCE`: `Yahoo chart API for USDTWD=X`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TAIFEX_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `CBC_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `YAHOO_FINANCE`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for fx`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TAIFEX_OFFICIAL`: `status=failed; URL fetch failed from https://openapi.taifex.com.tw/v1/DailyForeignExchangeRates after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `CBC_OFFICIAL`: `status=failed; URL fetch failed from https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `YAHOO_FINANCE`: `<urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

### leadership

- Provider chain: `TWSE_OFFICIAL → YAHOO_FINANCE → FINMIND_FALLBACK`.
- Endpoints:
  - `TWSE_OFFICIAL`: `https://www.twse.com.tw/exchangeReport/STOCK_DAY?date=20260601&stockNo=2330&response=json (first Main-7 symbol; remaining symbols not reached)`.
  - `YAHOO_FINANCE`: `Yahoo chart API for Main-7 symbols`.
  - `FINMIND_FALLBACK`: `FinMind live API; disabled unless opted in and tokened`.
- HTTP response / provider attempt result:
  - `TWSE_OFFICIAL`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `YAHOO_FINANCE`: HTTPS CONNECT tunnel `403 Forbidden`; no provider payload body was returned.
  - `FINMIND_FALLBACK`: No HTTP request; fallback disabled/unavailable because opt-in and token are missing.
- Rows fetched: `0`.
- Parser result: not reached; no provider payload row reached normalization/parser output.
- Validation result: `all providers failed for leadership`.
- Output CSV generated: `No`; `output_path` is `null` in the strict production fetch result.
- Exact failure layer:
  - `TWSE_OFFICIAL`: `status=failed; URL fetch failed from https://www.twse.com.tw/exchangeReport/STOCK_DAY?date=20260601&stockNo=2330&response=json after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `YAHOO_FINANCE`: `<urlopen error Tunnel connection failed: 403 Forbidden>`.
  - `FINMIND_FALLBACK`: `live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing`.
- Classification: `A. Connectivity; F. Workflow configuration / B. Authentication`.

## Layer-by-layer verification

1. **Connectivity:** failing for official TWSE, TAIFEX, CBC, Yahoo, and Stooq attempts with `Tunnel connection failed: 403 Forbidden`. This prevents payload retrieval and leaves `rows fetched = 0` for all seven audited datasets.
2. **Authentication:** FinMind is not tested because fallback is disabled and no token is present in the observed run. If official connectivity remains blocked, FinMind requires both explicit opt-in and a token secret.
3. **Provider unavailable/configuration:** Taiwan Index Plus is configured as a disabled template with no concrete endpoint, so it cannot rescue price.
4. **Parser:** no parser-specific failure is observed for the audited production blocker; parsers are not reached after connectivity/configuration/authentication failures.
5. **Validation:** strict dataset validation reports `all providers failed for <dataset>` because no provider produces a candidate row. This is downstream of acquisition, not a schema/rule defect.
6. **Workflow configuration:** scheduled and default workflow-dispatch runs have FinMind disabled by design. `allow_finmind=true` is available only for manual dispatch and still requires a GitHub Secret token.
7. **Artifact generation:** dataset CSVs are not generated because `write_strict_csv` is only called after a provider row passes strict validation/reconciliation; no provider reaches that point.

## Final blocker classification

- Primary blocker: **A. Connectivity** for official/public endpoints (`Tunnel connection failed: 403 Forbidden`).
- Secondary blocker if connectivity remains blocked: **F. Workflow configuration / B. Authentication** because FinMind fallback is disabled by default and requires `FINMIND_TOKEN` or `FINMIND_API_TOKEN` plus explicit opt-in.
- Not the blocker: parser logic, strict validation rules, scoring logic, signal rules, CP formula, CAL logic, report generation logic, validation-rule logic, or backtest logic.
