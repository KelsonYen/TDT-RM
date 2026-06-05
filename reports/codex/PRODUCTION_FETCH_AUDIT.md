# Production Fetch Audit — 2026-06-05

## Scope Guardrails

This sprint changed only production-fetch diagnostics/artifact reporting and tests. No model score formulas, TDT-RM signal rules, ETF exit logic, scoring logic, or light rules were changed.

## A. Current Main-Branch Production Fetch Topology

Production GitHub Actions entrypoint: `.github/workflows/daily-production-data-fetch.yml` invokes `scripts/run_github_actions_production_fetch.py --trade-date "$AS_OF"`. That wrapper invokes `scripts/fetch_daily_data_multi_provider.py` with strict CSV validation enabled, then materializes `inputs/daily/YYYY-MM-DD/`, writes diagnostics under `reports/daily/YYYY-MM-DD/artifacts/`, and writes `outputs/daily/YYYY-MM-DD/fetch_manifest.json`.

Validation gates:

1. Per-provider strict row validation via `validate_strict_row()` before writing each dataset CSV.
2. Staging CSV validation via `validate_daily_input_csvs()`.
3. Production file materialization validation via `validate_required_production_files()`.
4. Artifact contract validation via `validate_fetch_artifact_contract()`.

Artifact generation:

- `reports/daily/YYYY-MM-DD/artifacts/production_fetch_summary.json`
- `reports/daily/YYYY-MM-DD/artifacts/provider_health.json`
- `reports/daily/YYYY-MM-DD/artifacts/validation_report.json`
- `outputs/daily/YYYY-MM-DD/fetch_manifest.json`
- `outputs/daily/YYYY-MM-DD/provider_connectivity_summary.json` after summary rendering

## B. Dataset Provider Chain / Validation / CSV Paths

| Dataset | Provider chain | Primary provider | Fallback provider(s) | Validation rule | Output CSV path |
| --- | --- | --- | --- | --- | --- |
| price | TWSE_OFFICIAL → TAIWAN_INDEX_PLUS_OFFICIAL → YAHOO_FINANCE → STOOQ → FINMIND_FALLBACK | TWSE FMTQIK official public endpoint | Taiwan Index Plus, Yahoo, Stooq, FinMind only if explicitly enabled and tokenized | strict schema + numeric required fields + reconciliation checks | `inputs/daily/<trade_date>/_strict_provider_csvs/price.csv` |
| foreign_flow | TWSE_OFFICIAL → FINMIND_FALLBACK | TWSE T86 official public endpoint | FinMind only if explicitly enabled and tokenized | strict schema for foreign spot buy/sell and boolean fields | `inputs/daily/<trade_date>/_strict_provider_csvs/foreign_flow.csv` |
| fx | TAIFEX_OFFICIAL → CBC_OFFICIAL → YAHOO_FINANCE → FINMIND_FALLBACK | TAIFEX daily FX OpenAPI | CBC, Yahoo, FinMind only if explicitly enabled and tokenized | strict schema for USD/TWD changes and TWD state flags | `inputs/daily/<trade_date>/_strict_provider_csvs/fx.csv` |
| breadth | TWSE_OFFICIAL → FINMIND_FALLBACK | TWSE MI_INDEX official public endpoint | FinMind only if explicitly enabled and tokenized | strict schema for advancing/declining issues and breadth booleans | `inputs/daily/<trade_date>/_strict_provider_csvs/breadth.csv` |
| futures | TAIFEX_OFFICIAL → FINMIND_FALLBACK | TAIFEX DailyMarketReportFut OpenAPI | FinMind only if explicitly enabled and tokenized | strict schema for futures hedge/net-short booleans | `inputs/daily/<trade_date>/_strict_provider_csvs/futures.csv` |
| options | TAIFEX_OFFICIAL → FINMIND_FALLBACK | TAIFEX PutCallRatio + TAIFEXVIX OpenAPI endpoints | FinMind only if explicitly enabled and tokenized | strict schema for PCR/VIX flags plus tail_risk/bcd numeric values | `inputs/daily/<trade_date>/_strict_provider_csvs/options.csv` |
| leadership | TWSE_OFFICIAL → YAHOO_FINANCE → FINMIND_FALLBACK | TWSE STOCK_DAY official public endpoint for Main-7 symbols | Yahoo, FinMind only if explicitly enabled and tokenized | strict schema for Main-7 counts/symbol fields and MHS | `inputs/daily/<trade_date>/_strict_provider_csvs/leadership.csv` |

