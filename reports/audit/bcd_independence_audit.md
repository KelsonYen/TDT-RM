# BCD Independence Audit

Trade date: 2026-06-05
Calculation version: BCD-INDEPENDENT-V1
BCD Status: INCOMPLETE
Completeness score: 0.1429
Missing Inputs: ["main7_returns", "main7_weights", "main7_concentration", "sector_breadth", "sector_diffusion", "otc_return_pct", "small_mid_breadth", "small_mid_weakness", "turnover_concentration_topn", "turnover_concentration"]

## Input sources
- advancing_issues: breadth_csv
- breadth_history: bcd_feature_builder
- breadth_weakens_for_2_days: breadth_csv
- close: taiex_price
- close_below_ma20_consecutive_days: taiex_price
- count_main_7_below_ma20: leadership_csv
- count_main_7_below_ma60: leadership_csv
- declining_gt_advancing_consecutive_days: breadth_csv
- declining_issues: breadth_csv
- declining_issues_significantly_expand: breadth_csv
- declining_issues_significantly_gt_advancing: breadth_csv
- foreign_large_sell: foreign_flow_csv
- foreign_spot_large_sell: foreign_flow_csv
- foreign_spot_net_buy: foreign_flow_csv
- foreign_spot_net_sell: foreign_flow_csv
- foreign_spot_net_sell_consecutive_days: foreign_flow_csv
- futures_hedging_increases: futures_csv
- futures_hedging_significant: futures_csv
- futures_net_short_decreases: futures_csv
- futures_net_short_increases: futures_csv
- hot_stock_margin_fast_increase: margin_csv
- index_5d_return_pct: taiex_price
- index_down: breadth_csv
- ma20: taiex_price
- ma20_slope: taiex_price
- ma5: taiex_price
- ma60: taiex_price
- main7_closes: leadership_csv
- main7_previous_closes: leadership_csv
- main7_turnover_amounts: leadership_csv
- main_7_symbols: leadership_csv
- majority_main_7_assets_above_ma20: leadership_csv
- margin_balance_5d_decline_pct: margin_csv
- margin_balance_5d_flat_or_down: margin_csv
- margin_balance_5d_increases: margin_csv
- margin_not_retreating: margin_csv
- mhs: leadership_csv
- observed_at: margin_csv
- one_day_return_pct: taiex_price
- pcr_rises: options_csv
- pcr_stable: options_csv
- previous_ma60: taiex_price
- return_60d_pct: taiex_price
- taiex_return_pct: taiex_price
- tail_risk: options_csv
- turnover_amount: taiex_price
- twd_appreciates: fx_csv
- twd_depreciates_significantly: fx_csv
- twd_stable: fx_csv
- two_day_return_pct: taiex_price
- usd_twd_3d_change_pct: fx_csv
- usd_twd_5d_change_pct: fx_csv
- vix_rises: options_csv
- vix_stable: options_csv

## Calculation path
- `src/tdt_rm/daily_runner.py::build_daily_payload_from_snapshot` calls `_bcd_result_from_snapshot` and writes BCD payload/audit fields.
- `src/tdt_rm/daily_runner.py::_bcd_result_from_snapshot` maps independent snapshot breadth, leadership, sector, OTC/small-mid, and turnover fields into `BCDInput`.
- `src/tdt_rm/bcd.py::score_bcd` validates completeness and returns `final_score=None` unless all required independent inputs are present.

## Dependency graph
```
breadth_history ─┐
main7_returns ──┤
main7_weights ──┤
sector_diffusion ├─> BCDInput -> score_bcd -> bcd
otc_return_pct ─┤
small_mid_breadth ─┤
turnover_concentration_topn ─┘
tail_risk ─X (forbidden dependency)
options_csv.bcd ─X (forbidden dependency)
```

## Source dependencies
- advancing_issues<-breadth_csv
- declining_issues<-breadth_csv
- breadth_history<-bcd_feature_builder
- taiex_return_pct<-taiex_price

## Comparison against tail_risk
- Tail Risk: 53.95
- BCD: None
- not comparable (BCD incomplete/null)
