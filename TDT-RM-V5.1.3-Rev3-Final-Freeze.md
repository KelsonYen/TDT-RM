# TDT-RM V5.1.3 Rev.3 Final Freeze Specification

Author: Dr. Yen  
Model: TDT-RM V5.1.3 Decision Matrix Patch Rev.3  
Chinese Name: 台股雙溫度計風控模型 V5.1.3 Rev.3 正式凍結版  
English Name: Taiwan Dual Thermometer Risk Monitor V5.1.3 Rev.3 Final Freeze  
Version Status: 正式凍結版 / Final Freeze Execution Spec  
Created At: 2026/05/24 08:12  
Purpose: 每日台股大盤風控正式執行規格

---

## 1. Model Positioning

本模型用於每日盤後或隔日早上，判斷台股大盤風險、股票曝險上限與今日操作動作。

本模型不是預測模型，不猜高低點，不預測明日漲跌。

核心目的：避免市場結構壞掉時仍維持高曝險。

每日只跑一次，以前一交易日正式盤後資料為準。

資料狀態判斷：

```text
IF required_data_is_incomplete:
    data_status = "暫估版"

IF foreign_investor_data_complete
AND margin_data_complete
AND turnover_data_complete
AND breadth_data_complete
AND fx_data_complete
AND moving_average_data_complete:
    data_status = "正式版"
```

---

## 2. Core Indicators

TDT-RM V5.1.3 Rev.3 Final Freeze uses five core indicators.

| Indicator | Chinese Name | Function |
|---|---|---|
| MHS | 市場熱度 | 判斷上漲是否過熱 |
| BCD | 廣度集中背離 | 判斷上漲是否是假強勢 |
| TCWRS | 台股結構風險 | 判斷市場是否結構轉弱 |
| Tail Risk | 尾端風險 | 判斷外部壓力、避險壓力與極端波動 |
| ETI-5 | 落地確認 | 判斷風險是否已從溫度升高變成實際破壞 |

---

# 3. TCWRS: Taiwan Crash Warning Risk Score

Total Score: 0–100  
Principle: 只衡量結構破壞，不衡量漲多或高估值。

TCWRS contains eight sub-factors.

| Code | Factor | Max Score |
|---|---|---:|
| P | 價格趨勢與跌速 | 18 |
| V | 成交量與價量效率 | 12 |
| F | 外資現貨、期貨、選擇權避險 | 15 |
| X | 新台幣與跨境資金 | 12 |
| M | 融資槓桿與散戶風險 | 12 |
| B | 市場廣度惡化 | 12 |
| L | 權值股與主流股健康度 | 10 |
| G | 全球風險與外部壓力 | 9 |

```text
TCWRS = P + V + F + X + M + B + L + G
TCWRS range = 0 to 100
```

## 3.1 P: Price Trend and Downside Speed

Max Score: 18

| Score | Condition |
|---:|---|
| 0 | 收盤在20日線上，且20日線上彎 |
| 4 | 跌破5日線，但仍在20日線上 |
| 8 | 跌破20日線1日 |
| 12 | 連2日跌破20日線 |
| 15 | 跌破60日線 |
| 18 | 單日跌幅 ≥ 3.5%，或2日累跌 ≥ 5.5% |

```text
IF close > MA20 AND MA20_slope > 0:
    P = 0
ELIF close < MA5 AND close >= MA20:
    P = 4
ELIF close < MA20 for 1 day:
    P = 8
ELIF close < MA20 for 2 consecutive days:
    P = 12
ELIF close < MA60:
    P = 15
ELIF one_day_return <= -3.5% OR two_day_return <= -5.5%:
    P = 18
```

## 3.2 V: Volume and Price-Volume Efficiency

Max Score: 12

| Score | Condition |
|---:|---|
| 0 | 量增價漲、收紅 |
| 3 | 高檔放量但收紅 |
| 6 | 高檔長上影 |
| 9 | 爆量收黑 |
| 12 | 爆量長黑且跌破20日線 |

Definition of 爆量:

```text
high_volume = turnover_amount > MA20_turnover * 1.5
           OR turnover_amount is in the top 10% of the past one year
```

