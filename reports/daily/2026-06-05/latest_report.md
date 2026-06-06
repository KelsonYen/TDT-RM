# TDT-RM Final Operator Report — 2026-06-05

## Production Status

* Trade Date: 2026-06-05
* Latest Bar Date: 2026-06-05
* Pipeline Validation Status: passed
* Data Status: enriched_snapshot
* Production Report Quality: PASS
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

## Operator Disclosure

* Production Report Quality: `PASS`
* Acceptable for Real-World Daily Use: `YES`

### Blocking Quality Failures
* No blocking quality-control reasons detected.

### Non-Blocking Module Warnings
* module=ETF Exit; status=not_integrated; notes=Reserved for future ETF Exit integration; no ETF exit logic applied.

### Data-Source Warnings
#### Fallback Provider Datasets
* none reported

#### Fallback-Dependent Operator Fields
* none reported

#### Placeholder / Default-Like Fields
* none reported

### Official Provider Datasets
* source_id=breadth_csv; provider_source=TWSE_OFFICIAL:twse_mi_index_breadth; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/breadth.csv
* source_id=foreign_flow_csv; provider_source=TWSE_OFFICIAL:twse_t86_foreign_flow; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/foreign_flow.csv
* source_id=futures_csv; provider_source=TAIFEX_OFFICIAL:taifex_txf_futures; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/futures.csv
* source_id=fx_csv; provider_source=TAIFEX_OFFICIAL:taifex_daily_fx; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/fx.csv
* source_id=leadership_csv; provider_source=TWSE_OFFICIAL:twse_main7_leadership; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/leadership.csv
* source_id=margin_csv; provider_source=TWSE_OFFICIAL:twse_margin; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/margin.csv
* source_id=options_csv; provider_source=FINMIND_FALLBACK:TaiwanOptionDaily:TXO; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/options.csv
* source_id=taiex_price; provider_source=TWSE_OFFICIAL:twse_fmtqik_price; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/price.csv

## Data Quality Notes

* Available ETI Components: ETI-1, ETI-2, ETI-3, ETI-4, ETI-5
* Fallback Proxies: {}
* Provider Warnings: field conflict for index_5d_return_pct: kept/updated between taiex_price=0.7555953174551044 and margin_csv=0.0; kept taiex_price by precedence rule
* Validation Errors: 0
* Validation Warnings: 0

## Final Assessment

TDT-RM closes the latest available market date with a Yellow signal and crash probability 26.98%. The operator should follow the recommended action within the approved 60-80% equity exposure band.
