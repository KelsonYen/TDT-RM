# Production Data Provider Recovery Report

## Executive summary

- The TDT-RM model, TCWRS, ETI, MHS, BCD, Tail Risk, CP formulas, ETF Exit model, and backtest logic were not changed.
- The existing production path is already official-source-first for TWSE cash-market data and TAIFEX derivatives/FX data, with FinMind disabled unless explicitly opted in.
- The safe implementation added one official FX fallback: CBC Statistical Database daily NTD/USD (`BP01D01en`) after TAIFEX and before vendor fallbacks.
- The safe implementation also added a GitHub Actions connectivity audit workflow that records DNS, HTTPS status, response status, rate-limit indicators, authentication observations, and production suitability for TWSE, TAIFEX, CBC, FinMind, and MOF.
- Current Codex runtime evidence shows both DNS resolution failures and HTTPS tunnel `403 Forbidden` failures for all audited public endpoints. This is treated as an environment limitation, not provider unsuitability.
- Public GitHub Actions pages currently show no prior workflow runs for the existing probe/production workflows; therefore a real GitHub-hosted runner result still must be produced by dispatching `Production Data Connectivity Audit` after this branch lands.

## Connectivity matrix

| Source | Codex DNS | Codex HTTPS | Codex status | Rate-limit behavior | Authentication requirement | Production suitability |
|---|---:|---:|---:|---|---|---|
| TWSE | Failed: temporary name-resolution failure | Failed: tunnel `403 Forbidden` | None | Not observable in Codex | None expected for public endpoints | Priority-1 official source when reachable from GitHub Actions |
| TAIFEX | Failed: temporary name-resolution failure | Failed: tunnel `403 Forbidden` | None | Not observable in Codex | None expected for public OpenAPI endpoints | Priority-2 official source when reachable from GitHub Actions |
| CBC | Failed: temporary name-resolution failure | Failed: tunnel `403 Forbidden` | None | Not observable in Codex | None expected for CBC Statistical Database API | Priority-3 official FX fallback when reachable from GitHub Actions |
| FinMind | Failed: temporary name-resolution failure | Failed: tunnel `403 Forbidden` | None | Not observable in Codex | Token optional for some public queries; production fallback remains token-gated | Priority-4 vendor fallback only |
| MOF | Failed: temporary name-resolution failure | Failed: tunnel `403 Forbidden` | None | Not observable in Codex | None expected for public web endpoint | Connectivity-only audit target; not currently a canonical TDT-RM market-data provider |

## Provider ranking table

| Rank | Provider | Reliability | Automation suitability | Long-term maintenance risk | GitHub Actions compatibility |
|---:|---|---|---|---|---|
| 1 | TWSE official | Highest for listed cash-market reports; authoritative source for TWSE data | Good: public JSON report endpoints are already configured | Medium: report schemas and anti-bot/WAF policies can change | Requires real runner audit; workflow added to verify |
| 2 | TAIFEX official | Highest for futures/options and public TAIFEX FX feed | Good: public OpenAPI endpoints are already configured | Low-to-medium: OpenAPI schemas can drift | Requires real runner audit; workflow added to verify |
| 3 | CBC official FX | Highest authority for NTD/USD daily FX history | Good: documented JSON API via `FileName=BP01D01en` | Low: stable statistical database item code, but JSON shape must be monitored | Requires real runner audit; workflow added to verify |
| 4 | FinMind fallback | Useful vendor aggregation, not official | Acceptable only as explicit token-gated fallback | Medium-to-high: vendor rate limits, token policy, and schema changes | Compatible only when `FINMIND_TOKEN` is configured and fallback is explicitly allowed |

## Production architecture recommendation

1. **Tier 1: Official sources.** Attempt official providers first by dataset: TWSE for price, foreign flow, breadth, and leadership; TAIFEX for futures/options and first FX; CBC as the official FX fallback.
2. **Tier 2: Vendor fallback.** Use FinMind only as an explicit, token-gated fallback, never silently. Record provider health and reconciliation results.
3. **Tier 3: Local emergency fallback.** Use only reproducible, pre-existing cached/provider artifacts for incident replay. Do not fabricate manual CSVs.
4. **Fail-closed validation.** Block the run on missing files, stale trade dates, forbidden source types, failed strict schema validation, failed reconciliation checks, or missing authentication for an explicitly enabled vendor fallback.
5. **GitHub Actions execution.** Run the new `Production Data Connectivity Audit` workflow before production fetch and inspect its artifact/step summary whenever a data-fetch failure occurs.

## GitHub Actions environment audit status

- Existing repository workflows for probe and daily production fetch have no public prior runs visible at audit time, so the failure cannot yet be classified as GitHub Actions-only or both with runner evidence.
- The new workflow is the smallest safe path to obtain real runner evidence without touching scoring/model/backtest logic.
- Required next step: dispatch `Production Data Connectivity Audit` on GitHub Actions and compare its artifact with the Codex-local blocked result.