```text
IF volume_up AND price_up AND close_is_red:
    V = 0
ELIF high_level AND high_volume AND close_is_red:
    V = 3
ELIF high_level AND long_upper_shadow:
    V = 6
ELIF high_volume AND close_is_black:
    V = 9
ELIF high_volume AND long_black_candle AND close < MA20:
    V = 12
```

## 3.3 F: Foreign Investor Spot, Futures, and Options Hedging

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 外資現貨買超，期貨淨空下降，PCR/VIX穩定 |
| 4 | 外資現貨小賣，但期貨未明顯避險 |
| 8 | 外資連2日賣超 |
| 11 | 外資連3日賣超，且台指期淨空增加 |
| 15 | 外資現貨大賣＋期貨淨空增加＋PCR或VIX同步升高 |

```text
IF foreign_spot_net_buy > 0 AND futures_net_short_decreases AND PCR_stable AND VIX_stable:
    F = 0
ELIF foreign_spot_small_sell AND NOT futures_hedging_significant:
    F = 4
ELIF foreign_spot_net_sell for 2 consecutive days:
    F = 8
ELIF foreign_spot_net_sell for 3 consecutive days AND futures_net_short_increases:
    F = 11
ELIF foreign_spot_large_sell AND futures_net_short_increases AND (PCR_rises OR VIX_rises):
    F = 15
```

## 3.4 X: New Taiwan Dollar and Cross-Border Capital Flow

Max Score: 12

| Score | Condition |
|---:|---|
| 0 | 台幣升值或穩定 |
| 4 | 美元兌台幣3日升幅 > 0.5% |
| 8 | 美元兌台幣5日升幅 > 1.0% |
| 12 | 台股下跌＋台幣明顯貶值＋外資賣超 |

```text
IF TWD_appreciates OR TWD_stable:
    X = 0
ELIF USD_TWD_3d_change > 0.5%:
    X = 4
ELIF USD_TWD_5d_change > 1.0%:
    X = 8
ELIF index_down AND TWD_depreciates_significantly AND foreign_spot_net_sell:
    X = 12
```

## 3.5 M: Margin Leverage and Retail Risk

Max Score: 12

| Score | Condition |
|---:|---|
| 0 | 融資餘額5日持平或下降，且未出現熱門股融資快速增加 |
| 4 | 融資餘額5日增加，但指數仍在20日線上 |
| 8 | 指數5日跌幅 > 3%，但融資減幅 < 0.5% |
| 12 | 指數下跌、融資不退、熱門股融資快速增加 |

```text
IF margin_balance_5d_flat_or_down AND NOT hot_stock_margin_fast_increase:
    M = 0
ELIF margin_balance_5d_increases AND close >= MA20:
    M = 4
ELIF index_5d_return < -3% AND margin_balance_5d_decline < 0.5%:
    M = 8
ELIF index_down AND margin_not_retreating AND hot_stock_margin_fast_increase:
    M = 12
```

## 3.6 B: Market Breadth Deterioration

Max Score: 12

| Score | Condition |
|---:|---|
| 0 | 指數上漲或持平，且上漲家數大於下跌家數 |
| 4 | 指數下跌，但下跌家數未明顯擴大 |
| 8 | 指數下跌，且下跌家數明顯大於上漲家數 |
| 12 | 指數跌破20日線，且下跌家數連續2日明顯大於上漲家數 |

Important rule:

```text
IF index_up AND breadth_deteriorates:
    Do NOT score this under TCWRS_B
    Score it under BCD instead
```

```text
IF index_up_or_flat AND advancing_issues > declining_issues:
    B = 0
ELIF index_down AND NOT declining_issues_significantly_expand:
    B = 4
ELIF index_down AND declining_issues >> advancing_issues:
    B = 8
ELIF close < MA20 AND declining_issues >> advancing_issues for 2 consecutive days:
    B = 12
```

## 3.7 L: Large-Cap and Mainstream Stock Health

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | 七大主流標的多數在20日線上 |
| 3 | 2檔跌破20日線 |
| 6 | 4檔跌破20日線 |
| 8 | 5檔跌破20日線 |
| 10 | 超過半數跌破60日線 |

