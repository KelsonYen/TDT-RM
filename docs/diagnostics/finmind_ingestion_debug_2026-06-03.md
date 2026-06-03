# FinMind ingestion debug report — 2026-06-03

## Scope

This diagnostic run executed the existing `--debug-ingestion` workflow only. It did not run the normal production path and did not create or update production daily input CSVs.

## Repository state checks

- Current local branch: `work`.
- Requested `main` pull could not be completed in this container because no Git remotes are configured and no local `main` branch exists. The local HEAD is `41af36a`, the merge commit for PR #48 (`Merge pull request #48 from KelsonYen/codex/-debug-finmind-automated-ingestion-failure`).
- PR #48 debug support is present: `scripts/fetch_daily_data_finmind.py --help` shows `--debug-ingestion`, and the script routes that flag to `run_detailed_ingestion_debug()`.

## Commands run

```bash
git status --short --branch
```

```bash
git remote -v; git branch -a; git fetch --all --prune; git checkout main; git pull --ff-only origin main
```

Result: failed because the repository clone has no configured remotes and no local `main` branch.

```bash
python scripts/fetch_daily_data_finmind.py --help | rg -n -- '--debug-ingestion'
```

Result: passed; the CLI flag is present.

```bash
python scripts/fetch_daily_data_finmind.py --debug-ingestion --sleep-seconds 0 --timeout 30
```

Result: failed intentionally with diagnostic exit code `1` because every dataset probe failed before reaching FinMind, with proxy tunnel status `CONNECT 403`.

```bash
env | sort | sed -n '/PROXY/p;/proxy/p;/FINMIND/p'
python - <<'PY'
import urllib.request
for url in [
    'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date=2026-06-01&end_date=2026-06-03&data_id=TAIEX',
    'https://www.google.com',
]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            print(url, r.status, r.read(100)[:100])
    except Exception as e:
        print(url, type(e).__name__, e)
PY
```

Result: both HTTPS requests failed with `Tunnel connection failed: 403 Forbidden` through the configured `proxy:8080`.

```bash
HTTPS_PROXY= HTTP_PROXY= https_proxy= http_proxy= python - <<'PY'
import urllib.request
url='https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date=2026-06-01&end_date=2026-06-03&data_id=TAIEX'
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        print('status', r.status, r.read(500)[:500])
except Exception as e:
    print(type(e).__name__, e)
PY
```

Result: direct egress without the proxy failed with DNS resolution error, so the container cannot bypass the blocked proxy path.

## Environment / token findings

- `FINMIND_TOKEN detected: NO` was printed by the debug workflow.
- No `FINMIND_TOKEN` environment variable was present in the diagnostic environment.
- The minimum observed blocker is not an API token validation failure. Requests did not reach the FinMind API service; they failed at the container proxy tunnel with `CONNECT 403`.
- Because requests never reached FinMind, this run cannot determine whether a valid token would be accepted by FinMind from a healthy network environment.

## Trade-date resolution

- Latest trade-date resolution failed before provider response parsing:
  - `FinMind request failed for TaiwanStockPrice: <urlopen error Tunnel connection failed: 403 Forbidden>`
  - `FinMind request failed for TaiwanStockPriceAdj: <urlopen error Tunnel connection failed: 403 Forbidden>`
- The debug workflow therefore used diagnostic probe date `2026-06-03`.
- The date range for the 120-day lookback probes was `2026-02-03` through `2026-06-03`, except breadth, which requested `2026-05-20` through `2026-06-03`.

## Dataset diagnostics

The requested failure-classification vocabulary is normalized here as follows: script `NETWORK_ERROR` => `network_error`. No probe reached a response body, so there was no evidence for `auth_error`, `dataset_not_found`, `empty_response`, `schema_mismatch`, `transform_error`, or `unknown_error` during this run.

### price.csv / TaiwanStockPrice:TAIEX

- Dataset name: `TaiwanStockPrice:TAIEX`
- Request URL / parameters:
  - `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date=2026-02-03&end_date=2026-06-03&data_id=TAIEX`
  - `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPriceAdj&start_date=2026-02-03&end_date=2026-06-03&data_id=TAIEX`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `TaiwanStockPrice=CONNECT 403`; `TaiwanStockPriceAdj=CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `close`, `ma5`, `ma20`, `ma60`, `ma20_slope`, `one_day_return_pct`, `two_day_return_pct`, `close_below_ma20_consecutive_days`, `index_5d_return_pct`, `return_60d_pct`, `previous_ma60`, `turnover_amount`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### foreign_flow.csv / TaiwanStockTotalInstitutionalInvestors

- Dataset name: `TaiwanStockTotalInstitutionalInvestors`
- Request URL / parameters: `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTotalInstitutionalInvestors&start_date=2026-02-03&end_date=2026-06-03`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `foreign_spot_net_buy`, `foreign_spot_net_sell`, `foreign_spot_net_sell_consecutive_days`, `foreign_spot_large_sell`, `foreign_large_sell`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### fx.csv / TaiwanExchangeRate:USD

- Dataset name: `TaiwanExchangeRate:USD`
- Request URL / parameters: `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanExchangeRate&start_date=2026-02-03&end_date=2026-06-03&data_id=USD`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `usd_twd_3d_change_pct`, `usd_twd_5d_change_pct`, `twd_appreciates`, `twd_stable`, `twd_depreciates_significantly`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### breadth.csv / TaiwanStockPrice:listed_universe

- Dataset name: `TaiwanStockPrice:listed_universe`
- Request URL / parameters: `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date=2026-05-20&end_date=2026-06-03`
- Date range: `2026-05-20` to `2026-06-03`
- HTTP status code: `CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `index_down`, `advancing_issues`, `declining_issues`, `declining_issues_significantly_expand`, `declining_issues_significantly_gt_advancing`, `declining_gt_advancing_consecutive_days`, `breadth_weakens_for_2_days`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### futures.csv / TaiwanFuturesDaily:TX

