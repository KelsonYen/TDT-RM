# Public Data Fetcher Guide

The public-data fetch layer generates provider CSV inputs for the existing TDT-RM daily pipeline. It is separated from scoring logic: fetchers normalize public source data into the same provider CSV schemas already consumed by `scripts/run_daily_pipeline.py`.

## Supported public sources

Configured sources live in `config/public_data_sources.json` and can be replaced without code changes.

Current adapters include:

- **TAIEX price / OHLCV**: TWSE `MI_5MINS_HIST` structured JSON endpoint for index OHLC data.
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

`config/public_data_sources.json` contains one object per source:

- `source_id`
- `provider_category`
- `endpoint_url_template`
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

- Public data endpoints may be delayed, temporarily unavailable, or revised after publication.
- Some model input fields may remain unavailable because public endpoints do not expose a deterministic equivalent.
- Tail Risk / BCD / MHS may remain unavailable, provisional, or covered by the existing pipeline fallback behavior.
- No ETF Exit policy is implemented.
- No paid API, broker login, credentialed integration, browser automation, or unstable HTML scraping is used.
