# Daily Public-Data Provider Guide

This guide describes the local/public-data provider layer added for assembling an enriched `DailyMarketSnapshot`. The provider layer is intentionally separated from scoring and validation: providers normalize source rows, the assembler merges them, `validate_daily_snapshot()` validates the result, and the existing daily runner performs scoring.

## Provider architecture

The provider module lives in `src/tdt_rm/daily_providers.py` and exposes:

- `DailySourceProvider`: protocol implemented by every source adapter.
- `DailyProviderCapability`: category, fields, source kind, and precedence declaration.
- `DailyProviderContext`: runtime date and optional field maps.
- `DailyProviderResult`: canonical fields plus source metadata, warnings, limitations, and provider errors.
- `DailyProviderRegistry`: small auditable registry for source adapters.
- `DailySnapshotAssembler`: calls providers, merges canonical fields, records conflicts, and validates the snapshot.
- `DailySnapshotAssemblyResult`: assembled snapshot, validation result, supplied-provider list, warnings, conflicts, provider errors, and missing source categories.

Each provider exposes:

```python
provider_id
provider_name
capabilities
fetch_or_load(context: DailyProviderContext) -> DailyProviderResult
```

Implemented source adapters:

- `StaticMappingProvider` for in-memory canonical or alias-mapped rows.
- `LocalCsvProvider` for one-row or `--as-of` date-filtered CSV sources.
- `LocalJsonProvider` for one JSON object, a snapshot-style JSON object with `canonical_row`, or a date-filtered list of objects.
- `TAIEXPriceProvider` for local TAIEX price bars or one-row derived price fields. When bars are supplied, it reuses `derive_price_features()` from `tdt_rm.market_data`.
- `ManualScoreProvider` for formal/manual `tail_risk`, `bcd`, and optional `mhs` values.

## Mapping source files into canonical fields

All provider rows are normalized into the same flat `canonical_row` consumed by `DailyMarketSnapshot` and `ingest_market_data_row()`.

Common canonical groups:

| Category | Examples |
| --- | --- |
| `price` | `observed_at`, `close`, `ma5`, `ma20`, `ma60`, `ma20_slope`, returns, turnover |
| `foreign_flow` | `foreign_spot_net_sell_consecutive_days`, `foreign_large_sell`, futures hedging flags |
| `fx` | `usd_twd_3d_change_pct`, `usd_twd_5d_change_pct` |
| `breadth` | `index_down`, advancing/declining issue counts, ETI breadth flags, leadership breakdown counts |
| `margin` | margin balance, 5-day index return, retail leverage flags |
| `scores` | formal/manual `tail_risk`, `bcd`, and optional `mhs` |

A field-map JSON can contain global mappings and category/provider-scoped mappings. See `examples/provider_inputs/sample_provider_field_map.json`.

## Precedence rules and conflict handling

The assembler never silently overwrites a canonical field with a different value. If two providers emit different values for the same canonical field, the conflict is recorded in:

- `DailySnapshotAssemblyResult.conflicts`
- `DailyMarketSnapshot.warnings`
- the CLI output and the output JSON `assembly.conflicts`

Default precedence:

1. Explicit manual/formal source rows win over auto-derived fields.
2. Formal `tail_risk` and `bcd` from `ManualScoreProvider` win over proxy score values.
3. `TAIEXPriceProvider` wins for price and moving-average base fields over generic auto providers.
4. Proxy fields have the lowest precedence.
5. Equal-precedence conflicts keep the first value and record an auditable warning.

## Assemble from local CSV files

```bash
python scripts/assemble_daily_snapshot.py \
  --as-of 2026-05-29 \
  --price-csv examples/provider_inputs/sample_price.csv \
  --foreign-csv examples/provider_inputs/sample_foreign_flow.csv \
  --fx-csv examples/provider_inputs/sample_fx.csv \
  --breadth-csv examples/provider_inputs/sample_breadth.csv \
  --margin-csv examples/provider_inputs/sample_margin.csv \
  --scores-csv examples/provider_inputs/sample_scores.csv \
  --field-map examples/provider_inputs/sample_provider_field_map.json \
  --output-json outputs/daily/assembled_snapshot_2026-05-29.json \
  --validate \
  --allow-warnings
```

The CLI writes normalized snapshot JSON and prints:

- `trade_date`
- `data_status`
- supplied providers
- missing field categories
- available ETI components
- Tail Risk source
- BCD source
- warning count and warning details

With `--validate`, blocking validation errors exit non-zero. Warning-only snapshots also exit non-zero unless `--allow-warnings` is supplied.

## Run production and validation from an assembled snapshot

Pass the assembled snapshot into the existing snapshot-path workflow:

```bash
python scripts/run_daily_production.py \
  --as-of 2026-05-29 \
  --snapshot-path outputs/daily/assembled_snapshot_2026-05-29.json \
  --output-dir outputs/daily

python scripts/validate_daily_production.py \
  --json-path outputs/daily/tdt_rm_daily_2026-05-29.json \
  --markdown-path outputs/daily/tdt_rm_daily_2026-05-29.md \
  --as-of 2026-05-29 \
  --manifest-out outputs/daily/tdt_rm_daily_2026-05-29_manifest.json
```

The daily runner continues to use the existing scoring modules exactly as before. The provider layer only prepares data and provenance.

## Current limitations

- Public live provider automation is still limited; this task focuses on local deterministic source files and the provider interface.
- No paid API integration is included.
- No broker login or credentialed-service integration is included.
- No unstable scraping flow is included.
- ETF Exit policy is not implemented here.
- MHS is passthrough only unless supplied in a local/manual score row.
