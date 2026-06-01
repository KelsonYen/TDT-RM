# TDT-RM 2022 Bear Market Backtest Report

## Run metadata

- Model: TDT-RM V5.1.3 Rev.3 Final Freeze
- Simulation: daily
- Period: 2022 bear market
- Observations: 247
- Source CSV: `outputs/tdt_rm_v5_1_3_2022_bear_market_backtest.csv`
- Source summary: `outputs/tdt_rm_v5_1_3_2022_bear_market_summary.json`

## Signal summary

| Metric | Value |
| --- | ---: |
| Red signals | 57 |
| Orange signals | 0 |
| False positives | 30 |
| Maximum drawdown avoided | 13.07% |
| Average CP | 33.06 |
| Average CP on risk-off days | 54.47 |

## First risk-off observation

| Date | Signal | Close | TCWRS | ETI-5 | Tail Risk | BCD | CP | Forward 20D Max Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-01-19 | Red | 18227.46 | 28 | 5 | 14.48 | 24.00 | 46.50 | -3.47% |

## Signal distribution

| Signal | Days |
| --- | ---: |
| Green | 28 |
| Red | 57 |
| Strengthened Yellow | 91 |
| Yellow | 71 |

## Worst forward 20-day drawdown observations

| Date | Signal | Close | CP | Forward 20D Max Drawdown | False Positive | Drawdown Avoided |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 2022-06-08 | Green | 16670.51 | 13.01 | -16.11% | False | 0.00% |
| 2022-06-09 | Green | 16621.34 | 14.80 | -15.86% | False | 0.00% |
| 2022-06-10 | Strengthened Yellow | 16460.12 | 35.18 | -15.03% | False | 0.00% |
| 2022-06-06 | Green | 16605.96 | 13.26 | -14.39% | False | 0.00% |
| 2022-06-07 | Green | 16512.88 | 15.21 | -13.90% | False | 0.00% |

## Notes

- Red and Orange observations are treated as risk-off signals in the outcome annotations.
- Forward drawdown statistics are computed from the next 20 available observations in the generated CSV.
- Inputs unavailable from the embedded public close tape are conservative price-derived proxies from the executable backtest scripts.
