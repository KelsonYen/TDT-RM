# TDT-RM 2020 COVID Crash Stress Test Report

## Run metadata

- Model: TDT-RM V5.1.3 Rev.3 Final Freeze
- Simulation: daily
- Period: 2020 COVID crash
- Observations: 48
- Source CSV: `outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv`
- Source summary: `outputs/tdt_rm_v5_1_3_2020_covid_crash_summary.json`

## Signal summary

| Metric | Value |
| --- | ---: |
| Red signals | 12 |
| Orange signals | 0 |
| False positives | 2 |
| Maximum drawdown avoided | 24.74% |
| Average CP | 31.39 |
| Average CP on risk-off days | 57.95 |
| First red signal | 2020-02-18 |
| First orange signal | n/a |

## First risk-off observation

| Date | Signal | Close | TCWRS | ETI-5 | Tail Risk | BCD | CP | Forward 20D Max Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020-02-18 | Red | 11648.98 | 35 | 5 | 16.30 | 24.00 | 49.66 | -20.86% |

## Signal distribution

| Signal | Days |
| --- | ---: |
| Green | 11 |
| Red | 12 |
| Strengthened Yellow | 17 |
| Yellow | 8 |

## Worst forward 20-day drawdown observations

| Date | Signal | Close | CP | Forward 20D Max Drawdown | False Positive | Drawdown Avoided |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 2020-02-19 | Green | 11758.84 | 3.89 | -26.17% | False | 0.00% |
| 2020-02-20 | Green | 11725.09 | 7.52 | -25.96% | False | 0.00% |
| 2020-02-21 | Yellow | 11686.35 | 14.66 | -25.71% | False | 0.00% |
| 2020-02-25 | Strengthened Yellow | 11540.23 | 31.40 | -24.77% | False | 0.00% |
| 2020-02-24 | Red | 11534.87 | 50.85 | -24.74% | False | 24.74% |

## Notes

- Red and Orange observations are treated as risk-off signals in the outcome annotations.
- Forward drawdown statistics are computed from the next 20 available observations in the generated CSV.
- Inputs unavailable from the embedded public close tape are conservative price-derived proxies from the executable backtest scripts.
