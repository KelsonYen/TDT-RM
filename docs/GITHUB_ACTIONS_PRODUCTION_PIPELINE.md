# GitHub Actions Production Data Fetch Pipeline

## Why production fetching moved out of Codex

The 2026-06-04 production provider audit showed that the Codex runtime cannot be the production network environment for TDT-RM data acquisition: HTTPS `CONNECT` through `proxy:8080` is blocked with `403 Forbidden`, and direct no-proxy DNS resolution fails. That is an egress limitation of the Codex runtime, not a TDT-RM provider or scoring failure.

Production data fetching therefore runs in GitHub Actions, which provides a normal CI network environment and auditable run logs/artifacts. Codex remains suitable for code changes, tests, and review, but **must not** be treated as the production data-fetch runtime.

## Workflow

The workflow is `.github/workflows/daily-production-fetch.yml`.

It performs the following fail-closed sequence:

1. Resolve the trade date.
2. Set up Python.
3. Install repository requirements/package.
4. Run official-source-first production fetchers.
5. Validate strict provider CSV schemas.
6. Materialize the required production input files in `inputs/daily/YYYY-MM-DD/`.
7. Validate required production files, schemas, trade dates, and source types.
8. Run the TDT-RM daily production report.
9. Upload production inputs and reports as GitHub Actions artifacts.

## Data-source policy

The pipeline is official-source-first:

- TAIEX price, foreign investor flow, market breadth, turnover/volume, margin: TWSE official public data first.
- Futures/options and TAIFEX FX: TAIFEX official public data first.
- CBC FX may be used if/when implemented in the provider layer.
- FinMind is allowed only as a vendor fallback, only when explicitly enabled by the workflow, and only when `FINMIND_TOKEN` is present in GitHub Secrets.
- Yahoo Finance is allowed only as fallback for market prices if official market-price providers are unavailable.

The pipeline never silently uses demo, mock, synthetic, stale local fallback, fixture, test, or sample data as production-valid input.

## Required production files

For trade date `YYYY-MM-DD`, a production-valid run must create:

```text
inputs/daily/YYYY-MM-DD/taiex_price.csv
inputs/daily/YYYY-MM-DD/twse_foreign_investor.csv
inputs/daily/YYYY-MM-DD/twse_margin.csv
inputs/daily/YYYY-MM-DD/twse_market_breadth.csv
inputs/daily/YYYY-MM-DD/twse_turnover_or_volume.csv
inputs/daily/YYYY-MM-DD/taifex_futures_options.csv
inputs/daily/YYYY-MM-DD/fx_usdtwd.csv
inputs/daily/YYYY-MM-DD/manifest.json
```

If any file is missing, has a schema error, has a trade-date mismatch, contains stale data, or uses a forbidden source type, the run fails closed.

## Manual run

1. Open GitHub Actions.
2. Select **Daily Production Data Fetch**.
3. Click **Run workflow**.
4. Optionally provide `trade_date` in `YYYY-MM-DD` format.
5. If `trade_date` is blank, the workflow uses the current date in `Asia/Taipei`.

## Scheduled run

The workflow schedule is:

```yaml
cron: "30 8 * * 1-5"
```

That is 08:30 UTC / 16:30 Asia-Taipei, Monday through Friday, after Taiwan market close. The default `trade_date` for scheduled runs is resolved with `TZ=Asia/Taipei date +%F`.

## FINMIND_TOKEN setup

FinMind is a last-resort vendor fallback and is disabled unless the workflow has a token.

To configure it:

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Add a repository secret named `FINMIND_TOKEN`.
4. Paste the FinMind API token as the secret value.

Do not commit tokens to the repository. The workflow reads the token from `${{ secrets.FINMIND_TOKEN }}`.

## Artifacts

Every run uploads artifacts with 90-day retention:

- `tdt-rm-production-inputs-YYYY-MM-DD`: the `inputs/daily/YYYY-MM-DD/` production input directory.
- `tdt-rm-production-reports-YYYY-MM-DD`: the dated report directory under `reports/daily/YYYY-MM-DD/`.

The report artifact includes provider fetch summaries, provider health diagnostics, pipeline summaries, and TDT-RM daily production report outputs when the run reaches the report step.

## How to verify a production-valid run

A run is production-valid only if all of the following are true:

1. The GitHub Actions job is green.
2. `inputs/daily/YYYY-MM-DD/manifest.json` exists and has the same `trade_date` as the run.
3. All required production files listed above exist.
4. CSV validation passed for every required file.
5. Every row has the requested trade date and a non-empty `provider_source` and `source_type`.
6. No row uses forbidden source types such as `demo`, `mock`, `synthetic`, `fixture`, `test`, `sample`, `stale`, `local_csv_fallback`, or `local_json_fallback`.
7. Provider health and fetch summaries identify any failed provider attempts and the reason for each failure.
8. The TDT-RM daily production report and pipeline summary artifacts exist.

If any condition fails, the run is not production-valid and must be treated as blocked until the provider failure or schema issue is resolved.
