# 大盤風險控制評估模型

by Dr. Yen

本倉庫收錄 **TDT-RM V5.1.3 Rev.3 Final Freeze** 規格，並提供一個可直接執行的 Python 程式，將每日模型分數轉成燈號、曝險上限，並可用收盤價序列做策略回撤（drawdown）檢查。

## 程式檔案

- `TDT-RM-V5.1.3-Rev3-Final-Freeze.md`：凍結版模型規格。
- `tdt_rm.py`：模型決策與回撤/回測 CLI 程式。
- `examples/sample_input.csv`：可直接試跑的輸入範例。
- `tests/test_tdt_rm.py`：核心決策與回撤計算測試。

## CSV 輸入格式

必要欄位：

| 欄位 | 說明 |
|---|---|
| `date` | 資料日期 |
| `tcwrs` | TCWRS 風險分數 |
| `mhs` | MHS 市場熱度分數 |
| `eti5_total` | ETI-5 總分，0–5 |
| `tail_risk` | Tail Risk 分數 |
| `bcd` | BCD 分數 |

選填欄位：

| 欄位 | 說明 |
|---|---|
| `taiex` | 加權指數位置；未填時會用 `close` |
| `ma20` | 20 日均線，供 BCD 狀態機判斷 |
| `ma60` | 60 日均線，供 BCD 狀態機判斷 |
| `consecutive_down_days` | 連跌天數 |
| `taiex_not_below_ma60_for_2_days` | 是否連續 2 日未跌破 60 日線 |
| `taiex_rebounds_from_below_ma60` | 是否從 60 日線下方反彈 |
| `taiex_back_above_ma60` | 是否已站回 60 日線 |
| `close` | 收盤價；執行 `backtest` 時必填 |

## 產生每日燈號

```bash
python tdt_rm.py evaluate examples/sample_input.csv --format json
```

也可以輸出成 CSV：

```bash
python tdt_rm.py evaluate examples/sample_input.csv --output daily_signals.csv
```

## 計算回撤 / 回測

`backtest` 會以前一天燈號的曝險上限套用到隔日收盤報酬，輸出策略累積報酬、買進持有報酬、最大回撤與最差回撤日期。

```bash
python tdt_rm.py backtest examples/sample_input.csv --output equity_curve.csv
```

預設曝險權重採用各燈號區間的保守上限：

| 燈號 | 回測曝險權重 |
|---|---:|
| 綠燈 | 1.00 |
| 黃燈 | 0.80 |
| 黃燈強化 | 0.70 |
| 橘燈 | 0.50 |
| 紅燈 | 0.30 |

## 執行測試

```bash
python -m unittest discover -s tests -v
```
