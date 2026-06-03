# TDT-RM Final Operator Report — 2026-06-02

## Production Status

* Trade Date: 2026-06-02
* Latest Bar Date: 2026-06-02
* Pipeline Validation Status: passed
* Data Status: enriched_snapshot
* Source Production Artifact: outputs/daily/tdt_rm_daily_2026-06-02.json
* Source Manifest: outputs/daily/tdt_rm_daily_2026-06-02_manifest.json

## Required Operator Fields

| Field | Value |
| --- | --- |
| Signal | Green |
| Regime State | watch |
| TCWRS | 0 |
| MHS | 0.0 |
| ETI-5 | 0 |
| Tail Risk | 1.08 |
| BCD | 0.0 |
| Crash Probability | 0.22 (22.0%) |
| Exposure Limit | 80-100% |
| Recommended Action | Operate within the approved exposure limit (80-100%); no leverage beyond policy. |
| Conclusion | TDT-RM closes the latest available market date with a Green signal and crash probability 0.22 (22.0%). The operator should follow the recommended action within the approved 80-100% equity exposure band. |

## Data Quality Notes

* Available ETI Components: ETI-1
* Fallback Proxies: {"bcd": {"reason": "formal bcd absent from daily snapshot", "status": "price_only_proxy"}, "tail_risk": {"reason": "formal tail_risk absent from daily snapshot", "status": "price_only_proxy"}}
* Provider Warnings: none
* Validation Errors: 0
* Validation Warnings: 0

## Final Assessment

TDT-RM closes the latest available market date with a Green signal and crash probability 0.22 (22.0%). The operator should follow the recommended action within the approved 80-100% equity exposure band.
