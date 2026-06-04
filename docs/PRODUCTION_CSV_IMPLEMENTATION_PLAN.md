# Production CSV Automation Implementation Plan

_Audit date: 2026-06-04. Scope: production CSV generation only. This plan does not change TDT-RM scoring logic, light logic, V5.1.3/V5.1.4 rules, or CAL model rules._

## Audit summary from PR #56 gap report

The production CSV gap report is `docs/PRODUCTION_GAP_REPORT.md`. It confirms that all eight strict daily CSVs have schemas and some public-provider parsing coverage, but none were fully production-ready because strict local/import CSV output, provenance fields, lookback-derived fields, and network assumptions were incomplete.

| Priority | CSV | Schema exists | Local ingestion exists | Fetcher/provider exists | Auto-output status after this PR | Manual/imported input still needed | Primary blocker |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `price.csv` | Yes | Yes | Yes: TWSE FMTQIK, TWSE MI_5MINS_HIST, local fallback | Minimum viable strict auto-output implemented for price | Local fallback still operator-supplied when live source fails | Network reachability and real fallback availability |
| 2 | `foreign_flow.csv` | Yes | Yes | Yes: TWSE T86 | Not strict production-ready | Yes | Numeric sell mapping, multi-day lookback, provenance writer |
| 3 | `fx.csv` | Yes | Yes | Yes: TAIFEX FX | Not strict production-ready | Yes | Strict provenance writer and holiday handling |
| 4 | `breadth.csv` | Yes | Yes | Yes: TWSE MI_INDEX | Not strict production-ready | Yes | Multi-day breadth history and strict provenance writer |
| 5 | `futures.csv` | Yes | Yes | Raw TAIFEX futures source exists | Not strict production-ready | Yes | Decision-field definitions and source mapping for net-short/hedging |
| 6 | `options.csv` | Yes | Yes | Raw TAIFEX PCR/VIX source exists | Not strict production-ready | Yes | PCR/VIX thresholds and formal Tail Risk/BCD provenance |
| 7 | `leadership.csv` | Yes | Yes | Main-7 STOCK_DAY source exists | Not strict production-ready | Yes | MHS source/algorithm and per-symbol history completeness |

## Implementation plan

### 1. `price.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `close`, `ma5`, `ma20`, `ma60`, `ma20_slope`, `one_day_return_pct`, `two_day_return_pct`, `close_below_ma20_consecutive_days`, `index_5d_return_pct`, `return_60d_pct`, `previous_ma60`, `turnover_amount`.
- **Candidate public data source**: TWSE `FMTQIK` monthly market summary.
- **Fallback source**: TWSE `MI_5MINS_HIST`; operator-supplied local price CSV fallback only after public source failure or explicit offline mode.
- **Expected transformation**: derive MA5/20/60, MA20 slope, 1D/2D/5D/60D returns, previous MA60, close-below-MA20 streak, and latest turnover from at least 61 trading-day bars; write strict column names and provenance.
- **Validation rule**: fail closed unless all required fields are present, numeric fields parse, the row date equals `--as-of`, and manifest validation passes.
- **Output path**: `--output-dir/price.csv` from `scripts/fetch_daily_provider_csvs.py`.
- **Failure behavior**: do not write `price.csv`; mark `data_status=price_unavailable`; preserve 403/DNS/file errors in `fetch_manifest.json` and `provider_health.json`.
- **Test plan**: success from fixture, public failure to local fallback, missing fallback fail-closed, strict field failure, manifest/provenance validation.

### 2. `foreign_flow.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `foreign_spot_net_buy`, `foreign_spot_net_sell`, `foreign_spot_net_sell_consecutive_days`, `foreign_spot_large_sell`, `foreign_large_sell`.
- **Candidate public data source**: TWSE `T86` institutional flow report.
- **Fallback source**: operator-imported T86-derived CSV from a controlled environment.
- **Expected transformation**: aggregate foreign investor net buy/sell by trade date, convert sell amount to numeric, compute consecutive sell days from lookback history, and derive large-sell booleans.
- **Validation rule**: fail if buy/sell amounts are non-numeric, lookback is insufficient for consecutive days, or provenance fields are missing.
- **Output path**: `inputs/daily/YYYY-MM-DD/foreign_flow.csv` or provider output dir.
- **Failure behavior**: block full production when absent unless an explicit partial diagnostic run is requested.
- **Test plan**: T86 parser fixtures, negative/positive net flow unit tests, multi-day consecutive-sell fixtures, strict CSV validator.

