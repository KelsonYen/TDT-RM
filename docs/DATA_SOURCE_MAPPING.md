# TDT-RM Daily Data Source Mapping

This table documents the canonical daily snapshot fields accepted by the local
snapshot/provider bridge. The bridge only normalizes local CSV/JSON inputs; it
does not connect to paid APIs, broker logins, or credentialed services.

| Canonical field | Accepted aliases | Model component | Source category | Affects | Status |
| --- | --- | --- | --- | --- | --- |
| `observed_at` / `trade_date` | `date`, `資料日期` | Daily artifact identity | price | reporting only | required |
| `close` | `taiex_close`, `index_close`, `收盤價` | TCWRS-P, ETI-1, Bear Trend, decision matrix | price | TCWRS, ETI-5, Bear Trend, CAL, reporting | required |
| `ma5` | `taiex_ma5`, `index_ma5` | TCWRS-P | price | TCWRS, reporting | required |
| `ma20` | `taiex_ma20`, `index_ma20` | TCWRS-P, ETI-1, Bear Trend, decision matrix | price | TCWRS, ETI-5, Bear Trend, CAL, reporting | required |
| `ma60` | `taiex_ma60`, `index_ma60` | TCWRS-P, Bear Trend | price | TCWRS, Bear Trend, reporting | required |
| `ma20_slope` | `taiex_ma20_slope`, `index_ma20_slope` | TCWRS-P | price | TCWRS, reporting | required |
| `one_day_return_pct` | — | TCWRS-P | price | TCWRS, proxy fallback | optional |
| `two_day_return_pct` | — | TCWRS-P | price | TCWRS, proxy fallback | optional |
| `turnover_amount` | `taiex_turnover`, `turnover` | TCWRS-V | price | TCWRS, reporting | optional |
| `ma20_turnover` | `turnover_ma20` | TCWRS-V | price | TCWRS | optional |
| `foreign_spot_net_buy` | — | TCWRS-F | foreign flow | TCWRS | optional |
| `foreign_spot_net_sell_consecutive_days` | — | ETI-2, TCWRS-F | foreign flow | TCWRS, ETI-5 | optional |
| `foreign_large_sell` | — | ETI-2 | foreign flow | ETI-5 | optional |
| `foreign_spot_large_sell` | — | TCWRS-F / ETI-2 availability | foreign flow | TCWRS, ETI-5 availability | optional |
| `futures_hedging_increases` | `futures_hedging_significant` | ETI-2 | foreign flow | ETI-5 | optional |
| `futures_net_short_increases` | — | TCWRS-F | foreign flow | TCWRS | optional |
| `usd_twd_3d_change_pct` | `usdtwd_3d_change_pct` | ETI-3, TCWRS-X | FX | TCWRS, ETI-5 | optional |
| `usd_twd_5d_change_pct` | `usdtwd_5d_change_pct` | ETI-3, TCWRS-X | FX | TCWRS, ETI-5 | optional |
| `twd_depreciates_significantly` | — | TCWRS-X | FX | TCWRS | optional |
| `margin_balance_5d_decline_pct` | — | TCWRS-M | margin | TCWRS | optional |
| `margin_balance_5d_increases` | — | TCWRS-M | margin | TCWRS | optional |
| `advancing_issues` | `advancers`, `上漲家數` | TCWRS-B / ETI-4 availability | breadth | TCWRS, ETI-5 availability | optional |
| `declining_issues` | `decliners`, `下跌家數` | TCWRS-B / ETI-4 availability | breadth | TCWRS, ETI-5 availability | optional |
| `declining_issues_significantly_expand` | — | TCWRS-B | breadth | TCWRS | optional |
| `declining_issues_significantly_gt_advancing` | — | TCWRS-B, ETI-4 | breadth | TCWRS, ETI-5 | optional |
| `breadth_weakens_for_2_days` | — | ETI-4 | breadth | ETI-5 | optional |
| `count_main_7_below_ma20` | — | TCWRS-L, ETI-5 | breadth | TCWRS, ETI-5 | optional |
| `count_main_7_below_ma60` | — | TCWRS-L | breadth | TCWRS | optional |
| `sox`, `sox_ma20`, `sox_ma60` | — | TCWRS-G | external risk | TCWRS | optional |
| `nasdaq`, `nasdaq_ma20` | — | TCWRS-G | external risk | TCWRS | optional |
| `vix_rises_fast`, `vix_spikes` | — | TCWRS-G | external risk | TCWRS | optional |
| `tail_risk` | `tail_risk_score`, `formal_tail_risk` | Crash Probability | formal Tail Risk | CP, decision matrix | proxy fallback |
| `bcd` | `bcd_score`, `formal_bcd` | Crash Probability | formal BCD | CP, decision matrix | proxy fallback |
| `mhs` | `mhs_score` | Decision matrix MHS input | external risk | decision matrix | not yet implemented |
| `price_bars[]` | rows with `observed_at`, `close`, optional OHLC/turnover | Price-only fallback bridge | price | proxy fallback, reporting | optional |
| `field_sources` | canonical field to source id mapping | source coverage | all | reporting only | optional |
| `source_metadata` | source id metadata (`name`, `retrieved_at`, `notes`) | source coverage | all | reporting only | optional |

## ETI availability rules

ETI availability is derived from supplied fields, not from whether an `ETI5Input`
object can be constructed with default values:

- `ETI-1`: `close` and `ma20` are supplied.
- `ETI-2`: a foreign-selling or futures-hedging field is supplied.
- `ETI-3`: a USD/TWD change field is supplied.
- `ETI-4`: a breadth deterioration field is supplied.
- `ETI-5`: `count_main_7_below_ma20` is supplied.

The V5.1.4 availability-cap behavior remains in `score_eti5()`; the snapshot
bridge only supplies the available component set.
