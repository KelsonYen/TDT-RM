# Production Gap Report — Seven Daily Production CSVs

_盤點日期：2026-06-04。範圍：`price.csv`、`foreign_flow.csv`、`fx.csv`、`breadth.csv`、`futures.csv`、`options.csv`、`leadership.csv`。_

## Executive summary

目前 repo 已有 public provider fetcher 與 parser，可在具備核准外部網路的環境中嘗試抓取七類資料；官方來源映射也已定義於 production provider 文件與 `config/public_data_sources.json`。但是，嚴格 production/local import 路徑要求七份 CSV 必須含 `trade_date`、`provider_source`、`source_type` 與 strict schema 欄位，且 Codex runtime 不應假設能直接連 TWSE/TAIFEX/FinMind。

因此，依「能否直接產出可通過 strict production validator 的七份 CSV」判定：**目前七份都仍需要人工匯入或由外部受控環境產生後匯入**。依「repo 內是否已有自動抓取與部分標準化能力」判定：`price.csv`、`foreign_flow.csv`、`fx.csv`、`breadth.csv`、`leadership.csv` 屬於 **部分自動化 / 接近可自動化**；`futures.csv`、`options.csv` 屬於 **原始市場資料可抓，但 production decision 欄位尚未自動推導**。

## 判定基準

- **全自動 production-ready**：排程每日自動抓取、轉成 strict CSV schema、帶有真實 `provider_source`/`source_type`、通過 `scripts/validate_daily_input_csvs.py`，並可直接餵給 `scripts/run_daily_production_pipeline.py --input-dir`。
- **部分自動化**：已有 official/public adapter 可抓或可 parser，但輸出仍是 legacy provider schema、缺 strict 欄位、缺 provenance、缺衍生規則，或受 Codex runtime 網路限制阻擋。
- **人工匯入**：目前 production runbook 要求 operator 在 Codex 外部下載/轉檔後放入 `inputs/daily/YYYY-MM-DD/`。

## Current production posture

1. Strict local/import mode 固定要求七份檔案：`price.csv`、`foreign_flow.csv`、`fx.csv`、`breadth.csv`、`futures.csv`、`options.csv`、`leadership.csv`。
2. Validator 會拒絕缺檔、空檔、日期不符、缺 `provider_source`、缺 `source_type`，或 `source_type` 為 fallback/mock/fixture/synthetic/neutral/sample/test。
3. Production provider fetcher 目前會寫 legacy provider CSV 與 manifest/health 檔，但 `write_provider_csvs()` 寫出的欄位以 `date` 與 provider-specific 欄位為主，沒有保證產出 strict local/import schema 所需的 provenance 欄位。
4. Codex runtime 已被文件化為不可假設有可用 HTTPS egress；因此 Codex 驗證與日常 production 應採用離線/本地 CSV 路徑。

## Dataset gap matrix

| CSV | Official / configured source | Current automation level | Blocking points | Work needed for full daily automation |
| --- | --- | --- | --- | --- |
| `price.csv` | TWSE `FMTQIK` monthly market summary；fallback：TWSE `MI_5MINS_HIST` | **部分自動化**。Adapter 可抓多月資料並用 `derive_price_features()` 算 close、MA5/20/60、MA20 slope、1D/2D return、turnover。 | Strict schema 仍需 `close_below_ma20_consecutive_days`、`index_5d_return_pct`、`return_60d_pct`、`previous_ma60`；public writer 目前輸出 `date`/`taiex_*` legacy 欄位，不輸出 `trade_date`、`provider_source`、`source_type`；Codex runtime 不能假設能連 TWSE。 | 擴充 price feature derivation 與 strict CSV writer；把 source_id/source_type 寫入 provenance 欄；加入 61+ trading-day history 以算 60D return/previous MA60；在受控網路排程抓取並落地 strict CSV。 |
| `foreign_flow.csv` | TWSE `T86` institutional flow report | **部分自動化**。Adapter 可 aggregate 外資買賣超並產生 large-sell flags。 | Parser 目前將 `foreign_spot_net_sell` 當 boolean fallback，而 strict schema 視為 numeric；連賣天數需要多日 T86 lookback，目前 config 未明確要求多日 payload；缺 provenance strict 欄；Codex runtime 網路受限。 | 將 net buy/sell 拆成 numeric buy amount 與 sell amount；新增 N 日 lookback 以計算 consecutive sell days；補 strict writer/provenance；新增 live/fixture tests 驗證正負值與單位。 |
| `fx.csv` | TAIFEX `DailyForeignExchangeRates` OpenAPI | **部分自動化，接近 production-ready**。Adapter 可取 USD/TWD 並推導 3D/5D change、TWD appreciates/stable/depreciates flags。 | Strict CSV 仍缺 `trade_date`、`provider_source`、`source_type` writer；需確保 endpoint 回傳足夠日序列與 holiday handling；Codex runtime 網路受限。 | 加 strict CSV writer；正式定義缺交易日/假日回補策略；在 production network 排程抓取並記錄 provider health。 |
| `breadth.csv` | TWSE `MI_INDEX` after-trading market report | **部分自動化**。Adapter 可解析 advancing/declining issues、`index_down` 與 `declining_issues_significantly_gt_advancing`。 | `declining_issues_significantly_expand` 與 `breadth_weakens_for_2_days` 需要前日/多日 breadth history；目前 parser 單日邏輯不足；缺 strict provenance；Codex runtime 網路受限。 | 新增 breadth history cache/lookback；明文化「顯著擴大」與「連續 2 日轉弱」門檻；輸出 strict schema；加入 MI_INDEX parser regression fixtures。 |
| `futures.csv` | TAIFEX `DailyMarketReportFut` OpenAPI | **原始資料可自動抓，但 production 欄位尚未自動化**。Adapter 目前輸出 TX/TXF close、settlement、volume、open interest、basis/source contract。 | Strict schema 需要 `futures_hedging_increases`、`futures_hedging_significant`、`futures_net_short_increases`、`futures_net_short_decreases`，但目前 public parser 沒有把 raw futures/OI/法人部位轉成這四個 boolean；source selection 也可能需要法人/大額交易人資料，而非單純 daily market report。 | 確認 production 定義：避險增加、顯著避險、淨空單增減的官方資料表與門檻；新增 TAIFEX institutional/large-trader source（如適用）；建立 derived-signal transformer 與 strict writer；加入多日 OI/net-short history。 |
| `options.csv` | TAIFEX `PutCallRatio` 與 `TAIFEXVIX` OpenAPI | **原始資料可自動抓，但 production 欄位尚未自動化**。Adapter 可取 PCR、put/call volume、TAIFEX VIX。 | Strict schema 需要 `pcr_stable`、`pcr_rises`、`vix_stable`、`vix_rises`、`tail_risk`、`bcd`；目前 parser 未定義 PCR/VIX 穩定或上升門檻，也沒有 formal Tail Risk / BCD source；public manifest 已指出未供應 formal scores 時 pipeline 只能用既有 fallback 行為。 | 定義 PCR/VIX lookback 與門檻；串接 formal Tail Risk / BCD 或明確標記 deterministic provisional scores；將 options raw data 轉成 strict booleans + scores；補 score provenance 與禁止 mock/fallback。 |
| `leadership.csv` | TWSE `STOCK_DAY` per Main-7 constituent | **部分自動化**。Adapter 可逐檔抓 4 個月歷史，計算 Main-7 below MA20/MA60 counts 與 below-MA20 symbols。 | Strict schema 另需 `mhs`；目前 leadership adapter 不產 MHS；若任一 Main-7 構成股少於 60 日 history，整體回報 missing_fields；需維護 Main-7 symbol config 與處理停牌/缺值；缺 strict provenance；Codex runtime 網路受限。 | 定義並實作 MHS 來源/算法；維護 `main7_symbols` 版本化設定；加入 per-symbol cache、缺值容忍/停牌規則；輸出 strict schema/provenance。 |

