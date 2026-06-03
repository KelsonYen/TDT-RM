# One-command Daily Pipeline Guide

The daily pipeline turns manually prepared local provider files into the standard TDT-RM daily production artifacts with one operator command:

```text
provider CSVs -> assembled enriched snapshot -> daily JSON/Markdown/manifest -> validation -> operator summary
```

The pipeline reuses the existing snapshot assembler, daily production runner, manifest writer, and artifact validator. It does **not** change model scoring logic.

## One-command daily workflow

1. Prepare local provider CSV files for the trade date.
2. Run `scripts/run_daily_pipeline.py` with `--as-of`, provider inputs, and an output directory.
3. Review the terminal operator summary.
4. Treat non-zero exits as blocking production failures.
5. Archive the JSON, Markdown, manifest, and assembled snapshot artifacts.

## Example using provider CSVs

```bash
python scripts/run_daily_pipeline.py \
  --as-of 2026-05-29 \
  --price-csv examples/provider_inputs/sample_price.csv \
  --foreign-csv examples/provider_inputs/sample_foreign_flow.csv \
  --fx-csv examples/provider_inputs/sample_fx.csv \
  --breadth-csv examples/provider_inputs/sample_breadth.csv \
  --leadership-csv examples/provider_inputs/sample_leadership.csv \
  --scores-csv examples/provider_inputs/sample_scores.csv \
  --field-map examples/provider_inputs/sample_provider_field_map.json \
  --output-dir outputs/daily \
  --allow-warnings
```

`--price-csv` is required unless `--snapshot-path` is supplied. Optional provider files can be omitted when they are unavailable; missing optional fields are reported through snapshot coverage and warnings where applicable.

## Example using an existing snapshot JSON

Use `--snapshot-path` when a normalized enriched snapshot has already been assembled:

```bash
python scripts/run_daily_pipeline.py \
  --as-of 2026-05-29 \
  --snapshot-path examples/daily_snapshots/sample_enriched_snapshot.json \
  --output-dir outputs/daily \
  --allow-warnings
```

When `--snapshot-path` is supplied, provider assembly is skipped and no new assembled snapshot is written.

## Output artifacts

For trade date `2026-05-29`, the default output directory contains:

- `assembled_daily_snapshot_2026-05-29.json` — normalized provider snapshot, unless `--snapshot-path` was used.
- `tdt_rm_daily_2026-05-29.json` — daily production JSON artifact.
- `tdt_rm_daily_2026-05-29.md` — human-readable daily report.
- `tdt_rm_daily_2026-05-29_manifest.json` — manifest with validation status and data-quality metadata, unless `--no-manifest` is supplied.

Use `--snapshot-out PATH` to control the assembled snapshot path. Use `--json-summary PATH` to write the same operator summary as machine-readable JSON.

## How to read the operator summary

The summary is intentionally concise and line-oriented:

- `trade_date` — production trade date used in artifacts.
- `data_status` — snapshot data status, normally `enriched_snapshot` for assembled provider snapshots.
- `signal` and `exposure_limit` — five-light decision output and equity exposure limit.
- `TCWRS`, `MHS`, `ETI-5`, `Tail Risk`, `BCD`, `CP` — daily score values from existing scoring modules.
- `available_eti_components` — ETI components supported by sourced snapshot fields.
- `fallback_proxies` — proxy scores used for Tail Risk or BCD when formal values are absent. `{}` means no fallback proxies were used.
- `provider_warnings` — assembler warnings, including conflicts or optional coverage issues.
- `validation_status` — daily artifact validation status.
- `artifact_paths` — paths to generated JSON, Markdown, manifest, and assembled snapshot artifacts.

The CLI exits non-zero for blocking validation errors. Warning-only validation results follow the existing validation policy; `--allow-warnings` does not invent stricter blocking rules.

## Expected warnings

Warnings can include:

- Missing optional provider categories or optional fields.
- ETI components unavailable because required source fields were not supplied.
- Price-bar date mismatch warnings if supplied price history does not end on the snapshot trade date.
- Daily artifact staleness warnings when validating old trade dates.
- Price-only provisional warnings when running price-only artifacts outside the enriched provider flow.

Warnings should be reviewed, but they are not automatically promoted to blocking failures by this pipeline unless the existing validator reports blocking errors.

## Current limitations

- No ETF Exit integration is implemented in this pipeline.
- No paid API, broker login, or live scraping is added.
- MHS is passthrough only unless supplied in the scores provider or snapshot.
- Provider files still need to be manually prepared or externally generated before running the command.
