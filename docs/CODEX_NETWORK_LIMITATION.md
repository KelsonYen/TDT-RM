# Codex Network Limitation for Daily Production

## Confirmed runtime limitation

Codex runtime outbound HTTPS cannot be treated as a production data-source assumption for TDT-RM daily runs.

Observed behavior in the Codex container:

- Proxy mode: outbound HTTPS through `proxy:8080` is terminated by Envoy with `CONNECT 403` before provider traffic reaches the upstream service.
- Cross-check: the same HTTPS tunnel failure was observed for an unrelated HTTPS target such as `google.com`, so this is not specific to FinMind or to TDT-RM provider code.
- Direct/no-proxy mode: outbound direct mode does not provide usable DNS resolution, so bypassing the proxy is also unavailable in this runtime.

## Production architecture implication

Live provider fetchers, including the FinMind fetcher, are **external-network-required** components. They may be run in a production network or CI environment with approved egress, credentials, DNS, and proxy policy, but they must not be assumed available inside Codex runtime.

Codex production validation should therefore prefer the offline/local CSV path:

1. Place the seven required strict CSV files under `inputs/daily/YYYY-MM-DD/`:
   - `price.csv`
   - `foreign_flow.csv`
   - `fx.csv`
   - `breadth.csv`
   - `futures.csv`
   - `options.csv`
   - `leadership.csv`
2. Validate all seven files before scoring:

   ```bash
   python scripts/validate_daily_input_csvs.py --trade-date YYYY-MM-DD --input-dir inputs/daily/YYYY-MM-DD
   ```

3. Run the daily production pipeline from those local inputs:

   ```bash
   python scripts/run_daily_production_pipeline.py \
     --trade-date YYYY-MM-DD \
     --input-dir inputs/daily/YYYY-MM-DD \
     --outputs-dir outputs/daily \
     --reports-dir reports/daily/YYYY-MM-DD \
     --pipeline-summary outputs/daily/tdt_rm_daily_YYYY-MM-DD_summary.json
   ```

## Fail-closed policy

The local CSV path is intentionally fail-closed:

- If any of the seven required CSV files is missing, validation fails and lists the missing file path.
- If required columns are missing, validation fails before model scoring.
- If any row's `trade_date` does not match the requested production date, validation fails before model scoring.
- `source_type` values that indicate fallback, mock, fixture, synthetic, neutral, sample, or test data are rejected.
- The daily production runner must not invent missing fields, silently use fake rows, or fill gaps with neutral scores.

## FinMind status

The FinMind ingestion code remains in the repository for environments with working external network access, but it is marked and documented as `external-network-required`. A FinMind failure inside Codex runtime should be interpreted as an environment egress limitation unless a run from a healthy network proves otherwise.
