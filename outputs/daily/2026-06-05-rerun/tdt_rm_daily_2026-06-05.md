2026/06/05 台股雙溫度計風控報告
作者：Dr. Yen
模型：TDT-RM V5.1.4 Backtest Calibration Patch
資料日期：2026/06/05
產出時間：2026/06/07 07:55
資料狀態：正式版
今日燈號：黃燈
市場狀態：觀察
TCWRS：12
MHS：100
ETI-5：1
Tail Risk：53.95
BCD：資料不足／INCOMPLETE
BCD 資料不足，未納入升燈判斷，不影響 TCWRS、ETI-5、Tail Risk 與今日燈號。
Crash Probability：21.59%
股票曝險上限：60–80%

■ 核心結論
１、MHS達高檔過熱區，代表市場情緒與價格動能偏熱；這是過熱提醒，不等於崩盤訊號。
２、TCWRS仍低，代表目前結構性破壞尚未明確出現。
３、ETI-5為1，僅有早期警訊，表示風險尚未全面落地。
４、MHS 分項資料未完整揭露，因此僅能判定為市場過熱訊號，不可單獨解讀為崩盤風險。
５、Tail Risk 尚未形成可單獨升燈的極端尾部風險訊號。
６、今日操作應以持有、停止追價、不使用槓桿、等待風險是否擴散為主。

■ ETI-5 明細
ETI Aggregate

* eti5_total: 1
* eti_available_count: 5
* triggered_signals: ["ETI-4"]

ETI-1 價格結構
Status: NOT_TRIGGERED
Source: taiex_price
Matched Rule: index remains above/effectively back above MA20
Trigger Evidence:
Close = 45070.94
MA20 = 43030.505000000005
Rule: close < ma20 OR close_not_back_above_ma20_for_2_days
Result: FALSE

ETI-2 外資與期貨
Status: NOT_TRIGGERED
Source: foreign_flow_csv, futures_csv
Matched Rule: foreign selling confirmation not triggered
Trigger Evidence:
Foreign Net Sell Consecutive Days = 1
Foreign Large Sell = False
Futures Hedging Increases = False
Rule: foreign_spot_net_sell_consecutive_days >= 2 OR (foreign_large_sell AND futures_hedging_increases)
Result: FALSE

ETI-3 匯率
Status: NOT_TRIGGERED
Source: fx_csv
Matched Rule: TWD depreciation confirmation not triggered
Trigger Evidence:
USD/TWD 3D Change = 0.09540467482907024%
Threshold: > 0.5%
USD/TWD 5D Change = 0.2899566658169802%
Threshold: > 1.0%
Rule: usd_twd_3d_change_pct > 0.5 OR usd_twd_5d_change_pct > 1.0
Result: FALSE

ETI-4 市場廣度
Status: TRIGGERED
Source: breadth_csv
Matched Rule: (index_down AND declining_issues >> advancing_issues) OR breadth_weakens_for_2_days
Trigger Evidence:
Advancing Issues = 3144
Declining Issues = 9578
Index Down = True
Declining Issues > Advancing Issues = True
Rule: declining_issues > advancing_issues
Result: TRUE
Overall ETI-4 Rule: (index_down AND declining_issues > advancing_issues) OR breadth_weakens_for_2_days
Overall Result: TRUE

ETI-5 主流股結構
Status: NOT_TRIGGERED
Source: leadership_csv
Matched Rule: leadership breakdown confirmation not triggered
Trigger Evidence:
Count Main 7 Below MA20 = 0
Threshold: >= 4
Rule: count_main_7_below_ma20 >= 4
Result: FALSE

■ 資料來源稽核
ETI-1
Provider:
taiex_price

Status:
AVAILABLE

ETI-2
Provider:
foreign_flow_csv
futures_csv

Status:
AVAILABLE

ETI-3
Provider:
fx_csv

Status:
AVAILABLE

ETI-4
Provider:
breadth_csv

Status:
AVAILABLE

ETI-5
Provider:
leadership_csv

Status:
AVAILABLE

■ BCD 稽核資訊
Final Score: 資料不足
Data Quality Status: INCOMPLETE

Component Scores
{
  "index_breadth_divergence": 4.0
}

Missing Components
[
  "breadth_history",
  "main7_returns",
  "main7_weights",
  "main7_concentration",
  "sector_breadth",
  "sector_diffusion",
  "otc_return_pct",
  "small_mid_breadth",
  "small_mid_weakness",
  "turnover_concentration_topn",
  "turnover_concentration"
]

Raw Inputs
{
  "taiex_return_pct": -1.3278321517877676,
  "advancing_issues": 3144,
  "declining_issues": 9578,
  "breadth_history": [],
  "main7_returns": {},
  "main7_weights": {},
  "sector_returns": {},
  "sector_above_ma20": {},
  "otc_return_pct": null,
  "small_mid_breadth": null,
  "turnover_concentration_topn": null
}