```text
IF majority_main_7_assets_above_MA20:
    L = 0
ELIF count_main_7_below_MA20 == 2:
    L = 3
ELIF count_main_7_below_MA20 == 4:
    L = 6
ELIF count_main_7_below_MA20 == 5:
    L = 8
ELIF count_main_7_below_MA60 > 3:
    L = 10
```

## 3.8 G: Global Risk and External Pressure

Max Score: 9

| Score | Condition |
|---:|---|
| 0 | 美股、SOX、VIX穩定 |
| 3 | SOX或Nasdaq跌破20日線 |
| 6 | SOX跌破60日線，或VIX快速上升 |
| 9 | 美股科技主軸明確轉弱＋VIX急升＋台股跌破20日線或60日線 |

Important rule:

```text
High valuation is NOT scored under TCWRS_G.
High valuation must be handled by MHS_VAL_MHS.
```

```text
IF US_stocks_stable AND SOX_stable AND VIX_stable:
    G = 0
ELIF SOX < SOX_MA20 OR Nasdaq < Nasdaq_MA20:
    G = 3
ELIF SOX < SOX_MA60 OR VIX_rises_fast:
    G = 6
ELIF US_tech_leadership_weakens AND VIX_spikes AND (TAIEX < MA20 OR TAIEX < MA60):
    G = 9
```

---

# 4. MHS: Market Heat Score

Total Score: 0–100  
Principle: 衡量市場過熱，不等於崩盤。

| Code | Factor | Max Score |
|---|---|---:|
| P_MHS | 價格加速度 | 15 |
| V_MHS | 成交量與週轉熱度 | 15 |
| M_MHS | 融資槓桿熱度 | 15 |
| VAL_MHS | 估值熱度 | 15 |
| T_MHS | 投機交易熱度 | 10 |
| R_MHS | 散戶資金與開戶熱度 | 10 |
| ETF_MHS | ETF與被動資金熱度 | 10 |
| S_MHS | 媒體社群與本夢比熱度 | 10 |

```text
MHS = P_MHS + V_MHS + M_MHS + VAL_MHS + T_MHS + R_MHS + ETF_MHS + S_MHS
MHS range = 0 to 100
```

## 4.1 P_MHS: Price Acceleration

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 指數低於20日線 |
| 5 | 站上20日線但未創高 |
| 10 | 接近60日高點 |
| 15 | 創60日新高或歷史新高 |

## 4.2 V_MHS: Volume and Turnover Heat

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 成交低於20日均量 |
| 5 | 成交高於20日均量 |
| 10 | 成交高於20日均量1.5倍 |
| 15 | 成交位於一年成交量前10%高量區 |

## 4.3 M_MHS: Margin Leverage Heat

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 融資下降 |
| 5 | 融資溫和增加 |
| 10 | 融資5日快速增加 |
| 15 | 融資創波段高，且熱門股槓桿集中 |

## 4.4 VAL_MHS: Valuation Heat

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 估值低於長期均值 |
| 5 | 估值接近長期均值上緣 |
| 10 | 估值高於長期均值一個標準差 |
| 15 | 估值進入歷史高分位 |

## 4.5 T_MHS: Speculative Trading Heat

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | 漲停家數少，題材輪動正常 |
| 4 | 熱門族群連續噴出 |
| 7 | 大量個股漲停或高週轉 |
| 10 | 低基本面題材股全面噴出 |

## 4.6 R_MHS: Retail Capital and Account Opening Heat

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | 散戶參與正常 |
| 4 | 零股與定期定額明顯升溫 |
| 7 | 開戶、融資、熱門ETF申購同步升高 |
| 10 | 市場出現明顯全民追高氛圍 |

## 4.7 ETF_MHS: ETF and Passive Capital Heat

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | ETF資金正常 |
| 4 | ETF成交放大 |
| 7 | 高股息、科技ETF同步大量申購 |
| 10 | ETF換股、申購、成分股拉抬同步過熱 |

## 4.8 S_MHS: Media, Social Narrative, and Dream-Valuation Heat

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | 媒體討論正常 |
| 4 | 財經媒體大量報導創高 |
| 7 | 社群普遍看多 |
| 10 | 出現明顯「不買會錯過」敘事 |

---

# 5. Tail Risk Score

Total Score: 0–100  
Principle: 衡量極端壓力，不處理一般日常波動。

