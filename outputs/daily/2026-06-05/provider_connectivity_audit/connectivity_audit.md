# Production Data Provider Connectivity Audit

- Generated at: `2026-06-06T00:16:24Z`
- Probe as-of date: `2026-06-05`
- Runtime context: `github_actions_runner`
- Scope: connectivity/sample-payload audit only; no scoring model, ETF Exit model, or manual fallback changes.
- GitHub Actions `workflow_dispatch` runs are authoritative for production connectivity; Codex/local network failures are not final provider conclusions.

## Artifact files

- Markdown summary: `connectivity_audit.md`
- JSON artifact: `connectivity_audit.json`
- CSV provider matrix: `provider_matrix.csv`

## Provider matrix

| provider_name | dataset_type | requires_token | token_present | dns_ok | https_ok | http_status | sample_rows_or_payload_present | usable_for_production | failure_reason |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| TWSE official endpoint | TAIEX cash-market price | `False` | `False` | `True` | `True` | `200` | `True` | `True` |  |
| TAIFEX official endpoint | TAIEX futures derivatives | `False` | `False` | `True` | `True` | `200` | `False` | `False` | Provider schema / API failure |
| Yahoo Finance chart API | public TAIEX price (yfinance-compatible) | `False` | `False` | `True` | `True` | `200` | `True` | `True` |  |
| Stooq CSV endpoint | public TAIEX price | `False` | `False` | `True` | `True` | `200` | `True` | `True` |  |
| FinMind API | vendor Taiwan market metadata/sample | `True` | `True` | `True` | `True` | `200` | `False` | `False` | Provider schema / API failure |
| CBC FX official endpoint | USD/TWD FX | `False` | `False` | `True` | `True` | `200` | `False` | `False` | Provider schema / API failure |

## Production usability conclusion

- Usable providers in this runtime: `TWSE official endpoint, Yahoo Finance chart API, Stooq CSV endpoint`
- Observed failure categories: `Provider schema / API failure`
- FinMind: requires a GitHub Actions secret (`FINMIND_TOKEN` or `FINMIND_API_TOKEN`) for production fallback acceptance; an absent token is reported as authentication-not-tested, not provider failure.
- Local fallback/manual CSV paths are intentionally not counted as production success.

## Failure category handling

- Codex runtime network failure: rerun the GitHub Actions workflow before drawing provider conclusions.
- GitHub Actions runner network failure: change endpoint/provider, use a paid provider, or move fetching to a scheduled external fetcher.
- Provider authentication failure: add or rotate GitHub Actions secrets token.
- Provider schema / API failure: implement or repair an official source parser and validation contract.
- Provider rate limit: add backoff/throttling or choose a paid provider with an SLA.