### 3. `fx.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `usd_twd_3d_change_pct`, `usd_twd_5d_change_pct`, `twd_appreciates`, `twd_stable`, `twd_depreciates_significantly`.
- **Candidate public data source**: TAIFEX `DailyForeignExchangeRates` OpenAPI.
- **Fallback source**: another official/public USD/TWD close source, or operator-imported controlled CSV.
- **Expected transformation**: select USD/TWD series, calculate 3D/5D percentage moves, and derive appreciation/stability/depreciation booleans.
- **Validation rule**: require sufficient lookback and explicit holiday handling; fail on blank provenance or stale date.
- **Output path**: `inputs/daily/YYYY-MM-DD/fx.csv` or provider output dir.
- **Failure behavior**: no silent neutral FX row; record endpoint/network errors.
- **Test plan**: TAIFEX fixture, holiday/no-row fixture, stale-source fixture, strict validator.

### 4. `breadth.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `index_down`, `advancing_issues`, `declining_issues`, `declining_issues_significantly_expand`, `declining_issues_significantly_gt_advancing`, `declining_gt_advancing_consecutive_days`, `breadth_weakens_for_2_days`.
- **Candidate public data source**: TWSE `MI_INDEX` after-trading market report.
- **Fallback source**: operator-imported TWSE breadth CSV from controlled environment.
- **Expected transformation**: parse advancing/declining issues, derive index-down and significant-decline booleans, and compute two-day weakening/lookback counters.
- **Validation rule**: fail when issue counts are missing/non-numeric or lookback is insufficient for history-derived fields.
- **Output path**: `inputs/daily/YYYY-MM-DD/breadth.csv` or provider output dir.
- **Failure behavior**: mark breadth unavailable; do not fabricate breadth booleans.
- **Test plan**: MI_INDEX parser regression fixtures, multi-day lookback tests, strict validator.

### 5. `futures.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `futures_hedging_increases`, `futures_hedging_significant`, `futures_net_short_increases`, `futures_net_short_decreases`.
- **Candidate public data source**: TAIFEX futures daily reports plus the official institutional/large-trader table that defines net-short/hedging exposure.
- **Fallback source**: operator-imported TAIFEX-derived strict CSV.
- **Expected transformation**: map official futures positioning data into four strict booleans using approved thresholds.
- **Validation rule**: fail until source table and thresholds are explicitly specified; raw TXF close/OI alone is insufficient.
- **Output path**: `inputs/daily/YYYY-MM-DD/futures.csv` or provider output dir.
- **Failure behavior**: block strict full production rather than infer signals from unrelated raw fields.
- **Test plan**: source-selection fixture, threshold boundary tests, provenance tests.

### 6. `options.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `pcr_stable`, `pcr_rises`, `vix_stable`, `vix_rises`, `tail_risk`, `bcd`.
- **Candidate public data source**: TAIFEX `PutCallRatio` and `TAIFEXVIX`.
- **Fallback source**: formal Tail Risk/BCD provider CSV, or operator-imported controlled CSV.
- **Expected transformation**: calculate PCR/VIX direction/stability from lookback and ingest formal Tail Risk/BCD scores with provenance.
- **Validation rule**: fail if formal/provisional score status is not explicit or PCR/VIX thresholds are unspecified.
- **Output path**: `inputs/daily/YYYY-MM-DD/options.csv` or provider output dir.
- **Failure behavior**: do not use mock Tail Risk/BCD as production provider data.
- **Test plan**: PCR/VIX fixtures, formal-score provenance fixture, strict validator, no-mock score tests.

### 7. `leadership.csv`

- **Required schema**: `trade_date`, `provider_source`, `source_type`, `count_main_7_below_ma20`, `count_main_7_below_ma60`, `majority_main_7_assets_above_ma20`, `main_7_symbols`, `main_7_below_ma20_symbols`, `mhs`.
- **Candidate public data source**: TWSE `STOCK_DAY` per configured Main-7 constituent.
- **Fallback source**: operator-imported Main-7/MHS CSV with symbol-list version noted.
- **Expected transformation**: derive per-symbol MA20/MA60 status, aggregate counts, and ingest/compute MHS from an approved source/algorithm.
- **Validation rule**: fail when any required constituent lacks sufficient history unless a documented suspension/missing-data policy applies.
- **Output path**: `inputs/daily/YYYY-MM-DD/leadership.csv` or provider output dir.
- **Failure behavior**: keep ETI-5 unavailable rather than generate neutral leadership or MHS values.
- **Test plan**: per-symbol fixtures, missing constituent fixture, symbol-config version tests, strict validator.
