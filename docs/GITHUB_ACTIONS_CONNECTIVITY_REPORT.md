# GitHub Actions Production Connectivity Report

Audit date: `2026-06-04T08:10:12Z`

Scope: audit-only connectivity check for the production-data provider endpoints used by the production-data pipeline. This report does not change models, scoring, feature logic, TDT-RM decision logic, or provider code.

## GitHub Actions trigger status

The repository contains the requested GitHub Actions workflow at `.github/workflows/production-data-connectivity-audit.yml`. The local workspace could not dispatch it to GitHub because this checkout has no configured GitHub remote, `gh` is not installed, and no GitHub token is present in the environment. The same workflow entrypoint was therefore executed from the repository with:

```bash
python scripts/audit_market_data_connectivity.py --output-dir outputs/production_data_connectivity_audit --repeat 2
```

The audit failed closed in this execution environment: every provider had DNS resolution failures and HTTPS proxy tunnel denial (`403 Forbidden`). Treat the classifications below as the captured connectivity state for this audit run, not as evidence that the providers are globally unavailable.

## Provider results

| Provider | Production role | DNS result | HTTPS result | HTTP status | Response latency | Sample payload availability | Classification |
|---|---|---|---|---:|---:|---|---|
| TWSE | Official cash-market source | `FAIL: gaierror: [Errno -3] Temporary failure in name resolution` | `FAIL: URLError: <urlopen error Tunnel connection failed: 403 Forbidden>` | `null` | `7 ms` | `NO` | `UNUSABLE` |
| TAIFEX | Official derivatives source | `FAIL: gaierror: [Errno -3] Temporary failure in name resolution` | `FAIL: URLError: <urlopen error Tunnel connection failed: 403 Forbidden>` | `null` | `6 ms` | `NO` | `UNUSABLE` |
| FinMind | Vendor fallback source | `FAIL: gaierror: [Errno -3] Temporary failure in name resolution` | `FAIL: URLError: <urlopen error Tunnel connection failed: 403 Forbidden>` | `null` | `5 ms` | `NO` | `UNUSABLE` |
| Public FX source (CBC) | Official public USD/TWD FX fallback | `FAIL: gaierror: [Errno -3] Temporary failure in name resolution` | `FAIL: URLError: <urlopen error Tunnel connection failed: 403 Forbidden>` | `null` | `5 ms` | `NO` | `UNUSABLE` |

## Classification rules used

- `PRODUCTION_READY`: DNS succeeds, HTTPS succeeds, HTTP status is 2xx/3xx, and a sample payload is available without observed authentication or rate-limit failure.
- `PARTIAL`: DNS succeeds but the endpoint has a material production caveat such as authentication requirement, rate-limit observation, non-2xx/non-3xx status, or unavailable sample payload.
- `UNUSABLE`: DNS fails, HTTPS fails, or the endpoint cannot return any usable sample payload in the audited runtime.

## Findings

- No provider returned a sample payload in the audited environment.
- All required providers were classified as `UNUSABLE` for this run because DNS resolution failed before a usable HTTPS response could be established.
- The HTTPS errors were proxy tunnel denials rather than provider-level application responses, so the result indicates an execution-environment egress problem.
- FinMind remains a fallback source only and should remain token-gated in production; it should not silently replace official sources.

## Recommended official production provider order

1. `TWSE` — first official source for cash-market price, foreign-flow, breadth, and leadership data.
2. `TAIFEX` — first official source for futures/options and derivatives-derived production fields.
3. `Public FX source (CBC)` — official public USD/TWD FX fallback for exchange-rate continuity.
4. `FinMind` — vendor fallback only, explicitly enabled and authenticated via production secret; never the primary official provider.

## Production readiness conclusion

Current audited runtime readiness: `UNUSABLE` for all tested providers.

Production recommendation: keep the official provider order above, but do not mark the production connectivity path ready until a successful GitHub-hosted workflow run produces DNS success, HTTPS success, valid HTTP status, acceptable latency, and sample payload availability for the official endpoints.