## Automation readiness buckets

### A. 已有自動抓取與 parser，但仍非 strict production-ready

- `price.csv`
- `foreign_flow.csv`
- `fx.csv`
- `breadth.csv`
- `leadership.csv`

這些資料集已有 official source adapter 或 parser，主要差距是：strict CSV writer、provenance 欄位、部分衍生欄位/多日 lookback，以及 production network 排程。

### B. 原始資料可抓，但 production signal 欄位仍需規格與 transformer

- `futures.csv`
- `options.csv`

這兩份目前 public fetcher 偏向輸出原始 derivatives/options market data；strict production CSV 要的是決策欄位或 formal/provisional scores，因此必須先定義衍生規則與資料來源，再談每日全自動。

### C. 目前 strict production run 仍需人工匯入

- 七份全部仍需人工或外部受控 pipeline 產出後匯入 Codex/local production path。

原因不是 repo 完全沒有 fetcher，而是 strict production 的 acceptance gate 要求七份可驗證 CSV，而現有 public fetcher 輸出與 strict schema/網路假設尚未完全接軌。

## Recommended implementation plan

1. **新增 strict production CSV writer**：在 public fetch result 成功後，輸出 `trade_date`、`provider_source`、`source_type` 與 strict schema 欄位，不再只輸出 legacy `date`/provider-specific 欄位。
2. **補齊 price strict features**：加入 close-below-MA20 consecutive days、5D index return、60D return、previous MA60；最低 history 改成足以覆蓋 61+ trading days。
3. **建立多日 history/cache 層**：foreign_flow、breadth、fx、futures、options 都需要 lookback，不能只依賴單日 row。
4. **定義 derivatives/options signal 規格**：把 TXF/OI/net-short/PCR/VIX 轉成 strict booleans，並確認 Tail Risk/BCD 的正式或 deterministic provisional 來源。
5. **定義 MHS production source**：決定 MHS 是否由 leadership、external risk 或 manual formal score provider 供應；若要自動化，需實作算法與 provenance。
6. **在 production network/CI 執行抓取**：Codex runtime 僅驗證已落地 CSV；每日排程應在有 DNS、HTTPS egress、proxy policy 與必要憑證的環境執行。
7. **加 acceptance tests**：每個 dataset 使用 fixture 驗證「fetch → strict CSV → `validate_daily_input_csvs` → `run_daily_production_pipeline --input-dir`」全鏈路。

## Definition of done for “全自動每日更新”

- 每個交易日排程在收盤後抓取七類官方資料。
- 產出七份 strict CSV，全部含 `trade_date`、`provider_source`、`source_type` 與完整欄位。
- `source_type` 不使用 forbidden fallback/mock/fixture labels。
- `fetch_manifest.json` / `provider_health.json` 記錄來源、freshness、失敗嘗試與 cache 狀態。
- `python scripts/validate_daily_input_csvs.py --trade-date YYYY-MM-DD --input-dir inputs/daily/YYYY-MM-DD` 必須通過。
- `python scripts/run_daily_production_pipeline.py --trade-date YYYY-MM-DD --input-dir inputs/daily/YYYY-MM-DD --reports-dir reports/daily/YYYY-MM-DD` 必須通過，且不使用 fabricated neutral rows。
