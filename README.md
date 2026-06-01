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
  - 實際得分
  - 命中的規則
  - 所有中間條件與原始輸入值
- 條件判斷順序依照規格書 pseudocode 的 `IF / ELIF` 順序執行，確保模型分數可追蹤且可重現。
- 高估值不會被納入 `TCWRS_G`，依規格應由 `MHS_VAL_MHS` 處理。
- 指數上漲但廣度惡化不會計入 `TCWRS_B`，依規格應由 BCD 模組處理。

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
print(result.total)
print(result.as_dict())
```

`result.as_dict()` 會輸出完整 audit trace，包含所有子因子的中間計算欄位，方便回查分數來源。
