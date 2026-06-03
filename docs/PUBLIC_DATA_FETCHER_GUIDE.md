# Public Data Fetcher Guide

The public-data fetch layer generates provider CSV inputs for the existing TDT-RM daily pipeline. It is separated from scoring logic: fetchers normalize public source data into the same provider CSV schemas already consumed by `scripts/run_daily_pipeline.py`.

## Supported public sources

Configured sources live in `config/public_data_sources.json` and can be replaced without code changes.

Current adapters include:

- **TAIEX price / OHLCV**: TWSE `MI_5MINS_HIST` structured JSON endpoint for index OHLC data.
- **Local price fallback CSV/JSON**: operator-supplied files used only when configured or passed on the CLI. These files are external input data, still validated for `as_of` freshness and required price fields, and are never fabricated by the fetcher.
- **TWSE market breadth / summary**: optional TWSE `MI_INDEX` structured JSON configuration. Breadth is only written when configured fields are present.
- **TWSE foreign flow**: optional TWSE `T86` structured JSON configuration. Aggregate/model-specific fields must be deterministically mapped or the component remains unavailable.
- **TWSE margin**: optional TWSE margin-trading structured JSON configuration.
- **FX**: optional configurable public JSON endpoint placeholder for USD/TWD fields. No paid API key is used.
- **Derivatives / futures / options**: optional configurable public endpoint placeholder. No derivative-derived scores are fabricated.
- **Main-7 leadership**: optional constituent adapter. It writes `leadership.csv` only when every configured Main-7 symbol has close and MA20 data.

## Generated provider CSVs

Run `scripts/fetch_daily_provider_csvs.py` to fetch available public data and write provider inputs under the selected output directory:

- `price.csv` (required for a full daily pipeline run)
- `foreign_flow.csv` (optional)
- `fx.csv` (optional)
- `breadth.csv` (optional)
- `leadership.csv` (optional)
- `margin.csv` (optional)
- `scores.csv` only when formal or explicitly deterministic provisional score fields are supplied
- `provider_field_map.json`
- `fetch_manifest.json`

The writer omits optional CSVs when public data is unavailable, stale, malformed, or missing required fields. It records those conditions in `fetch_manifest.json` instead of filling fabricated values.

## Source configuration

`config/public_data_sources.json` contains one object per source. Multiple enabled objects may share a `provider_category`; they are tried in ascending `fallback_order` and the registry stops at the first successful source for that category. Key fields include:

- `source_id`
- `provider_category`
- `fallback_order` / legacy `priority`
- `enabled`
- `source_type` such as `twse_json`, `generic_json`, `local_csv_fallback`, or `local_json_fallback`
- `endpoint_url_template` or a local fallback `path`
- `request_parameters`
- `response_type`
- `field_extraction_mapping`
- `freshness_rules`
- `notes` / `limitations`

For tests or controlled runs, a source may use `fixture_path` instead of an endpoint. JSON and JSON-compatible YAML source configs are accepted by `--source-config`.

## Main-7 configuration

`config/main7_symbols.json` controls the leadership list. The default symbols are:

- `2330`
- `0050`
- `00878`
- `2454`
- `2317`
- `2382`
- `2308`

Edit the JSON file or pass `--main7-config` to change the list without changing code.

## Missing optional data

Only `price.csv` is required for a full production pipeline run. Optional categories are allowed to fail when `--allow-partial` is supplied; their source IDs, status, issues, and limitations are written to `fetch_manifest.json`.

Leadership is not faked. If constituent price/MA data are unavailable, `leadership.csv` is omitted and ETI-5 remains unavailable unless another successful provider supplies `count_main_7_below_ma20`.

## When live public price fetch is blocked

The price provider is required because the model must not run from fabricated or missing price data. Official public endpoints can still fail in real environments: common causes include 403 responses from endpoint-side bot/tunnel controls, corporate egress filtering, regional network restrictions, temporary TWSE service changes, or transient DNS/TLS/proxy failures. These failures are expected to block a full pipeline run unless a valid fallback source succeeds.

When price fails, `scripts/fetch_daily_provider_csvs.py` prints diagnostics headed `required provider price failed`, lists attempted price sources and failure reasons, and suggests a `--price-fallback-csv` command. `fetch_manifest.json` also records `source_attempts` with `source_id`, `provider_category`, `attempted`, `success`, `failure_reason`, `stale_status`, and `fields_extracted`.

## Local price fallback workflow

A local fallback file is operator-supplied or externally downloaded data. It is not created by the fetcher, and the fetcher will not fill missing fields. The file must contain a row for `--as-of` (or a single row whose date still passes freshness validation) and the canonical required fields such as `taiex_close`, `taiex_ma5`, `taiex_ma20`, `taiex_ma60`, and `taiex_ma20_slope`. If the fallback is stale or incomplete, `price.csv` is not written.

The repository includes `examples/provider_inputs/sample_price_fallback_2026-06-02.csv` as a deterministic fixture for tests and documentation only. It is not real production market data.

Live-first example with a local CSV fallback:

```bash
python scripts/fetch_daily_provider_csvs.py \
  --as-of 2026-06-02 \
  --output-dir inputs/daily/2026-06-02 \
  --price-fallback-csv path/to/price.csv \
  --allow-partial \
  --run-pipeline \
  --pipeline-output-dir outputs/daily
```

Offline example that skips live network sources and uses only configured/local fallback files:

```bash
python scripts/fetch_daily_provider_csvs.py \
  --as-of 2026-06-02 \
  --output-dir inputs/daily/2026-06-02 \
  --offline \
  --price-fallback-csv path/to/price.csv \
  --allow-partial
```

## Scores and fallbacks

The fetch layer does **not** invent formal Tail Risk, BCD, or MHS values.

- `scores.csv` is omitted unless formal or explicitly deterministic provisional score fields are supplied.
- When Tail Risk or BCD are absent, the existing daily pipeline records its documented `fallback_proxies`.
- MHS remains `0.0` unless a deterministic supplied field exists.
- Proxy scores are never silently labeled formal.

## Run example for 2026-06-02

```bash
python scripts/fetch_daily_provider_csvs.py --as-of 2026-06-02 --output-dir inputs/daily/2026-06-02 --allow-partial --run-pipeline --pipeline-output-dir outputs/daily
```

This writes provider CSVs under `inputs/daily/2026-06-02/` and daily production artifacts under `outputs/daily/` when required price data is available.

## Current limitations

- Public data endpoints may be delayed, temporarily unavailable, blocked by 403/network restrictions, or revised after publication.
- Some model input fields may remain unavailable because public endpoints do not expose a deterministic equivalent.
- Tail Risk / BCD / MHS may remain unavailable, provisional, or covered by the existing pipeline fallback behavior.
- No ETF Exit policy is implemented.
- No paid API, broker login, credentialed integration, browser automation, or unstable HTML scraping is used.
