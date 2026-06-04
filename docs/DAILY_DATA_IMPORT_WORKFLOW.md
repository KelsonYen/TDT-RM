# Daily External Data Import Workflow

Codex Cloud must not fetch TWSE or TAIFEX data directly. Daily production can run in **local/import data mode** by consuming committed CSV inputs under `inputs/daily/YYYY-MM-DD/`.

## Required command flow

```bash
python scripts/validate_daily_input_csvs.py \
  --trade-date 2026-06-03 \
  --input-dir inputs/daily/2026-06-03
```

```bash
python scripts/run_daily_production_pipeline.py \
  --trade-date 2026-06-03 \
  --input-dir inputs/daily/2026-06-03 \
  --reports-dir reports/daily/2026-06-03
```

The production runner validates local CSVs first. If any required CSV is missing, empty, dated incorrectly, missing `provider_source`, or marked with `source_type` of `fallback`, `mock`, or `fixture`, it fails closed and does not write a normal report.

## Operator workflow

1. Fetch TWSE, TAIFEX, FX, breadth, and leadership data outside Codex Cloud using an operator workstation, vendor terminal, browser download, or other approved network environment.
2. Convert each source to the eight CSV files listed below. Start from the templates in `inputs/templates/daily_csv_schema/`.
3. Record the actual upstream source in `provider_source` for every row, for example `TWSE_official_manual_import` or `TAIFEX_options_manual_import`.
4. Set `source_type` to a real non-fixture source label such as `official_manual`, `vendor_manual`, or `operator_verified`. Do **not** use `fallback`, `mock`, or `fixture`.
5. Place the files under `inputs/daily/YYYY-MM-DD/`.
6. Run the validator command.
7. Run the production command. With `--input-dir`, TDT-RM uses local CSV inputs only and does not call TWSE or TAIFEX live providers.
8. Review the terminal market-result block and the generated `reports/latest_report.md` plus the dated report under `reports/daily/YYYY-MM-DD/`.

## Required files

Local/import mode requires exactly these daily input files:

- `price.csv`
- `foreign_flow.csv`
- `fx.csv`
- `breadth.csv`
- `futures.csv`
- `options.csv`
- `leadership.csv`
- `margin.csv`

## CSV schema specification

All CSVs must contain at least one data row. Every row must have `trade_date` equal to the target date, a non-empty `provider_source`, and a non-forbidden `source_type`.

### `price.csv`

| Column | Type | Required | Validation |
| --- | --- | --- | --- |
| `trade_date` | date `YYYY-MM-DD` | yes | Must match `--trade-date`. |
| `provider_source` | string | yes | Must identify the upstream source. |
| `source_type` | string | yes | Cannot be `fallback`, `mock`, or `fixture`. |
| `close` | number | yes | Parseable as float. |
| `ma5` | number | yes | Parseable as float. |
| `ma20` | number | yes | Parseable as float. |
| `ma60` | number | yes | Parseable as float. |
| `ma20_slope` | number | yes | Parseable as float. |
| `one_day_return_pct` | number | yes | Parseable as float. |
| `two_day_return_pct` | number | yes | Parseable as float. |
| `close_below_ma20_consecutive_days` | integer | yes | Parseable as number. |
| `index_5d_return_pct` | number | yes | Parseable as float. |
| `return_60d_pct` | number | yes | Parseable as float. |
| `previous_ma60` | number | yes | Parseable as float. |
| `turnover_amount` | number | yes | Parseable as float. |

Example row: see `inputs/templates/daily_csv_schema/price.csv`.

### `foreign_flow.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `foreign_spot_net_buy`, `foreign_spot_net_sell`, `foreign_spot_net_sell_consecutive_days`, `foreign_spot_large_sell`, `foreign_large_sell`.

Numeric fields: `foreign_spot_net_buy`, `foreign_spot_net_sell`, `foreign_spot_net_sell_consecutive_days`. Boolean fields: `foreign_spot_large_sell`, `foreign_large_sell`.

Example row: see `inputs/templates/daily_csv_schema/foreign_flow.csv`.

### `fx.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `usd_twd_3d_change_pct`, `usd_twd_5d_change_pct`, `twd_appreciates`, `twd_stable`, `twd_depreciates_significantly`.

Numeric fields: `usd_twd_3d_change_pct`, `usd_twd_5d_change_pct`. Boolean fields: `twd_appreciates`, `twd_stable`, `twd_depreciates_significantly`.

Example row: see `inputs/templates/daily_csv_schema/fx.csv`.

### `breadth.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `index_down`, `advancing_issues`, `declining_issues`, `declining_issues_significantly_expand`, `declining_issues_significantly_gt_advancing`, `declining_gt_advancing_consecutive_days`, `breadth_weakens_for_2_days`.

Numeric fields: `advancing_issues`, `declining_issues`, `declining_gt_advancing_consecutive_days`. Boolean fields: `index_down`, `declining_issues_significantly_expand`, `declining_issues_significantly_gt_advancing`, `breadth_weakens_for_2_days`.

Example row: see `inputs/templates/daily_csv_schema/breadth.csv`.

### `futures.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `futures_hedging_increases`, `futures_hedging_significant`, `futures_net_short_increases`, `futures_net_short_decreases`.

Boolean fields: `futures_hedging_increases`, `futures_hedging_significant`, `futures_net_short_increases`, `futures_net_short_decreases`.

Example row: see `inputs/templates/daily_csv_schema/futures.csv`.

### `options.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `pcr_stable`, `pcr_rises`, `vix_stable`, `vix_rises`, `tail_risk`, `bcd`.

Numeric fields: `tail_risk`, `bcd`. Boolean fields: `pcr_stable`, `pcr_rises`, `vix_stable`, `vix_rises`.

Example row: see `inputs/templates/daily_csv_schema/options.csv`.

### `leadership.csv`

Required columns: `trade_date`, `provider_source`, `source_type`, `count_main_7_below_ma20`, `count_main_7_below_ma60`, `majority_main_7_assets_above_ma20`, `main_7_symbols`, `main_7_below_ma20_symbols`, `mhs`.

Numeric fields: `count_main_7_below_ma20`, `count_main_7_below_ma60`, `mhs`. Boolean field: `majority_main_7_assets_above_ma20`.

Example row: see `inputs/templates/daily_csv_schema/leadership.csv`.
