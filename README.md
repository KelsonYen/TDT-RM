# 大盤風險控制評估模型

by Dr. Yen

## TCWRS 模組

本倉庫目前實作 `TDT-RM V5.1.3 Rev.3 Final Freeze` 規格書第 3 章的
TCWRS（Taiwan Crash Warning Risk Score，台股結構風險）模組。

實作原則：

- 僅實作規格書列出的 8 個 TCWRS 子因子：`P`、`V`、`F`、`X`、`M`、`B`、`L`、`G`。
- 子因子最高分固定為規格書權重：18、12、15、12、12、12、10、9，總分範圍 0–100。
- 不加入規格書以外的因子，也不調整任何權重。
- 每個子因子都保留：
  - 子因子代碼與名稱
  - 最高分
  - 實際得分（`score` / `factor_score`）
  - 命中的規則（`matched_rule`）
  - 所有中間條件與原始輸入值（`conditions` / `trace_output`）
- `score_tcwrs()` 彙總 `P + V + F + X + M + B + L + G`，並回傳 `total_score`、`factor_scores`、`factor_traces` 三個主要輸出；`total` / `factors` 仍保留為相容別名。
- 當多個風險條件同時成立時，依規格權重採用最高分的命中規則，並仍在 trace 中保留所有中間條件，確保模型分數可追蹤且可重現。
- 高估值不會被納入 `TCWRS_G`，依規格應由 `MHS_VAL_MHS` 處理。
- 指數上漲但廣度惡化不會計入 `TCWRS_B`，依規格應由 BCD 模組處理。


## ETI-5 模組

本倉庫也實作規格書第 8 章 ETI-5（Exit Trigger Index 5，風險落地確認）模組。

ETI-5 是五個二元訊號的加總，分數範圍為 0–5：

- `ETI-1`：Index below 20MA
- `ETI-2`：Foreign selling
- `ETI-3`：TWD depreciation
- `ETI-4`：Breadth deterioration
- `ETI-5`：Leadership breakdown

`score_eti5()` 回傳 `eti_score`、`triggered_signals` 與 `trace_output`，並保留規格用語 `eti5_total` 作為相容別名。

```python
from tdt_rm import ETI5Input, score_eti5

result = score_eti5(
    ETI5Input(
        close=94,
        ma20=95,
        foreign_spot_net_sell_consecutive_days=2,
        usd_twd_3d_change_pct=0.51,
        index_down=True,
        declining_issues_significantly_gt_advancing=True,
        count_main_7_below_ma20=4,
    )
)

print(result.eti_score)
print(result.triggered_signals)
print(result.trace_output)
print(result.as_dict())
```

## Crash Probability 模組

本倉庫也實作規格書第 11 章 Crash Probability（CP，崩跌機率輔助分數）模組。

`score_crash_probability()` 依照固定權重計算：

```text
CP_raw = TCWRS * 0.40 + (ETI5_total * 20) * 0.30 + TailRisk * 0.20 + BCD * 0.10
CP = min(CP_raw, 100)
```

回傳內容包含 `cp_score`、`cp_level` 與 `trace_output`；`cp_raw` 也會保留為未封頂的公式結果。

CP 等級如下：

- `Low`：0–30
- `Medium`：31–55
- `High`：56–75
- `Extreme`：76–100

```python
from tdt_rm import CrashProbabilityInput, score_crash_probability

result = score_crash_probability(
    CrashProbabilityInput(
        tcwrs=50,
        eti5_total=2,
        tail_risk=60,
        bcd=70,
    )
)

print(result.cp_score)
print(result.cp_level)
print(result.trace_output)
print(result.as_dict())
```

## Historical Backtest 模組

本倉庫新增 dependency-free 的 Historical Backtest 框架，可將歷史每日輸入列逐筆套用 TCWRS、ETI-5 與 Crash Probability，並用未來事件標籤評估訊號命中率。

`run_historical_backtest()` 會：

- 依日期排序 `HistoricalBacktestObservation`。
- 對每筆資料計算 TCWRS，並在提供 `ETI5Input`、`tail_risk` 與 `bcd` 時同步計算 ETI-5 與 CP。
- 依 `BacktestConfig.signal_mode`（`any`、`all`、`tcwrs`、`eti5`、`cp`）與門檻產生風險訊號。
- 以 `forward_window` 檢查未來 N 筆觀測內是否出現 `realized_event=True`。
- 回傳逐筆可稽核 trace 與 precision、recall、F1、false-positive rate、average lead days 等統計。

```python
from tdt_rm import (
    BacktestConfig,
    ETI5Input,
    HistoricalBacktestObservation,
    TCWRSInput,
    run_historical_backtest,
)

observations = [
    HistoricalBacktestObservation(
        observed_at="2026-01-01",
        tcwrs_input=TCWRSInput(close=94, ma5=100, ma20=95, ma60=90, ma20_slope=-1),
        eti5_input=ETI5Input(close=94, ma20=95),
        tail_risk=60,
        bcd=70,
    ),
    HistoricalBacktestObservation(
        observed_at="2026-01-05",
        tcwrs_input=TCWRSInput(close=90, ma5=95, ma20=96, ma60=92, ma20_slope=-1),
        realized_event=True,
    ),
]

result = run_historical_backtest(
    observations,
    BacktestConfig(forward_window=5, signal_mode="any", tcwrs_threshold=55),
)

print(result.metrics.as_dict())
print(result.as_dict()["signals"][0]["trace_output"])
```

## 安裝與測試

本專案使用 `src/` layout，Python 版本需求為 3.11 以上。

```bash
pip install -e .
pytest -q
```

## 使用範例

```python
from tdt_rm import TCWRSInput, score_tcwrs

data = TCWRSInput(
    close=94,
    ma5=100,
    ma20=95,
    ma60=90,
    ma20_slope=-1,
    close_below_ma20_consecutive_days=1,
    turnover_top_10pct_1y=True,
    close_is_black=True,
    foreign_spot_net_sell_consecutive_days=2,
    usd_twd_5d_change_pct=1.01,
    index_5d_return_pct=-3.01,
    margin_balance_5d_decline_pct=0.49,
    index_down=True,
    declining_issues_significantly_expand=True,
    declining_issues_significantly_gt_advancing=True,
    count_main_7_below_ma20=4,
    sox=99,
    sox_ma20=100,
    sox_ma60=90,
    nasdaq=101,
    nasdaq_ma20=100,
)

result = score_tcwrs(data)
print(result.total_score)
print(result.factor_scores)
print(result.factor_traces)
print(result.as_dict())
```

`result.as_dict()` 會輸出完整 audit trace，頂層包含 `total_score`、`factor_scores`、`factor_traces`，並保留舊版 `total` / `factors` 別名，方便回查分數來源。
