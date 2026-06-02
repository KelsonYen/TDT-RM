# V5.1.4+CAL Final Assessment Report

## Report metadata

- Report path: `outputs/v5_1_4_cal_final_assessment_report.md`
- Artifact discovery: automatic scan of the outputs directory for V5.1.3, V5.1.4, and V5.1.4+CAL CSV/JSON artifacts.
- CAL discovery rule: any output CSV/JSON with a `cal` token anywhere in the file name is considered a CAL artifact candidate.

## Requested artifact pattern inventory

| Pattern | Matching files |
| --- | --- |
| `cal.csv` | None found |
| `cal.json` | None found |
| `2024.csv` | None found |
| `2026.csv` | None found |

## Discovered assessment artifacts

| Scenario | Model | Type | File |
| --- | --- | --- | --- |
| 2020 COVID | V5.1.3 | csv | `outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv` |
| 2020 COVID | V5.1.3 | json | `outputs/tdt_rm_v5_1_3_2020_covid_crash_summary.json` |
| 2020 COVID | V5.1.4 | csv | `outputs/covid_2020_backtest.csv` |
| 2020 COVID | V5.1.4 | json | `outputs/covid_2020_summary.json` |
| 2020 COVID | V5.1.4 | csv | `outputs/tdt_rm_v5_1_4_2020_covid_crash_stress.csv` |
| 2020 COVID | V5.1.4 | json | `outputs/tdt_rm_v5_1_4_2020_covid_crash_summary.json` |
| 2022 Bear Market | V5.1.3 | csv | `outputs/tdt_rm_v5_1_3_2022_bear_market_backtest.csv` |
| 2022 Bear Market | V5.1.3 | json | `outputs/tdt_rm_v5_1_3_2022_bear_market_summary.json` |
| 2022 Bear Market | V5.1.3 | json | `outputs/tdt_rm_v5_1_3_2022_performance_report.json` |
| 2022 Bear Market | V5.1.4 | csv | `outputs/tdt_rm_v5_1_4_2022_bear_market_backtest.csv` |
| 2022 Bear Market | V5.1.4 | json | `outputs/tdt_rm_v5_1_4_2022_bear_market_summary.json` |
| 2022 Bear Market | V5.1.4 | json | `outputs/tdt_rm_v5_1_4_2022_bear_market_validation.json` |

## V5.1.4+CAL expected coverage

| Scenario | Model | Expected CSV | Status |
| --- | --- | --- | --- |
| 2020 COVID | V5.1.4+CAL | `tdt_rm_v5_1_4_cal_2020_covid_crash_stress.csv` | Missing |
| 2022 Bear Market | V5.1.4+CAL | `tdt_rm_v5_1_4_cal_2022_bear_market_backtest.csv` | Missing |
| 2024 AI/semiconductor selloff | V5.1.4+CAL | `tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv` | Missing |
| 2026 overheating regime | V5.1.4+CAL | `tdt_rm_v5_1_4_cal_2026_overheating_stress.csv` | Missing |

## Missing expected V5.1.4+CAL artifacts

- `tdt_rm_v5_1_4_cal_2020_covid_crash_stress.csv`
- `tdt_rm_v5_1_4_cal_2020_covid_crash_summary.json`
- `tdt_rm_v5_1_4_cal_2022_bear_market_backtest.csv`
- `tdt_rm_v5_1_4_cal_2022_bear_market_summary.json`
- `tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv`
- `tdt_rm_v5_1_4_cal_2024_ai_selloff_summary.json`
- `tdt_rm_v5_1_4_cal_2026_overheating_stress.csv`
- `tdt_rm_v5_1_4_cal_2026_overheating_summary.json`

## Assessment summary

| Scenario | Model | Observations | Window | Red | Orange | False positives | Max drawdown avoided | Average CP | Source CSV |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2020 COVID | V5.1.3 | 48 | 2020-02-03 to 2020-04-13 | 12 | 0 | 2 | 24.74% | 31.39 | `outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv` |
| 2020 COVID | V5.1.4 | 48 | 2020-02-03 to 2020-04-13 | 0 | 0 | 0 | 0.00% | 22.14 | `outputs/covid_2020_backtest.csv` |
| 2020 COVID | V5.1.4 | 48 | 2020-02-03 to 2020-04-13 | 0 | 0 | 0 | 0.00% | 22.14 | `outputs/tdt_rm_v5_1_4_2020_covid_crash_stress.csv` |
| 2022 Bear Market | V5.1.3 | 247 | 2022-01-03 to 2022-12-30 | 57 | 0 | 30 | 13.07% | 33.06 | `outputs/tdt_rm_v5_1_3_2022_bear_market_backtest.csv` |
| 2022 Bear Market | V5.1.4 | 247 | 2022-01-03 to 2022-12-30 | 0 | 150 | 40 | 19.17% | 24.05 | `outputs/tdt_rm_v5_1_4_2022_bear_market_backtest.csv` |

## Signal distributions

| Scenario | Model | Signal distribution |
| --- | --- | --- |
| 2020 COVID | V5.1.3 | Green: 11, Red: 12, Strengthened Yellow: 17, Yellow: 8 |
| 2020 COVID | V5.1.4 | Green: 14, Strengthened Yellow: 24, Yellow: 10 |
| 2020 COVID | V5.1.4 | Green: 14, Strengthened Yellow: 24, Yellow: 10 |
| 2022 Bear Market | V5.1.3 | Green: 28, Red: 57, Strengthened Yellow: 91, Yellow: 71 |
| 2022 Bear Market | V5.1.4 | Green: 18, Orange: 150, Strengthened Yellow: 36, Yellow: 43 |

## Interpretation

- The report includes every discovered V5.1.3, V5.1.4, and V5.1.4+CAL CSV artifact instead of relying on hard-coded final-assessment file names.
- If CAL artifacts are missing, the missing-file section lists exact expected names rather than using a blanket absence statement.
- 2024 AI/semiconductor selloff and 2026 overheating regime rows appear automatically when matching CSV artifacts exist in outputs.
