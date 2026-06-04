# GitHub Actions Production Data Fetch Pipeline

## Why production fetching moved out of Codex

The 2026-06-04 production provider audit showed that the Codex runtime cannot be treated as the production network environment for TDT-RM data acquisition: HTTPS `CONNECT` through the container proxy is blocked with `403 Forbidden`, and direct no-proxy DNS resolution is unavailable. That is an egress limitation of the Codex runtime, not proof that TWSE, TAIFEX, CBC, FinMind, or any other provider is down.

Production-readiness validation therefore runs in GitHub Actions on `ubuntu-latest`, which provides public internet egress, auditable logs, step summaries, and downloadable artifacts. Codex remains suitable for code changes, tests, and review, but **must not** be treated as the live production data-fetch runtime.

## Workflow

The workflow is `.github/workflows/daily-production-fetch.yml`.

It performs this fail-closed sequence:

1. Resolve the `as_of` date from `workflow_dispatch` input, or use the current Asia/Taipei date for scheduled runs.
2. Set up Python and install the package.
3. Run the live production fetch and pipeline command:

   ```bash
   python scripts/fetch_daily_provider_csvs.py \
     --as-of "$AS_OF" \
     --output-dir "inputs/daily/$AS_OF/" \
     --run-pipeline \
     --pipeline-output-dir "outputs/daily/$AS_OF/" \
     --json-summary "outputs/daily/$AS_OF/summary.json"
   ```
4. Preserve fail-closed behavior: a missing `price.csv` or missing required production CSV category fails the job unless the CLI is explicitly run in a non-production partial mode (the workflow does not do that).
5. Write a GitHub Actions step summary listing `price.csv` written/missing, required CSVs present/missing, selected provider source per category, `data_status`, pipeline status, and uploaded artifact paths.
6. Upload the dated input/output directories plus `fetch_manifest.json` and `summary.json`.

## Data-source policy

The pipeline is official-source-first through `config/public_data_sources.json`:

- TAIEX price, foreign investor flow, market breadth, and margin: TWSE official public data.
- Futures/options and TAIFEX FX: TAIFEX official public OpenAPI data.
- CBC FX may be used as an official FX fallback.
- Local/manual fallback is not enabled by the workflow and is not counted as production-ready.
- FinMind remains disabled by default; the workflow only exposes an explicit `allow_finmind` input/environment flag for configurations that intentionally opt in.

The pipeline never silently uses demo, mock, synthetic, stale local fallback, fixture, test, sample, manual import, or local fallback data as production-valid live-provider success.

## Required production provider CSV categories

A full production fetch requires these eight provider CSV categories to agree with the implementation:

- `price.csv`
- `foreign_flow.csv`
- `fx.csv`
- `breadth.csv`
- `futures.csv`
- `options.csv`
- `leadership.csv`
- `margin.csv`

If any required category is missing, stale, malformed, or uses a forbidden source type, the run fails closed. `price.csv` remains the hard blocker for running the production pipeline.

## Manual run

The workflow includes `workflow_dispatch`, so it can be manually triggered from GitHub Actions.

1. Open the repository on GitHub.
2. Select **Actions** in the repository navigation.
3. Select **Daily Production Data Fetch**.
4. Click **Run workflow**.
5. Enter `as_of`, for example `2026-06-04`.
6. Leave `allow_finmind` disabled unless intentionally validating a FinMind-enabled configuration.
7. Wait for the job to finish; a green job means every required provider CSV and the daily pipeline passed the fail-closed gates on the GitHub-hosted runner.

## Scheduled run

The workflow schedule is:

```yaml
cron: "30 10 * * 1-5"
```

That is 10:30 UTC / 18:30 Asia/Taipei, Monday through Friday. Scheduled runs resolve the date with `TZ=Asia/Taipei date +%F`.

## Artifacts

Every run uploads `tdt-rm-production-fetch-YYYY-MM-DD` with 90-day retention. Inspect these paths first:

```text
inputs/daily/YYYY-MM-DD/
inputs/daily/YYYY-MM-DD/fetch_manifest.json
outputs/daily/YYYY-MM-DD/
outputs/daily/YYYY-MM-DD/summary.json
```

`fetch_manifest.json` records provider CSV paths, required-category gaps, provider health, source attempts, selected source type, cache status, and URL retry diagnostics. `summary.json` combines the fetch result and pipeline result when the pipeline is reached.

## How to verify a production-valid run

A run is production-valid only if all of the following are true:

1. The GitHub Actions job is green.
2. `inputs/daily/YYYY-MM-DD/fetch_manifest.json` exists and has the same `as_of` date as the run.
3. `outputs/daily/YYYY-MM-DD/summary.json` exists.
4. `price.csv` exists under `inputs/daily/YYYY-MM-DD/`.
5. All eight required provider CSV categories are present.
6. Provider source attempts identify the live source selected per category.
7. No row/source uses forbidden fallback, mock, synthetic, fixture, test, sample, manual/local fallback, or stale data as production success.
8. The pipeline status in the step summary is completed.

If any condition fails, the run is not production-valid and must be treated as blocked until the provider, schema, or pipeline issue is resolved.