- Dataset name: `TaiwanFuturesDaily:TX`
- Request URL / parameters: `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesDaily&start_date=2026-02-03&end_date=2026-06-03&data_id=TX`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `futures_hedging_increases`, `futures_hedging_significant`, `futures_net_short_increases`, `futures_net_short_decreases`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### options.csv / TaiwanOptionDaily:TXO

- Dataset name: `TaiwanOptionDaily:TXO`
- Request URL / parameters: `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanOptionDaily&start_date=2026-02-03&end_date=2026-06-03&data_id=TXO`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `pcr_stable`, `pcr_rises`, `vix_stable`, `vix_rises`, `tail_risk`, `bcd`
- Failure classification: `network_error`
- Additional semantic gap after network is fixed: FinMind `TaiwanOptionDaily` can provide TXO PCR inputs, but the current TDT-RM `options.csv` also requires VIX and formal `tail_risk` / `bcd` fields that are not provided by this FinMind dataset.
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

### leadership.csv / TaiwanStockPrice:Main7

- Dataset name: `TaiwanStockPrice:Main7`
- Request URL / parameters:
  - `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date=2026-02-03&end_date=2026-06-03&data_id=2330`
  - `GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPriceAdj&start_date=2026-02-03&end_date=2026-06-03&data_id=2330`
- Date range: `2026-02-03` to `2026-06-03`
- HTTP status code: `TaiwanStockPrice=CONNECT 403`; `TaiwanStockPriceAdj=CONNECT 403`
- Response row count: `0`
- Response columns: none; no response body was received
- Missing required fields: `trade_date`, `provider_source`, `source_type`, `count_main_7_below_ma20`, `count_main_7_below_ma60`, `majority_main_7_assets_above_ma20`, `main_7_symbols`, `main_7_below_ma20_symbols`, `mhs`
- Failure classification: `network_error`
- Converted to TDT-RM daily input: no; normalized CSV row count was `0`

## Success / conversion summary

- FinMind API connection: not successful from this container. HTTPS CONNECT to both FinMind and an unrelated HTTPS site failed with proxy `403 Forbidden`; direct no-proxy FinMind access failed DNS resolution.
- API token / environment variable: `FINMIND_TOKEN` was not set. The script correctly read the environment and reported token absence.
- Datasets with successful raw response rows: none.
- Datasets with successful TDT-RM daily-input conversion: none.
- Automatic Taiwan-market daily ingestion status: not ready in this environment; no Taiwan index daily data could be fetched or normalized because network egress failed before provider response parsing.

## Minimal root cause

The smallest current blocker is environment/network egress: this container's configured HTTPS proxy rejects outbound CONNECT tunnels with `403 Forbidden`. This blocks every FinMind dataset before authentication, response schema inspection, empty-response detection, or transformation logic can be evaluated.

## Minimal next fix proposal

1. Fix the runtime network/proxy path used by the scheduled ingestion environment so HTTPS requests to `https://api.finmindtrade.com` can complete.
2. Add a `FINMIND_TOKEN` secret/environment variable in the same runtime and rerun `python scripts/fetch_daily_data_finmind.py --debug-ingestion --sleep-seconds 0 --timeout 30`.
3. After network/token are confirmed, classify any remaining failures by provider response evidence:
   - `auth_error`: FinMind status/body indicates missing, invalid, or unauthorized token.
   - `dataset_not_found`: FinMind reports unsupported dataset name.
   - `empty_response`: HTTP/API success with zero rows for the requested date range.
   - `schema_mismatch`: rows exist but required source columns are missing or renamed.
   - `transform_error`: rows exist and source schema is usable, but normalization/derivation fails.
   - `unknown_error`: any remaining uncategorized exception.
4. Keep production ingestion behavior unchanged until a successful debug run reaches FinMind and identifies a non-network defect. The only known post-network semantic gap from this run is `options.csv`, which likely needs non-FinMind VIX / Tail Risk / BCD inputs or an explicit provider split in the next PR.
