# Production Fetch Validation Report — 2026-06-04

## Scope

This report validates the TDT-RM production data-fetch pipeline only. It does **not** change model logic, scoring, calibration, or daily-model thresholds.

Requested GitHub Actions target: `.github/workflows/daily-production-fetch.yml` (`workflow_dispatch`).

Target trade date used for validation: `2026-06-04`.

## GitHub Actions execution status

GitHub Actions dispatch and artifact download could not be completed from this container because the checkout has no configured GitHub remote, the GitHub CLI is not installed, no GitHub token is present in the environment, and outbound HTTPS from the container is blocked by the local tunnel with `403 Forbidden`.

Evidence commands:

```text
$ gh auth status
/bin/bash: line 1: gh: command not found

$ git remote -v
# no remote URL configured

$ python - <<'PY'
# urllib request to https://api.github.com/repos/KelsonYen/TDT-RM/actions/workflows/daily-production-fetch.yml/runs?per_page=5
PY
URLError <urlopen error Tunnel connection failed: 403 Forbidden>
```

Because of that environment limitation, this run did **not** prove a new GitHub-hosted `daily-production-fetch.yml` workflow run. I therefore executed the same production-fetch entrypoint invoked by the workflow locally, without running the separate connectivity audit.

Workflow entrypoint validated:

```text
python scripts/run_github_actions_production_fetch.py \
  --trade-date 2026-06-04 \
  --source-config config/public_data_sources.json
```

## Workflow definition audited

The GitHub Actions workflow is configured to:

1. Resolve a `TRADE_DATE` from the `workflow_dispatch` input or current Asia/Taipei date.
2. Install Python requirements and the package.
3. Run `scripts/run_github_actions_production_fetch.py` with `config/public_data_sources.json`.
4. Allow FinMind live fallback only when `FINMIND_TOKEN` exists.
5. Commit generated `inputs/daily/${TRADE_DATE}` and `reports/daily/${TRADE_DATE}`.
6. Upload two artifact sets:
   - `tdt-rm-production-inputs-${TRADE_DATE}`
   - `tdt-rm-production-reports-${TRADE_DATE}`

## Production fetch result

Overall status: **NOT_READY**.

The production fetch failed closed before production CSV materialization because all live provider fetches were blocked by the container network tunnel. This is an **environment/workflow-execution access issue in this container**, not evidence of a provider parser or schema failure in GitHub-hosted Actions.

Generated local artifacts inspected:

| Artifact | Exists | Inspection result |
| --- | ---: | --- |
| `reports/daily/2026-06-04/artifacts/production_fetch_summary.json` | Yes | Shows every required dataset failed and lists missing strict provider CSVs. |
| `reports/daily/2026-06-04/artifacts/provider_health.json` | Yes | Shows each provider attempt failed closed, primarily with `Tunnel connection failed: 403 Forbidden`; FinMind fallback remained disabled because no token was supplied. |
| `inputs/daily/2026-06-04/_strict_provider_csvs/*.csv` | No | No strict provider CSVs were generated. |
| `inputs/daily/2026-06-04/*.csv` | No | No production CSVs were generated. |
| `inputs/daily/2026-06-04/manifest.json` | No | Production manifest was not generated because required staged CSVs were missing. |
| `reports/daily/2026-06-04/*.md` | No | Daily production report was not generated because the fetch stage failed. |
| `reports/daily/2026-06-04/artifacts/pipeline_summary.json` | No | Daily model pipeline did not run because strict provider CSV validation could not pass. |

## Dataset validation table

Rows retrieved are counted from generated strict provider CSVs. Since no dataset CSVs were created, every row count is `0`.

| Dataset | Required staged CSV | Production CSV | Source provider attempted | Rows retrieved | Schema validation | Result |
| --- | --- | --- | --- | ---: | --- | --- |
| TAIEX price | `price.csv` | `taiex_price.csv` | TWSE_OFFICIAL, Taiwan Index Plus disabled template, Yahoo Finance, Stooq, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| Foreign investor flow | `foreign_flow.csv` | `twse_foreign_investor.csv` | TWSE_OFFICIAL, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| USD/TWD FX | `fx.csv` | `fx_usdtwd.csv` | TAIFEX_OFFICIAL, CBC_OFFICIAL, Yahoo Finance, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| Market breadth | `breadth.csv` | `twse_market_breadth.csv` | TWSE_OFFICIAL, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| TAIFEX futures | `futures.csv` | included in `taifex_futures_options.csv` | TAIFEX_OFFICIAL, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| TAIFEX options | `options.csv` | included in `taifex_futures_options.csv` | TAIFEX_OFFICIAL, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| Main-7 leadership | `leadership.csv` | daily-model staged input only | TWSE_OFFICIAL, Yahoo Finance, FinMind fallback disabled | 0 | Not reached; CSV missing | Failed |
| Margin | `margin.csv` | `twse_margin.csv` | Not evaluated in local failure summary because upstream fetch failed before a selected margin output existed | 0 | Not reached; CSV missing | Failed |
| Turnover/volume | derived from `price.csv` | `twse_turnover_or_volume.csv` | Derived from selected TAIEX price provider | 0 | Not reached; source `price.csv` missing | Failed |

