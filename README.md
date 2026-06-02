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



## 2022 Bear Market Backtest Validation

`backtest_2022_bear_market.py` runs the V5.1.4 2022 TAIEX bear-market backtest, and `validate_2022_bear_market.py` validates the generated CSV/summary artifacts against the V5.1.4 acceptance gates.

```bash
python scripts/backtest_2022_bear_market.py
python scripts/validate_2022_bear_market.py
```

The validation command checks the expected 247-session window, price-only ETI availability controls, red-signal confirmation gates, populated forward drawdown/false-positive annotations, and CSV/summary aggregate agreement. It writes `outputs/tdt_rm_v5_1_4_2022_bear_market_validation.json` and exits non-zero if any gate fails.



## COVID Crash 2020 Stress Test

`stress_test_covid_crash_2020.py` replays the 2020 TAIEX COVID-crash window with the same dependency-free, price-proxy stress harness used by the 2022 bear-market script.  It writes an auditable daily CSV and JSON summary under `outputs/` by default:

```bash
python scripts/stress_test_covid_crash_2020.py
```

The embedded tape covers 2020-02-03 through 2020-04-13 and seeds the pre-crash high with the January 2020 TAIEX peak close so drawdown-derived Tail Risk and BCD proxies reflect the pre-COVID high-water mark.


## Market Data Ingestion 模組

本倉庫新增 dependency-free 的 Market Data Ingestion layer，可將券商、資料商或 CSV 欄位正規化為模型可直接使用的 `TCWRSInput`、`ETI5Input`，並保留資料完整性與原始列 trace。

`ingest_market_data_row()` / `load_market_data_csv()` 支援：

- 常見欄位別名（例如 `date`、`taiex_close`、`taiex_ma20`）。
- 自訂 `field_map`，將 vendor 欄名映射到模型標準欄位。
- ETI-5 欄位可共用 TCWRS 的 `close` / `ma20`，也可用 `eti5_close` / `eti5_ma20` 覆寫。
- `tail_risk`、`bcd` 與 `realized_event` 可一併匯入，方便接續 Crash Probability 與 historical backtest。
- `historical_input_schema()` 可輸出機器可讀的 historical CSV schema（欄位名稱、型別、必填狀態與別名）。
- `validate_market_data_csv()` / `validate_market_data_rows()` 可在匯入前彙整所有 row-level validation issue，不會只停在第一筆錯誤。
- `load_historical_input_csv()` 可直接讀取 historical CSV 並轉成 `HistoricalBacktestObservation`，方便接續 `run_historical_backtest()`。
- `derive_price_features()` 可由 60 筆以上日線 bar 產生 `close`、`ma5`、`ma20`、`ma60`、`ma20_slope`、報酬率與 20 日均量/成交值。

```python
from tdt_rm import ingest_market_data_row, score_tcwrs

observation = ingest_market_data_row(
    {
        "date": "2026-01-05",
        "taiex_close": "94",
        "taiex_ma5": "100",
        "taiex_ma20": "95",
        "taiex_ma60": "90",
        "taiex_ma20_slope": "-1",
        "foreign_spot_net_sell_consecutive_days": "2",
        "usd_twd_3d_change_pct": "0.6",
        "index_down": "true",
        "declining_issues_significantly_gt_advancing": "1",
        "count_main_7_below_ma20": "4",
        "tail_risk": "60",
        "bcd": "70",
    },
    require_eti5=True,
    require_crash_probability=True,
)

result = score_tcwrs(observation.tcwrs_input)
print(observation.data_status)
print(result.total_score)
print(observation.as_dict()["completeness"])
```

### Historical CSV input format

Historical CSV 是 flat row 格式；每一列代表一個交易日的可用輸入快照。最小必填欄位如下：

```csv
date,taiex_close,taiex_ma5,taiex_ma20,taiex_ma60,taiex_ma20_slope,realized_event
2026-01-05,94,100,95,90,-1,no
2026-01-06,90,95,96,92,-1,yes
```

必填欄位可使用 canonical name 或內建 alias：

| Canonical 欄位 | 常見 alias | 型別 | 說明 |
| --- | --- | --- | --- |
| `observed_at` | `date`, `trade_date`, `資料日期` | date | 交易/觀測日期，支援 `YYYY-MM-DD` 與 `YYYY/MM/DD`。 |
| `close` | `taiex_close`, `index_close`, `收盤價` | float | 指數收盤價。 |
| `ma5` | `taiex_ma5`, `index_ma5` | float | 5 日均線。 |
| `ma20` | `taiex_ma20`, `index_ma20` | float | 20 日均線。 |
| `ma60` | `taiex_ma60`, `index_ma60` | float | 60 日均線。 |
| `ma20_slope` | `taiex_ma20_slope`, `index_ma20_slope` | float | 當日 MA20 減前一日 MA20。 |

