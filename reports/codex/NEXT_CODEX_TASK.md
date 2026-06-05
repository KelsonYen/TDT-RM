# Next Codex Task

## Goal

Eliminate the production-fetch blocker without changing any TDT-RM, ETF, scoring, signal, CP, CAL, report-generation, validation-rule, or backtest logic.

## Required next task

Build a provider-acquisition fix for GitHub Actions: either make official/public endpoint connectivity succeed from the runner, or add an explicitly opted-in authenticated production provider path with repository secrets. The current failing layer is acquisition, not parsing or model logic.

## Acceptance criteria

1. Run `Daily Production Data Fetch` for `trade_date=2026-06-03` on GitHub Actions.
2. Confirm all seven audited datasets produce strict CSVs: `price.csv`, `foreign_flow.csv`, `breadth.csv`, `futures.csv`, `options.csv`, `fx.csv`, and `leadership.csv`.
3. Confirm `reports/daily/2026-06-03/artifacts/production_fetch_summary.json` has `overall_status=READY` and no missing audited datasets.
4. Confirm provider health records at least one selected healthy provider per audited dataset with non-null `output_path`.
5. Keep all scoring/model/report/validation/backtest logic untouched; limit changes to provider acquisition/configuration/workflow secrets handling if changes are required.

## Investigation checklist

- Inspect GitHub Actions networking/proxy behavior for `www.twse.com.tw`, `openapi.taifex.com.tw`, `cpx.cbc.gov.tw`, Yahoo, and Stooq.
- If using FinMind fallback, dispatch with `allow_finmind=true` and ensure `FINMIND_TOKEN` or `FINMIND_API_TOKEN` exists; do not enable it silently for scheduled runs unless that is an explicit production policy decision.
- Preserve fail-closed behavior: no fabricated data, no sample CSVs, and no local fallback as production success.

## Evidence summary

- Official/public endpoint attempts returned `Tunnel connection failed: 403 Forbidden` before payload parsing.
- FinMind fallback was skipped because `allow_finmind=false` and no token was present.
- Output CSV generation did not occur in the strict production fetch path because no dataset had a selected healthy provider.
