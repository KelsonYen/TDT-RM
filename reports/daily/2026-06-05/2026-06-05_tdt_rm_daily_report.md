# TDT-RM Final Operator Report — 2026-06-05

## Production Status

* Trade Date: 2026-06-05
* Latest Bar Date: 2026-06-05
* Pipeline Validation Status: passed
* Data Status: enriched_snapshot
* Source Production Artifact: outputs/daily/2026-06-05/tdt_rm_daily_2026-06-05.json
* Source Manifest: outputs/daily/2026-06-05/tdt_rm_daily_2026-06-05_manifest.json

## Required Operator Fields

| Field | Value |
| --- | --- |
| Signal | Yellow |
| Regime State | watch |
| TCWRS | 12 |
| MHS | 100.0 |
| ETI-5 | 1 |
| Tail Risk | 53.95 |
| BCD | 53.95 |
| Crash Probability | 26.98% |
| Exposure Limit | 60-80% |
| Recommended Action | Hold. Do not chase. Do not use leverage. |
| Conclusion | TDT-RM closes the latest available market date with a Yellow signal and crash probability 26.98%. The operator should follow the recommended action within the approved 60-80% equity exposure band. |

## Data Quality Notes

* Available ETI Components: ETI-1, ETI-2, ETI-3, ETI-4, ETI-5
* Fallback Proxies: {}
* Provider Warnings: field conflict for index_5d_return_pct: kept/updated between taiex_price=0.7555953174551044 and margin_csv=0.0; kept taiex_price by precedence rule
* Validation Errors: 0
* Validation Warnings: 0

## Final Assessment

TDT-RM closes the latest available market date with a Yellow signal and crash probability 26.98%. The operator should follow the recommended action within the approved 60-80% equity exposure band.