| Code | Factor | Max Score |
|---|---|---:|
| Derivatives | 避險壓力 | 25 |
| FX | 極端匯率壓力 | 20 |
| Global Shock | 全球衝擊 | 20 |
| Liquidity | 極端流動性壓力 | 15 |
| Correlation | 共振風險 | 20 |

```text
TailRisk = Derivatives + FX + GlobalShock + Liquidity + Correlation
TailRisk range = 0 to 100
```

## 5.1 Derivatives: Hedging Pressure

Max Score: 25

| Score | Condition |
|---:|---|
| 0 | PCR、VIX、期貨淨空穩定 |
| 10 | PCR或VIX單項升高 |
| 18 | PCR、VIX同步升高 |
| 25 | 外資期貨大幅加空＋選擇權避險急升 |

## 5.2 FX: Extreme Foreign Exchange Pressure

Max Score: 20

| Score | Condition |
|---:|---|
| 0 | 台幣穩定 |
| 8 | 美元兌台幣5日升幅 > 1% |
| 15 | 股跌＋台幣5日明顯貶值＋外資賣超 |
| 20 | 股匯同步急殺，且外資現貨、期貨同步避險 |

Important rule:

```text
Tail Risk FX threshold is intentionally higher than TCWRS_X.
Three-day minor TWD depreciation is absorbed by TCWRS_X and must NOT enter TailRisk_FX.
```

## 5.3 Global Shock

Max Score: 20

| Score | Condition |
|---:|---|
| 0 | 外部市場穩定 |
| 8 | SOX或Nasdaq跌破20日線 |
| 15 | SOX跌破60日線 |
| 20 | 美股急跌、VIX跳升、半導體主軸轉弱 |

## 5.4 Liquidity: Extreme Liquidity Pressure

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 成交正常 |
| 5 | 下跌時成交放大，但未破20日線 |
| 10 | 爆量收黑，且收盤跌破20日線 |
| 15 | 爆量長黑，且次日無法收復20日線，或同步跌破60日線 |

## 5.5 Correlation: Risk Resonance

Max Score: 20

| Score | Condition |
|---:|---|
| 0 | 風險分散 |
| 8 | 台股、匯率、外資其中兩項轉弱 |
| 15 | 價格、匯率、外資、廣度三項轉弱 |
| 20 | 四項同步惡化 |

## 5.6 Tail Risk Tiers

| Score Range | Tier |
|---:|---|
| 0–40 | 低 |
| 41–60 | 中 |
| 61–75 | 高 |
| 76–100 | 極高 |

---

# 6. BCD: Breadth Concentration Divergence Score

Total Score: 0–100  
Principle: 只偵測上漲中的假強勢，不處理下跌中的市場破壞。

## 6.1 Activation Conditions

BCD is activated when one or more of the following conditions are present:

```text
BCD_active IF:
    TAIEX_up_today
    OR TAIEX_up_within_5_days
    OR (TAIEX_above_MA20 AND breadth_significantly_deteriorates)
    OR TAIEX_makes_60d_high
    OR TAIEX_makes_historical_high
```

Activation conditions:

1. 加權指數當日上漲。
2. 加權指數5日內上漲。
3. 加權指數位於20日線上方但廣度明顯轉弱。
4. 加權指數創60日新高或歷史新高。

## 6.2 BCD Scoring Items

| Code | Factor | Max Score |
|---|---|---:|
| Index-Breadth Divergence | 指數與漲跌家數背離 | 30 |
| Mega-cap Concentration | 權值集中度 | 25 |
| Sector Breadth | 族群擴散度 | 20 |
| Small/Mid Weakness | 中小型股弱化 | 15 |
| Volume Concentration | 成交集中度 | 10 |

```text
BCD = IndexBreadthDivergence + MegaCapConcentration + SectorBreadth + SmallMidWeakness + VolumeConcentration
BCD range = 0 to 100
```

### 6.2.1 Index-Breadth Divergence

Max Score: 30

| Score | Condition |
|---:|---|
| 0 | 指數上漲且上漲家數明顯多 |
| 10 | 指數上漲但漲跌家數接近 |
| 20 | 指數上漲但下跌家數較多 |
| 30 | 連2日以上指數創高但下跌家數較多 |