Source Fields
{
  "observed_at": "margin_csv",
  "one_day_return_pct": "taiex_price",
  "ma20": "taiex_price",
  "previous_ma60": "taiex_price",
  "close": "taiex_price",
  "two_day_return_pct": "taiex_price",
  "index_5d_return_pct": "taiex_price",
  "turnover_amount": "taiex_price",
  "close_below_ma20_consecutive_days": "taiex_price",
  "ma20_slope": "taiex_price",
  "return_60d_pct": "taiex_price",
  "ma5": "taiex_price",
  "ma60": "taiex_price",
  "foreign_spot_net_buy": "foreign_flow_csv",
  "foreign_spot_net_sell_consecutive_days": "foreign_flow_csv",
  "foreign_spot_large_sell": "foreign_flow_csv",
  "foreign_large_sell": "foreign_flow_csv",
  "foreign_spot_net_sell": "foreign_flow_csv",
  "twd_stable": "fx_csv",
  "usd_twd_5d_change_pct": "fx_csv",
  "twd_appreciates": "fx_csv",
  "twd_depreciates_significantly": "fx_csv",
  "usd_twd_3d_change_pct": "fx_csv",
  "declining_issues_significantly_expand": "breadth_csv",
  "breadth_weakens_for_2_days": "breadth_csv",
  "declining_gt_advancing_consecutive_days": "breadth_csv",
  "advancing_issues": "breadth_csv",
  "declining_issues_significantly_gt_advancing": "breadth_csv",
  "declining_issues": "breadth_csv",
  "index_down": "breadth_csv",
  "mhs": "leadership_csv",
  "majority_main_7_assets_above_ma20": "leadership_csv",
  "main_7_symbols": "leadership_csv",
  "count_main_7_below_ma20": "leadership_csv",
  "count_main_7_below_ma60": "leadership_csv",
  "futures_hedging_significant": "futures_csv",
  "futures_hedging_increases": "futures_csv",
  "futures_net_short_decreases": "futures_csv",
  "futures_net_short_increases": "futures_csv",
  "pcr_stable": "options_csv",
  "vix_rises": "options_csv",
  "pcr_rises": "options_csv",
  "tail_risk": "options_csv",
  "vix_stable": "options_csv",
  "margin_balance_5d_decline_pct": "margin_csv",
  "margin_not_retreating": "margin_csv",
  "margin_balance_5d_increases": "margin_csv",
  "margin_balance_5d_flat_or_down": "margin_csv",
  "hot_stock_margin_fast_increase": "margin_csv",
  "taiex_return_pct": "taiex_price"
}

■ Tail Risk 稽核資訊
Final Score: 53.9456
Derivatives
Sub Score: 53.9456
資料來源: ["options_csv"]
FX
Sub Score: 資料不足
資料來源: ["fx_csv"]
Global Shock
Sub Score: 資料不足
資料來源: []
Liquidity
Sub Score: 資料不足
資料來源: ["foreign_flow_csv", "margin_csv"]
Correlation
Sub Score: 資料不足
資料來源: ["leadership_csv"]
缺失欄位
[
  "nasdaq",
  "sox"
]
計算狀態
FORMAL_PROVIDER_TOTAL_WITH_SOURCE_FIELDS

■ Report Quality Gate
ETI Audit Trace Available: PASS
BCD Trace Available: PASS
Tail Risk Trace Available: PASS
Provider Health Available: PASS
Field Sources Available: PASS
Result: 正式版

■ 今日動作
１、持股：維持核心持股，單日不因高檔震盪而情緒化出清。
２、加碼：暫停追高，等待拉回或風險指標降溫。
３、減碼：目前不需要強制減碼，但不應新增短線追高部位。
４、槓桿：不融資、不加槓桿。
５、現金部位：保留調節空間，使股票曝險不高於60–80%。

■ 優先減碼順序
目前不需要強制減碼；若後續升燈，減碼順序如下：
１、高波動科技ETF或主題ETF
２、短線追高部位
３、槓桿或融資部位
４、核心長期ETF

■ 警報解除條件
１、MHS降溫。
２、TCWRS維持低檔。
３、ETI-5降至0或1。
４、Tail Risk未升高。
５、BCD未出現明顯假強勢。

■ 結論
目前市場屬於強勢多頭後期的偏熱狀態，而不是結構性崩盤狀態。操作上應維持核心持股，但停止追價與槓桿，等待TCWRS與ETI-5是否同步升高。真正需要大幅降曝險的條件，是價格破壞、外資賣超、台幣轉貶與主流股失靈同時出現。