## Missing datasets

The local production-fetch summary reported these missing required strict provider CSVs:

- `price.csv`
- `foreign_flow.csv`
- `fx.csv`
- `breadth.csv`
- `futures.csv`
- `options.csv`
- `leadership.csv`

The production materialization layer also requires these production CSVs, none of which were generated in this run:

- `taiex_price.csv`
- `twse_foreign_investor.csv`
- `twse_margin.csv`
- `twse_market_breadth.csv`
- `twse_turnover_or_volume.csv`
- `taifex_futures_options.csv`
- `fx_usdtwd.csv`
- `manifest.json`

## Schema validation assessment

Schema validation is fail-closed in two layers:

1. Strict staged daily input validation requires eight provider CSVs: `price.csv`, `foreign_flow.csv`, `fx.csv`, `breadth.csv`, `futures.csv`, `options.csv`, `leadership.csv`, and `margin.csv`.
2. Production-file validation requires the materialized production CSV set plus `manifest.json`.

For this run, schema validation did not reach field-level validation because the fetch stage produced no CSV files. The validation result is therefore **failed due to missing required CSVs**, not failed due to malformed fields.

## Daily model sufficiency assessment

Production readiness: **NOT READY**.

The generated outputs are **not sufficient** to run the TDT-RM daily model without manual data entry because:

- No strict provider CSVs were generated.
- No production CSVs were materialized.
- No production `manifest.json` exists.
- No daily report or `pipeline_summary.json` exists.
- The daily production pipeline intentionally failed closed before model execution.

## Failure classification

| Failure | Root cause | Classification | Exact fix |
| --- | --- | --- | --- |
| Cannot dispatch `daily-production-fetch.yml` from this container | No `gh` binary, no configured GitHub remote URL, no GitHub token, and GitHub API HTTPS blocked by local tunnel `403 Forbidden` | Workflow execution environment / credentials / network access | Run dispatch from an authenticated environment with repository remote and Actions permissions: `gh workflow run daily-production-fetch.yml --repo KelsonYen/TDT-RM -f trade_date=2026-06-04`, then download artifacts with `gh run download <run-id> --repo KelsonYen/TDT-RM --dir artifacts/gha-production-fetch-2026-06-04`. |
| All official provider attempts failed locally | Local container outbound provider HTTPS is blocked by `Tunnel connection failed: 403 Forbidden` | Environment network, not parser/schema | Re-run on GitHub-hosted Actions, where connectivity was separately reported as verified, or unblock outbound HTTPS in this container. Do not change parsers based only on this local tunnel failure. |
| FinMind fallback not used | FinMind live fallback is intentionally token-gated and no `FINMIND_TOKEN` was present | Credentials / configured fallback policy | If vendor fallback is desired, add repository secret `FINMIND_TOKEN`; workflow already passes `--allow-finmind-live` only when the secret exists. |
| Production CSVs missing | Upstream provider fetch stage returned `NOT_READY`, so materialization did not run | Expected fail-closed workflow behavior | Fix execution environment/provider access first; then rerun production fetch. |
| Daily model did not run | Strict CSV validation failed because all staged CSVs were missing | Expected fail-closed workflow behavior | Generate all required strict provider CSVs from live providers, then rerun `scripts/run_github_actions_production_fetch.py`. |

## Recommended next validation command sequence

Run these commands from a workstation or CI environment with GitHub CLI, repository access, and Actions permissions:

```bash
gh workflow run daily-production-fetch.yml --repo KelsonYen/TDT-RM -f trade_date=2026-06-04
run_id="$(gh run list --repo KelsonYen/TDT-RM --workflow daily-production-fetch.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --repo KelsonYen/TDT-RM --exit-status
gh run download "$run_id" --repo KelsonYen/TDT-RM --dir artifacts/gha-production-fetch-2026-06-04
find artifacts/gha-production-fetch-2026-06-04 -type f -maxdepth 4 -print
python scripts/validate_daily_input_csvs.py --trade-date 2026-06-04 --input-dir artifacts/gha-production-fetch-2026-06-04/tdt-rm-production-inputs-2026-06-04/_strict_provider_csvs
python scripts/run_github_actions_production_fetch.py --trade-date 2026-06-04 --source-config config/public_data_sources.json --skip-fetch --staging-dir artifacts/gha-production-fetch-2026-06-04/tdt-rm-production-inputs-2026-06-04/_strict_provider_csvs
```

Expected pass criteria after a successful GitHub-hosted run:

- `overall_status` is `READY` or equivalent passing status.
- Every required staged dataset has `status=success`, `provider_used` populated, and row count greater than zero.
- Every required production CSV exists under `inputs/daily/2026-06-04/`.
- `manifest.json` declares all required production files.
- Strict staged schema validation returns no errors.
- Production CSV schema validation returns no errors.
- Daily report and `pipeline_summary.json` are generated without manual data entry.