### 6.2.2 Mega-cap Concentration

Max Score: 25

| Score | Condition |
|---:|---|
| 0 | 多族群同步上漲 |
| 8 | 前五大權值股貢獻大盤漲幅超過40% |
| 16 | 前五大權值股貢獻超過60% |
| 25 | 台積電或少數AI權值股單獨拉盤，多數族群不跟 |

### 6.2.3 Sector Breadth

Max Score: 20

| Score | Condition |
|---:|---|
| 0 | 電子、金融、傳產同步 |
| 6 | 僅電子強 |
| 12 | 僅半導體或AI強 |
| 20 | 單一主流族群強，其他族群普遍弱 |

### 6.2.4 Small/Mid Weakness

Max Score: 15

| Score | Condition |
|---:|---|
| 0 | 櫃買與加權同步強 |
| 5 | 櫃買落後加權 |
| 10 | 加權創高但櫃買不創高 |
| 15 | 加權漲、櫃買跌 |

### 6.2.5 Volume Concentration

Max Score: 10

| Score | Condition |
|---:|---|
| 0 | 成交分布正常 |
| 4 | 成交集中於大型權值 |
| 7 | 成交集中於少數ETF或AI股 |
| 10 | 成交極度集中，市場內部流動性變差 |

## 6.3 BCD Tiers

| Score Range | Tier |
|---:|---|
| 0–30 | 健康 |
| 31–50 | 輕度集中 |
| 51–70 | 明顯拉積盤 |
| 71–100 | 高度背離，假強勢風險高 |

---

# 7. BCD State Machine

## 7.1 Normal State

Condition:

```text
IF TAIEX > MA20 AND consecutive_down_days <= 3:
    BCD_state = "normal"
    BCD_can_score_normally = True
    BCD_can_upgrade_signal = True
```

Description:

指數在20日線上方，未連跌超過3日。BCD正常計分，可參與升燈。

## 7.2 Restricted State

Condition:

```text
IF TAIEX < MA20 OR (TAIEX_rebounds_from_below_MA60 AND NOT TAIEX_back_above_MA60):
    BCD_state = "restricted"
    BCD_max_score = 50
    BCD_61_upgrade_condition_valid = False
```

Description:

指數跌破20日線，或從60日線下方反彈但尚未站回60日線。BCD最高50分，不得觸發BCD ≥ 61條件。

## 7.3 Upgrade-Suspended State

Condition:

```text
IF TAIEX < MA60 OR consecutive_down_days > 3:
    BCD_state = "upgrade_suspended"
    BCD_observation_allowed = True
    BCD_can_upgrade_signal = False
```

Description:

指數跌破60日線，或連跌超過3日。BCD可作觀察值，但不得參與升燈。

## 7.4 Full-Recovery State

Condition:

```text
IF TAIEX > MA60 AND TAIEX_not_below_MA60_for_2_consecutive_days:
    BCD_state = "full_recovery"
    BCD_can_score_normally = True
    BCD_can_upgrade_signal = True
```

Description:

指數重新站回60日線，且連續2日未跌破60日線。BCD恢復完整計分與升燈功能。

## 7.5 BCD State Priority

Priority order:

```text
1. IF consecutive_down_days > 3:
       BCD must NOT be used for signal upgrade

2. IF TAIEX < MA60:
       BCD signal upgrade function is suspended

3. IF TAIEX < MA20:
       BCD can still be scored, but maximum score is 50

4. IF TAIEX > MA20 AND consecutive_down_days <= 3:
       BCD returns to restricted or normal state

5. IF TAIEX > MA60 AND TAIEX_not_below_MA60_for_2_consecutive_days:
       BCD full signal upgrade function is restored
```

---

# 8. ETI-5: Exit Trigger Index 5

Total Score: 0–5  
Type: Integer indicator  
Principle: ETI-5不是獨立於TCWRS之外的新指標，而是TCWRS核心子項的二元落地確認層。

TCWRS衡量損傷程度。  
ETI-5衡量損傷件數。  
兩者搭配使用，避免單一高分因子誤導決策。

## 8.1 ETI Components

