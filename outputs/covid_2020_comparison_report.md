# TDT-RM 2020 COVID Crash Backtest Comparison Report

## Run metadata

- Period: 2020 COVID crash
- Simulation: daily
- Framework: Same daily price-proxy COVID stress-test framework and V5.1.4 outcome annotations used by the 2022 bear-market backtest.
- V5.1.3 source CSV: `outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv`
- V5.1.4 source CSV: `outputs/covid_2020_backtest.csv`

## Headline comparison

| Metric | V5.1.3 Final Freeze | V5.1.4 Backtest Calibration Patch | Change |
| --- | ---: | ---: | ---: |
| Red signals | 12 | 0 | -12.00 |
| Orange signals | 0 | 0 | +0.00 |
| False positives | 2 | 0 | -2.00 |
| Maximum drawdown avoided | 24.74% | 0.00% | -24.74% |
| Average CP | 31.39 | 22.14 | -9.25 |
| Average CP during risk-off periods | 57.95 | n/a | n/a |

## Verification gates

| Gate | Result | Evidence |
| --- | --- | --- |
| maximum_drawdown_avoided_at_least_20_pct | FAIL | actual=0.0, threshold=20.0 |
| false_positives_reduced | PASS | v5_1_3=2, v5_1_4=0 |
| orange_signals_appear | FAIL | actual=0 |
| red_signals_reduced_vs_v5_1_3 | PASS | v5_1_3=12, v5_1_4=0 |

## Signal distribution

| Signal | V5.1.3 days | V5.1.4 days |
| --- | ---: | ---: |
| Green | 11 | 14 |
| Red | 12 | 0 |
| Strengthened Yellow | 17 | 24 |
| Yellow | 8 | 10 |

## First risk-off observations

| Model | Date | Signal | Close | TCWRS | ETI-5 | Tail Risk | BCD | CP | Forward 20D Max Drawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TDT-RM V5.1.3 Rev.3 Final Freeze | 2020-02-18 | Red | 11648.98 | 35 | 5 | 16.30 | 24.00 | 49.66 | -20.86% |
| TDT-RM V5.1.4 Backtest Calibration Patch | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Interpretation

- V5.1.4 reduced red signals and false positives versus V5.1.3 on this price-only COVID tape.
- V5.1.4 did not satisfy the 20% maximum-drawdown-avoided gate because no Red or Orange risk-off signal was emitted before the crash trough in the generated artifact.
- V5.1.4 also did not satisfy the orange-signal-appearance gate on this short February-April 2020 sample.
- Average CP is reported across all observations; average CP during risk-off periods is `n/a` when a model emits no Red/Orange observations.