選填欄位包含其他 `TCWRSInput` / `ETI5Input` 欄位、`tail_risk`、`bcd` 與 `realized_event`。ETI-5 可共用 `close` / `ma20`，也可用 `eti5_close` / `eti5_ma20` 覆寫。

```python
from tdt_rm import (
    historical_input_schema,
    load_historical_input_csv,
    run_historical_backtest,
    validate_market_data_csv,
)

# Inspect the accepted schema.
schema = [field.as_dict() for field in historical_input_schema()]

# Validate first to collect all row errors.
validation = validate_market_data_csv("historical.csv")
if not validation.is_valid:
    print(validation.as_dict()["issues"])

# Load directly into backtest observations.
observations = load_historical_input_csv("historical.csv")
result = run_historical_backtest(observations)
print(result.metrics.as_dict())
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

## Performance Report

`generate_performance_report.py` compares the existing signal CSV against a fully invested baseline and writes both Markdown and JSON output.  The default comparison uses the 2022 bear-market CSV, treats `Red` and `Orange` as risk-off TDT-RM signals, applies signals to the next observed session to avoid same-day lookahead, and reports CAGR, max drawdown, annualized Sharpe Ratio, and signal count.

```bash
python scripts/generate_performance_report.py
```

Default outputs:

- `outputs/tdt_rm_v5_1_3_2022_performance_report.md`
- `outputs/tdt_rm_v5_1_3_2022_performance_report.json`

## Daily Production Runner

`scripts/run_daily_production.py` runs the frozen `TDT-RM V5.1.4` model as a daily production job. It downloads the latest public TAIEX index bars from TWSE, derives the required price features, runs the existing TCWRS, ETI-5, Crash Probability, Bear Trend, and five-light decision matrix modules, and writes both JSON and Markdown artifacts under `outputs/daily/`.

```bash
python scripts/run_daily_production.py
```

Optional arguments:

```bash
python scripts/run_daily_production.py --as-of 2026-06-02 --output-dir outputs/daily
```

Each daily JSON/Markdown output includes:

- timestamp
- market regime
- TCWRS
- MHS
- ETI-5
- Tail Risk
- BCD
- CP
- signal and equity exposure limit
- trace output for the underlying V5.1.4 scoring modules
- an `etf_exit` placeholder reserved for future ETF Exit integration

The runner is an orchestration layer only and does not modify model scoring logic. Because this repository does not yet contain standalone formal MHS, Tail Risk, or BCD scorer modules, the daily production runner marks the data as `price_only_provisional`: ETI-5 is limited to available ETI-1 price data, Tail Risk/BCD use the existing price-only proxy approach from the scenario scripts, and MHS is set to `0.0` until a formal scorer or external input is integrated.

## Daily production validation

`run_daily_production.py` runs the dependency-free TDT-RM V5.1.4 daily production path against the latest available public TWSE TAIEX price bars. By default, it writes the JSON report, Markdown operator report, and a production validation manifest under `outputs/daily/`:

```bash
python scripts/run_daily_production.py
```

You can pin the data download date or output directory when needed:

```bash
python scripts/run_daily_production.py --as-of 2026-06-02 --output-dir outputs/daily
```

To validate already-written daily artifacts, run the standalone validation gate:

```bash
python scripts/validate_daily_production.py \
  --json-path outputs/daily/tdt_rm_daily_YYYY-MM-DD.json \
  --markdown-path outputs/daily/tdt_rm_daily_YYYY-MM-DD.md \
  --as-of YYYY-MM-DD \
  --manifest-out outputs/daily/tdt_rm_daily_YYYY-MM-DD_manifest.json
```

The optional `--as-of` argument applies the same stale-data gate used by the daily runner manifest: recent lag is reported as a warning, while older stale data is a blocking validation error.

The manifest records the run timestamp, model version, trade date, data source and status, artifact paths, optional command/git SHA metadata, and the validation result. `validation_status` means:

- `passed`: no validation warnings or blocking errors.
- `warning`: artifacts are usable, but operators should review warnings such as stale data or provisional data status.
- `failed`: at least one blocking error exists; do not treat the daily artifacts as usable operator output until corrected.

Current production limitations remain explicit in the artifacts and manifest: daily data is `price_only_provisional`, and ETF Exit is still a `not_integrated` placeholder. This validation layer does not implement ETF-specific exit policy and does not change model scoring logic, TCWRS weights, ETI-5 rules, Bear Trend Filter, CAL, Crash Probability, or the decision matrix.