| Code | Name | Condition |
|---|---|---|
| ETI-1 | 加權指數有效跌破20日線 | 收盤跌破20日線，或連續2日未能站回20日線 |
| ETI-2 | 外資連續賣超 | 外資現貨連續2日賣超，或單日大賣且期貨避險同步增加 |
| ETI-3 | 新台幣轉貶 | 美元兌新台幣3日升幅 > 0.5%，或5日升幅 > 1.0% |
| ETI-4 | 市場廣度惡化 | 指數下跌且下跌家數明顯大於上漲家數，或連續2日廣度轉弱 |
| ETI-5 | 主流七標的失靈 | 固定七標的中至少4檔跌破20日線；若5檔以上跌破20日線，視為高風險確認 |

```text
ETI_1 = 1 IF close < MA20 OR close_not_back_above_MA20_for_2_days ELSE 0
ETI_2 = 1 IF foreign_spot_net_sell_for_2_days OR (foreign_large_sell AND futures_hedging_increases) ELSE 0
ETI_3 = 1 IF USD_TWD_3d_change > 0.5% OR USD_TWD_5d_change > 1.0% ELSE 0
ETI_4 = 1 IF (index_down AND declining_issues >> advancing_issues) OR breadth_weakens_for_2_days ELSE 0
ETI_5 = 1 IF count_main_7_below_MA20 >= 4 ELSE 0

ETI5_total = ETI_1 + ETI_2 + ETI_3 + ETI_4 + ETI_5
ETI5_total range = 0 to 5
```

## 8.2 ETI-5 Interpretation

| Score | Interpretation |
|---:|---|
| 0–1 | 風險未落地 |
| 2 | 初步轉弱 |
| 3 | 結構風險落地 |
| 4 | 高風險 |
| 5 | 系統性風險確認 |

---

# 9. Main Seven Assets Definition

## 9.1 Fixed Core Assets

1. 2330 台積電
2. 0050
3. 00878或0056，依使用者主要持有標的固定

## 9.2 Quarterly Review Assets

4. 市值前三大非台積電權值股選二檔
5. 主流產業代表股選二檔

## 9.3 Asset Fixing Rule

```text
Once main_7_assets are fixed for the quarter:
    They must NOT be changed arbitrarily on a daily basis
    Purpose: avoid hindsight adjustment
```

---

# 10. Resonance and Duplicate-Scoring Rules

## 10.1 MHS High and TCWRS Low

```text
IF MHS_high AND TCWRS_low:
    interpretation = "強多過熱"
    structural_breakdown = False
```

MHS高、TCWRS低，判定為強多過熱，不是結構崩壞。

## 10.2 BCD High and Index Above MA20

```text
IF BCD_high AND TAIEX > MA20:
    interpretation = "假強勢警示"
    signal_can_upgrade_to = ["黃燈強化", "橘燈"]
    signal_cannot_upgrade_to_red_by_BCD_alone = True
```

BCD高、指數在20日線上，判定為假強勢警示，可升至黃燈強化或橘燈，但不得單獨升紅燈。

## 10.3 Tail Risk High and TCWRS Low

```text
IF TailRisk_high AND TCWRS_low:
    interpretation = "外部或避險壓力升高"
    red_signal_by_tailrisk_alone = False
```

Tail Risk高、TCWRS低，判定為外部或避險壓力升高，不能單獨升紅燈。

## 10.4 TCWRS High and ETI-5 High

```text
IF TCWRS_high AND ETI5_high:
    interpretation = "風險落地"
    priority = "higher_than_MHS_BCD_TailRisk"
```

TCWRS高且ETI-5同步升高，判定為風險落地，優先級高於MHS、BCD與Tail Risk。

## 10.5 Tail Risk and TCWRS Overlap

```text
TailRisk and TCWRS sub-factors may overlap by design.
This is intentional resonance design, not accidental duplicate scoring.
However, a single event must NOT independently push the signal to orange or red.
```

## 10.6 High-Volume Black Candle Resonance Rule

爆量收黑可同時計入TCWRS V項與Tail Risk Liquidity。

However, to upgrade to orange, at least one third confirmation condition must be satisfied.

Third confirmation conditions:

