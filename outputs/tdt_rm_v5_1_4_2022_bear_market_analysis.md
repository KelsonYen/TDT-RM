# TDT-RM V5.1.4 2022 熊市回測分析

## 資料範圍與驗證狀態

- 分析來源：`outputs/tdt_rm_v5_1_4_2022_bear_market_backtest.csv`。
- 回測區間：2022-01-03 至 2022-12-30，共 247 個交易日。
- 驗證結論：`outputs/tdt_rm_v5_1_4_2022_bear_market_validation.json` 顯示 `is_valid = true`，且觀察窗、必要欄位、price-only ETI 控制、紅燈確認規則、結果標註與摘要一致性檢查皆通過。

## 核心結論

1. **風控以 Orange 為主，而非 Red。** 2022 年樣本內 Red 訊號為 0；Orange 訊號為 150，約占 60.7%。這表示 V5.1.4 在 price-only ETI 資料限制下，透過熊市趨勢地板與穩定性規則提高防守層級，但避免由不可用 ETI 元件或 CP 單獨產生 Red。
2. **最大避險價值出現在 2022-04-13。** 當日 Signal = Orange、Close = 17301.65，後續 60 日最大跌幅為 -19.17%，對應最大 `Drawdown Avoided %` = 19.17%。
3. **False Positive 集中在 Orange。** 全年 False Positive 為 40 筆；依訊號分組計算，False Positive 全數落在 Orange，代表模型防守訊號偏早或偏保守的成本主要來自 Orange 區間。
4. **沒有 Red 是合理的審計結果。** `eti_available_count` 全期為 1，`eti_cap_reason` 顯示可用元件不超過 2 時會封頂；因此 V5.1.4 沒有把資料不足情境誤升級成 Red。

## 訊號分佈

| Signal | 交易日數 | 占比 | 平均 20D 最大跌幅 | 平均 60D 最大跌幅 | False Positive |
|---|---:|---:|---:|---:|---:|
| Green | 18 | 7.3% | -5.19% | -10.46% | 0 |
| Yellow | 43 | 17.4% | -3.81% | -6.19% | 0 |
| Strengthened Yellow | 36 | 14.6% | -6.03% | -11.09% | 0 |
| Orange | 150 | 60.7% | -4.82% | -10.77% | 40 |


## 主要狀態切換

模型全年共有 18 次狀態段落切換。早期 2022-01-03 先為 Green，2022-01-19 轉為 Yellow；第一次 Orange 出現在 2022-03-08。4 月中以後 Orange 長時間主導，直到 2022-08-15 降為 Strengthened Yellow，之後在 8–11 月間於 Orange、Strengthened Yellow 與 Yellow 之間切換。

| 日期 | 新 Signal |
|---|---|
| 2022-01-03 | Green |
| 2022-01-19 | Yellow |
| 2022-02-10 | Green |
| 2022-02-14 | Yellow |
| 2022-02-16 | Green |
| 2022-02-22 | Yellow |
| 2022-02-25 | Strengthened Yellow |
| 2022-03-08 | Orange |
| 2022-03-25 | Yellow |
| 2022-03-28 | Orange |
| 2022-08-15 | Strengthened Yellow |
| 2022-08-22 | Orange |
| 2022-08-25 | Strengthened Yellow |
| 2022-08-31 | Yellow |
| 2022-09-01 | Strengthened Yellow |
| 2022-09-19 | Orange |
| 2022-11-11 | Strengthened Yellow |
| 2022-11-24 | Yellow |


## 解讀與建議

- **防守有效性：** 最大可避免跌幅 19.17%，且最深 60D 風險點與最大避險點同日，顯示 Orange 在 2022 熊市中捕捉到重要下行風險。
- **代價：** 40 筆 False Positive 代表防守訊號存在過早啟動或短期未跌的成本；後續若要降低交易摩擦，可針對 Orange 的進出場遲滯、持有期或解除條件做敏感度測試。
- **資料限制：** 本回測是 price-only ETI 控制情境；ETI 可用元件不足使風控升級受到封頂。若接入完整 ETI、籌碼、期權與廣度資料，應重新比較 Red/Orange 分佈與 False Positive。
- **實務用法：** 在此版本中，Orange 可視為主要降風險狀態；Red 則應保留給多元 ETI/BCD/Tail Risk 互相確認後的高確信風險事件。
