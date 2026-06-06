# TDT-RM Daily Production Runbook

This runbook describes the reproducible daily path for running TDT-RM V5.1.4 from a local enriched daily market snapshot through production artifacts, manifest creation, and validation. It is an operator workflow only; it does not change model scoring logic, TCWRS weights, ETI-5 rules, Crash Probability, Bear Trend Filter, CAL, or the five-light decision matrix.

## Daily workflow overview

1. Collect or locally generate the daily market inputs after the trading session closes.
2. Build an enriched snapshot that contains the canonical price fields and any available foreign-flow, USD/TWD, breadth, leadership, Tail Risk, BCD, and optional MHS fields.
3. Normalize the snapshot with `scripts/build_daily_snapshot.py` when starting from CSV or when you want a validation block embedded in the snapshot JSON.
4. Run daily production with `scripts/run_daily_production.py --snapshot-path ...`.
5. Validate the generated JSON and Markdown artifacts with `scripts/validate_daily_production.py`.
6. Review the manifest and source-coverage fields before distributing the operator report.
7. Optionally run `scripts/smoke_daily_production.py` to exercise the full path in one command and print a concise operator summary.

## Prepare an enriched snapshot

The normalized snapshot shape is documented by the example fixtures in `examples/daily_snapshots/`:

- `sample_enriched_snapshot.json` is a complete one-day enriched snapshot.
- `sample_enriched_snapshot.csv` is a single-row CSV using canonical names and documented aliases.
- `sample_field_map.json` demonstrates how vendor CSV headers can be mapped into canonical fields.

A production enriched snapshot should include:

- `trade_date` and `observed_at`.
- `canonical_row.close`, `canonical_row.ma5`, `canonical_row.ma20`, `canonical_row.ma60`, and `canonical_row.ma20_slope`.
- Optional but recommended TCWRS/ETI fields for foreign flow, USD/TWD movement, market breadth, and leadership breakdown.
- Formal `tail_risk` values when available. BCD is computed internally only; missing independent BCD inputs produce `bcd=null` and `bcd_status=INCOMPLETE`.
- Optional `mhs`. The runner uses this value when supplied; otherwise it defaults to `0.0` because no formal MHS scorer is implemented in this repository.
- `field_sources` mapping each supplied canonical field to a source identifier.
- `source_metadata` describing local data collection jobs, timestamps, and notes.
- `data_status`, `limitations`, and `warnings` so the operator report can preserve provenance and caveats.

## Normalize CSV or JSON snapshot input

Normalize the sample CSV fixture into a JSON snapshot:

```bash
python scripts/build_daily_snapshot.py \
  --input-csv examples/daily_snapshots/sample_enriched_snapshot.csv \
  --field-map examples/daily_snapshots/sample_field_map.json \
  --output-json /tmp/tdt_rm_sample_snapshot.json \
  --as-of 2026-05-29 \
  --validate
```

Normalize an existing JSON snapshot and write the validation block:

```bash
python scripts/build_daily_snapshot.py \
  --input-json examples/daily_snapshots/sample_enriched_snapshot.json \
  --output-json /tmp/tdt_rm_sample_snapshot.json \
  --as-of 2026-05-29 \
  --validate
```

The field map is a JSON object whose keys are canonical TDT-RM fields and whose values are raw CSV headers. Built-in aliases such as `taiex_close`, `index_ma20`, and `usdtwd_3d_change_pct` can be used without a field map, but a field map is recommended for vendor-specific files.

## Run daily production with `--snapshot-path`

Run production from an enriched snapshot:

```bash
python scripts/run_daily_production.py \
  --snapshot-path /tmp/tdt_rm_sample_snapshot.json \
  --as-of 2026-05-29 \
  --output-dir outputs/daily
```

The command writes:

- `tdt_rm_daily_<trade_date>.json`
- `tdt_rm_daily_<trade_date>.md`
- `tdt_rm_daily_<trade_date>_manifest.json` when the runner is called with manifest writing enabled. The CLI smoke script enables this automatically.

## Validate generated artifacts

Validate the JSON and Markdown pair:

```bash
python scripts/validate_daily_production.py \
  --json-path outputs/daily/tdt_rm_daily_2026-05-29.json \
  --markdown-path outputs/daily/tdt_rm_daily_2026-05-29.md \
  --as-of 2026-05-29 \
  --manifest-out outputs/daily/tdt_rm_daily_2026-05-29_manifest.json
```

Validation exits non-zero only for blocking errors. Warnings are intended to remain visible to operators while allowing usable reports to pass.

## Operator smoke test

The smoke script runs the enriched snapshot through production, checks that JSON, Markdown, and manifest artifacts exist, runs the validation gate, and prints the operational summary fields:

```bash
python scripts/smoke_daily_production.py \
  --snapshot-path examples/daily_snapshots/sample_enriched_snapshot.json \
  --output-dir /tmp/tdt_rm_daily_smoke \
  --as-of 2026-05-29
```

The summary includes `trade_date`, `signal`, `exposure_limit`, `TCWRS`, `ETI-5`, `Tail Risk`, `BCD`, `CP`, `data_status`, `fallback_proxies`, and `validation_status`.

## Read the manifest

The manifest records the run and validation context:

- `run_timestamp`: when the manifest was written.
- `model_version` and `trade_date`: model/run identity.
- `data_source` and `data_status`: whether the run used price-only public data or an enriched snapshot.
- `artifact_paths`: JSON and Markdown artifact paths.
- `validation_status` and `validation`: gate outcome, warning count, error count, and issue details.
- `data_quality.fallback_proxies`: formal Tail Risk fallback usage and BCD incomplete status. Provider BCD must never be supplied.
- `data_quality.available_eti_components`: ETI components with source fields present in the snapshot.
- `data_quality.field_sources` and `source_metadata`: source attribution preserved from the snapshot.

## Interpret `price_only_provisional` versus enriched snapshot runs

A default run without `--snapshot-path` downloads public TAIEX price bars and marks `data.status` as `price_only_provisional`. In that mode, only ETI-1 price data is available, Tail Risk and BCD use documented price-only fallback proxies, and MHS is `0.0`.

An enriched snapshot run marks `data.status` from the snapshot, usually `enriched_snapshot`. ETI availability is derived from supplied source fields. When formal `tail_risk` is present and independent BCD inputs are complete, `data.fallback_proxies` should be empty; if BCD inputs are incomplete, the runner records `incomplete_bcd` without using a provider fallback.

## Current limitations

- MHS scorer is not formalized unless `mhs` is supplied in the snapshot; otherwise MHS remains `0.0`.
- ETF Exit is not integrated and remains an explicit placeholder in daily artifacts.
- Provider automation is not implemented; no paid API, broker login, or credentialed provider integration is part of this workflow.
- Source fields must still be manually supplied or locally generated before snapshot normalization.