```text
orange_upgrade_allowed_from_high_volume_black_candle IF at_least_one_of:
    ETI5_total >= 2
    OR foreign_spot_net_sell_for_consecutive_days
    OR TWD_depreciates_significantly
    OR TAIEX < MA20
    OR (BCD >= 61 AND TAIEX > MA20)
    OR count_main_7_below_MA20 >= 4
```

---

# 11. Crash Probability Calculation

## 11.1 Formula

```text
CP_raw = TCWRS × 0.40 + (ETI5_total × 20) × 0.30 + TailRisk × 0.20 + BCD × 0.10
CP = min(CP_raw, 100)
```

## 11.2 Crash Probability Tiers

| Score Range | Tier |
|---:|---|
| 0–30 | 低 |
| 31–55 | 中 |
| 56–75 | 高 |
| 76–100 | 極高 |

Important rule:

```text
CP is auxiliary only.
CP must NOT independently upgrade the signal to red.
```

---

# 12. Regime State Decision Order

Fixed order:

```text
Crash -> Fragile -> Hot -> Calm
```

The first matched condition in the fixed order should be used.

## 12.1 Crash

```text
IF TCWRS >= 76 OR ETI5_total >= 4 OR (TCWRS >= 61 AND ETI5_total >= 3):
    RegimeState = "Crash"
```

## 12.2 Fragile

```text
ELIF TCWRS >= 41 OR ETI5_total >= 2 OR TailRisk >= 61:
    RegimeState = "Fragile"
```

## 12.3 Hot

```text
ELIF MHS >= 71 AND TCWRS <= 40 AND ETI5_total <= 1:
    RegimeState = "Hot"
```

## 12.4 Calm

```text
ELIF TCWRS <= 20 AND ETI5_total == 0 AND TailRisk <= 40 AND MHS <= 70:
    RegimeState = "Calm"
```

---

# 13. Five-Light Decision Matrix

Fixed decision order:

```text
紅燈 -> 橘燈 -> 黃燈強化 -> 黃燈 -> 綠燈
```

The first matched condition in the fixed order should be used.

---

## 13.1 Red Light

Signal: 紅燈  
Action: 股票曝險降至20–30%以下。

Conditions:

```text
IF TCWRS >= 76:
    Signal = "紅燈"
    equity_exposure_limit = "20–30%以下"

ELIF ETI5_total >= 4:
    Signal = "紅燈"
    equity_exposure_limit = "20–30%以下"

ELIF TCWRS >= 61 AND ETI5_total >= 3:
    Signal = "紅燈"
    equity_exposure_limit = "20–30%以下"
```

Important rule:

```text
TailRisk, no matter how high, is insufficient to upgrade to red either alone or together with ETI5_total <= 3.
```

---

## 13.2 Orange Light

Signal: 橘燈  
Action: 股票曝險降至40–50%。

Conditions:

```text
IF 61 <= TCWRS <= 75 AND ETI5_total >= 2:
    Signal = "橘燈"
    equity_exposure_limit = "40–50%"

ELIF ETI5_total >= 3 AND TCWRS >= 41:
    Signal = "橘燈"
    equity_exposure_limit = "40–50%"

ELIF TCWRS >= 41 AND TailRisk >= 61 AND ETI5_total >= 2:
    Signal = "橘燈"
    equity_exposure_limit = "40–50%"

ELIF BCD >= 61 AND TCWRS >= 41 AND ETI5_total >= 2 AND TAIEX > MA20 AND consecutive_down_days <= 3:
    Signal = "橘燈"
    equity_exposure_limit = "40–50%"
```

Important rule:

```text
BCD >= 61 condition is valid only when TAIEX is above MA20 and consecutive_down_days <= 3.
```

---

## 13.3 Strengthened Yellow Light

Signal: 黃燈強化  
Action: 股票曝險50–70%，停止加碼，降低槓桿。

Conditions:

```text
IF 41 <= TCWRS <= 60:
    Signal = "黃燈強化"
    equity_exposure_limit = "50–70%"

ELIF MHS >= 86 AND TCWRS >= 30:
    Signal = "黃燈強化"
    equity_exposure_limit = "50–70%"

ELIF ETI5_total >= 2 AND TCWRS >= 21:
    Signal = "黃燈強化"
    equity_exposure_limit = "50–70%"

ELIF TailRisk >= 61 AND TCWRS >= 21:
    Signal = "黃燈強化"
    equity_exposure_limit = "50–70%"

ELIF BCD >= 61 AND TCWRS >= 21 AND TAIEX > MA20 AND consecutive_down_days <= 3:
    Signal = "黃燈強化"
    equity_exposure_limit = "50–70%"
```

