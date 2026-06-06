# BCD Independence Audit

Trade date: 2026-05-29
Calculation version: BCD-INDEPENDENT-V1
BCD Status: INCOMPLETE
Completeness score: 0.0
Missing Inputs: ["advancing_declining_issues", "index_breadth_divergence", "main7_returns", "main7_weights", "main7_concentration", "sector_breadth", "sector_diffusion", "otc_return_pct", "small_mid_breadth", "small_mid_weakness", "turnover_concentration_topn", "turnover_concentration", "breadth_history"]

## Input sources
- close: taiex_price
- close_below_ma20_consecutive_days: taiex_price
- index_5d_return_pct: taiex_price
- ma20: taiex_price
- ma20_slope: taiex_price
- ma5: taiex_price
- ma60: taiex_price
- observed_at: taiex_price
- one_day_return_pct: taiex_price
- previous_ma60: taiex_price
- return_60d_pct: taiex_price
- taiex_return_pct: taiex_price
- turnover_amount: taiex_price
- two_day_return_pct: taiex_price

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
- taiex_return_pct<-taiex_price

## Comparison against tail_risk
- Tail Risk: 0.9
- BCD: None
- not comparable (BCD incomplete/null)