## C. Production Fetch Validation Run

Command executed against the current branch:

```bash
python scripts/run_github_actions_production_fetch.py --trade-date 2026-06-05
```

The run failed closed in this container because every live public endpoint attempted through the container egress tunnel returned `Tunnel connection failed: 403 Forbidden`; FinMind fallback was disabled by configuration and had no token. The run still produced fail-closed diagnostic artifacts.

| Dataset | Provider used | HTTP status | Rows fetched | Parser status | Validation status | Output CSV |
| --- | --- | --- | ---: | --- | --- | --- |
| price | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| foreign_flow | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| fx | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| breadth | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| futures | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| options | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |
| leadership | none | n/a; tunnel 403 captured as network exception | 0 | not_reached | not_reached | missing |

Focused missing datasets from the prompt:

| Dataset | Official provider attempt | FinMind fallback attempt | Failure layer after fix |
| --- | --- | --- | --- |
| foreign_flow | TWSE_OFFICIAL failed before parser due tunnel 403 | disabled/no token | NETWORK for TWSE; CONFIG for FinMind |
| breadth | TWSE_OFFICIAL failed before parser due tunnel 403 | disabled/no token | NETWORK for TWSE; CONFIG for FinMind |
| options | TAIFEX_OFFICIAL failed before parser due tunnel 403 on both PCR/VIX endpoints | disabled/no token | NETWORK for TAIFEX; CONFIG for FinMind |

## D. Root Cause

Primary root cause observed in this environment: NETWORK. The current container cannot reach TWSE, TAIFEX, CBC, Yahoo, or Stooq public endpoints because HTTPS tunnel establishment is blocked with 403 before any parser receives a payload.

Secondary root cause for fallback chain completion: CONFIG. FinMind fallback is intentionally disabled unless explicitly opted in and a token secret is present. In this run, no `FINMIND_TOKEN` or `FINMIND_API_TOKEN` was present and no FinMind opt-in was enabled.

No live payload reached parser/schema validation in this environment, so this run did not prove a current SCHEMA or PARSER failure for `foreign_flow`, `breadth`, or `options`. Existing parser drift tests for TWSE T86 parenthesized fields, TWSE MI_INDEX numbered breadth tables, and TAIFEX options compact fields pass.

## E. Files Modified

- `scripts/run_github_actions_production_fetch.py` — corrected failure classification so tunnel/proxy 403 is reported as NETWORK instead of AUTH, and added `failure_layer` to manifest source attempts.
- `scripts/render_github_actions_production_fetch_summary.py` — renders/preserves `failure_layer` in GitHub step summaries and provider-health fallback rows.
- `tests/test_github_actions_production_fetch.py` — added regression tests for tunnel 403 NETWORK classification and disabled FinMind CONFIG classification.
- `tests/test_render_github_actions_production_fetch_summary.py` — updated summary expectations and added provider-health fallback NETWORK regression coverage.
- `reports/codex/PRODUCTION_FETCH_AUDIT.md` — this audit report.

## F. Validation Result

- `pytest -q`: PASS, 246 tests.
- `python scripts/run_github_actions_production_fetch.py --trade-date 2026-06-05`: FAIL-CLOSED as expected in this container due NETWORK tunnel 403 and CONFIG-disabled FinMind fallback; diagnostic artifacts were produced.
- `python scripts/fetch_daily_data_multi_provider.py --trade-date 2026-06-05 --input-dir /tmp/tdt_fetch_audit/staging --summary-json /tmp/tdt_fetch_audit/summary.json --provider-health-json /tmp/tdt_fetch_audit/provider_health.json --source-config config/public_data_sources.json --validate`: FAIL-CLOSED for the same NETWORK/CONFIG reasons.

## G. Remaining Risks

1. The container cannot validate true TWSE/TAIFEX live schema today because all official endpoints are blocked before payload retrieval.
2. GitHub Actions may have different egress than this container; if Actions can reach official endpoints, remaining failures would need inspection of the uploaded `source_attempts` with `failure_layer`, parser status, validation status, endpoint, and raw provider diagnostics.
3. FinMind is configured as an explicit opt-in fallback; production remains not ready when official sources are blocked and FinMind is not enabled/tokenized.

## H. Production Ready

Production Ready: **NO** for this validation run.

Reason: required datasets were not materialized because official public endpoints were blocked by NETWORK tunnel 403 and FinMind fallback was CONFIG-disabled/uncredentialed. Diagnostics are production-ready and now classify the failure layer precisely.