Important rule:

```text
BCD >= 61 condition is valid only when TAIEX is above MA20 and consecutive_down_days <= 3.
```

---

## 13.4 Yellow Light

Signal: 黃燈  
Action: 股票曝險60–80%，持有，不追高，不融資。

Conditions:

```text
IF 21 <= TCWRS <= 40:
    Signal = "黃燈"
    equity_exposure_limit = "60–80%"

ELIF MHS >= 71:
    Signal = "黃燈"
    equity_exposure_limit = "60–80%"

ELIF ETI5_total >= 1:
    Signal = "黃燈"
    equity_exposure_limit = "60–80%"

ELIF TailRisk >= 41:
    Signal = "黃燈"
    equity_exposure_limit = "60–80%"

ELIF BCD >= 41:
    Signal = "黃燈"
    equity_exposure_limit = "60–80%"
```

---

## 13.5 Green Light

Signal: 綠燈  
Action: 正常持有。

Condition:

```text
IF TCWRS <= 20 AND ETI5_total == 0 AND TailRisk <= 40 AND BCD <= 40 AND MHS <= 70:
    Signal = "綠燈"
    equity_exposure_limit = "80–100%"
```

---

# 14. Equity Exposure Limits

| Signal | Equity Exposure Limit | Action |
|---|---:|---|
| 綠燈 | 80–100% | 正常持有 |
| 黃燈 | 60–80% | 持有，不追高，不融資 |
| 黃燈強化 | 50–70% | 停止加碼，降低槓桿 |
| 橘燈 | 40–50% | 降低股票曝險 |
| 紅燈 | 20–30%以下 | 大幅降低股票曝險 |

Important rule:

```text
Equity exposure limit is a maximum exposure ceiling.
It is NOT a mandatory full-position rule and NOT a mandatory liquidation rule.
```

---

# 15. Daily Output Format

## 15.1 Title Format

```text
YYYY/MM/DD 台股雙溫度計風控報告
```

## 15.2 Basic Fields

```text
作者：Dr. Yen
模型：TDT-RM V5.1.3 Rev.3 Final Freeze
資料日期：YYYY/MM/DD
產出時間：YYYY/MM/DD HH:MM
資料狀態：暫估版／正式版
今日燈號：
市場狀態：
TCWRS：
MHS：
ETI-5：
Tail Risk：
BCD：
Crash Probability：
股票曝險上限：
```

## 15.3 Fixed Sections

```text
■ 核心結論
■ ETI-5明細
■ 今日動作
■ 優先減碼順序
■ 警報解除條件
■ 結論
```

---

# 16. Version Freeze Declaration

Official model name:

```text
TDT-RM V5.1.3 Decision Matrix Patch Rev.3 Final Freeze
```

Chinese name:

```text
台股雙溫度計風控模型 V5.1.3 Rev.3 正式凍結版
```

English name:

```text
Taiwan Dual Thermometer Risk Monitor V5.1.3 Rev.3 Final Freeze
```

Version status:

```text
正式執行規格
```

Execution rule:

```text
Use this version for all future daily market risk-control analysis.
Do not revise this version arbitrarily unless clear false positives, false negatives, or continuous execution contradictions appear.
```

---

# 17. Final Conclusion

TDT-RM V5.1.3 Rev.3 Final Freeze 正式固定。

This version's core value is clean functional separation:

| Indicator | Function |
|---|---|
| MHS | 看過熱 |
| BCD | 看假強勢 |
| TCWRS | 看結構破壞 |
| Tail Risk | 看極端壓力 |
| ETI-5 | 看風險落地 |

Decision principles:

```text
Do not misclassify market overheating as a crash.
Do not allow a single high-volume black candle to directly push the signal to red.
Do not allow a single hedging signal to directly push the signal to red.
Use this version as the formal execution baseline for daily Taiwan stock market risk control.
```
