#!/usr/bin/env python
"""Historical production replay framework for the TDT-RM daily pipeline.

The replay framework validates production orchestration over historical dates
using only historical/local inputs: read-only provider cache entries,
operator-supplied fallback fixtures, existing snapshots, and provider CSVs. It
never performs live internet fetches and does not change model scoring logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_pipeline import run_daily_pipeline  # noqa: E402
from tdt_rm.public_data_fetchers import (  # noqa: E402
    PublicDataFetchContext,
    PublicDataFetchResult,
    PublicDataFetcherRegistry,
    load_main7_symbols,
    load_source_config,
    write_provider_csvs,
)

SUCCESS = "success"
PROVIDER_FAILURE = "provider_failure"
VALIDATION_FAILURE = "validation_failure"
FRESHNESS_FAILURE = "freshness_failure"
CACHE_FAILURE = "cache_failure"
FALLBACK_FAILURE = "fallback_failure"
SNAPSHOT_FAILURE = "snapshot_failure"
REPORT_GENERATION_FAILURE = "report_generation_failure"
UNEXPECTED_EXCEPTION = "unexpected_exception"

REPLAY_STATUS_CATEGORIES = (
    SUCCESS,
    PROVIDER_FAILURE,
    VALIDATION_FAILURE,
    FRESHNESS_FAILURE,
    CACHE_FAILURE,
    FALLBACK_FAILURE,
    SNAPSHOT_FAILURE,
    REPORT_GENERATION_FAILURE,
    UNEXPECTED_EXCEPTION,
)

SUMMARY_FILENAME = "replay_summary.json"
FAILURES_FILENAME = "replay_failures.csv"
MANIFEST_FILENAME = "replay_manifest.json"


@dataclass(frozen=True)
class ReplayFailure:
    """One fail-closed replay failure row."""

    date: str
    failure_type: str
    provider: str
    error_message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "date": self.date,
            "failure_type": self.failure_type,
            "provider": self.provider,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class ReplayDayResult:
    """Status emitted for one replayed date."""

    as_of: date
    status: str
    provider_csv_paths: Mapping[str, str]
    fetch_manifest_path: str | None = None
    provider_health_path: str | None = None
    daily_artifact_paths: Mapping[str, str] | None = None
    failure: ReplayFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCESS and self.failure is None


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the TDT-RM daily production pipeline from historical/local inputs only.")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="First replay date, YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="Last replay date, YYYY-MM-DD.")
    parser.add_argument("--outputs-dir", required=True, help="Directory for replay artifacts.")
    parser.add_argument("--source-config", help="Provider source configuration. Defaults to config/public_data_sources.json.")
    parser.add_argument("--main7-config", help="Optional JSON file containing a Main-7 symbols list.")
    parser.add_argument("--cache-dir", help="Read-only historical provider cache directory.")
    parser.add_argument("--provider-inputs-dir", help="Directory containing per-day provider CSV fixtures under YYYY-MM-DD/.")
    parser.add_argument("--snapshots-dir", help="Directory containing existing snapshot fixtures named YYYY-MM-DD.json or assembled_daily_snapshot_YYYY-MM-DD.json.")
    args = parser.parse_args()

    try:
        results, summary, manifest_path = run_historical_replay(
            start_date=args.start_date,
            end_date=args.end_date,
            outputs_dir=args.outputs_dir,
            source_config=args.source_config,
            main7_config=args.main7_config,
            cache_dir=args.cache_dir,
            provider_inputs_dir=args.provider_inputs_dir,
            snapshots_dir=args.snapshots_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI presents concise operator error.
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    print(render_cli_summary(summary))
    return 0 if not summary["failed_runs"] else 1


def run_historical_replay(
    *,
    start_date: date,
    end_date: date,
    outputs_dir: str | Path,
    source_config: Mapping[str, Any] | str | Path | None = None,
    main7_config: str | Path | None = None,
    cache_dir: str | Path | None = None,
    provider_inputs_dir: str | Path | None = None,
    snapshots_dir: str | Path | None = None,
) -> tuple[list[ReplayDayResult], dict[str, Any], Path]:
    """Replay daily production runs over an inclusive date range.

    Live/network provider sources are disabled for every day by setting the
    public fetch context to ``offline=True``. Cache access is read-only when a
    cache directory is supplied.
    """

    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date")

    destination = Path(outputs_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source_config_payload = load_source_config(source_config)
    main7_symbols = load_main7_symbols(main7_config)
    registry = PublicDataFetcherRegistry.from_config(source_config_payload)

    results: list[ReplayDayResult] = []
    for as_of in _date_range(start_date, end_date):
        results.append(
            replay_one_day(
                as_of=as_of,
                outputs_dir=destination,
                registry=registry,
                source_config=source_config_payload,
                main7_symbols=main7_symbols,
                cache_dir=cache_dir,
                provider_inputs_dir=Path(provider_inputs_dir) if provider_inputs_dir else None,
                snapshots_dir=Path(snapshots_dir) if snapshots_dir else None,
            )
        )

    failures = [result.failure for result in results if result.failure is not None]
    summary_path = destination / SUMMARY_FILENAME
    failure_log_path = destination / FAILURES_FILENAME
    manifest_path = destination / MANIFEST_FILENAME
    summary = build_replay_summary(start_date, end_date, results)
    write_replay_summary(summary_path, summary)
    write_failure_log(failure_log_path, failures)
    write_replay_manifest(manifest_path, start_date, end_date, summary, summary_path, failure_log_path)
    return results, summary, manifest_path


def replay_one_day(
    *,
    as_of: date,
    outputs_dir: Path,
    registry: PublicDataFetcherRegistry,
    source_config: Mapping[str, Any],
    main7_symbols: Sequence[str],
    cache_dir: str | Path | None,
    provider_inputs_dir: Path | None,
    snapshots_dir: Path | None,
) -> ReplayDayResult:
    """Replay one day and classify fail-closed failures."""

    day_dir = outputs_dir / as_of.isoformat()
    provider_dir = day_dir / "providers"
    pipeline_dir = day_dir / "daily"
    try:
        snapshot_path = _snapshot_fixture_path(snapshots_dir, as_of)
        if snapshot_path is not None:
            pipeline = run_daily_pipeline(
                as_of=as_of,
                output_dir=pipeline_dir,
                snapshot_path=snapshot_path,
                command="scripts/replay_daily_pipeline.py",
            )
            return _pipeline_result(as_of, SUCCESS, {}, pipeline)

        provider_paths = _provider_fixture_paths(provider_inputs_dir, as_of)
        provider_field_map_path = provider_paths.pop("field_map", None)
        fetch_manifest_path: str | None = None
        provider_health_path: str | None = None

        if not provider_paths:
            context = PublicDataFetchContext(
                as_of=as_of,
                source_config=source_config,
                main7_symbols=tuple(main7_symbols),
                offline=True,
                cache_dir=cache_dir,
                cache_mode="read" if cache_dir else "off",
            )
            fetch_results = registry.fetch_all(context)
            written = write_provider_csvs(fetch_results, provider_dir, as_of)
            provider_paths = dict(written.provider_csv_paths)
            provider_field_map_path = written.provider_field_map_path
            fetch_manifest_path = written.fetch_manifest_path
            provider_health_path = written.provider_health_path
            blocking_failure = classify_fetch_failure(as_of, fetch_results, provider_paths)
            if blocking_failure is not None:
                return ReplayDayResult(
                    as_of=as_of,
                    status=blocking_failure.failure_type,
                    provider_csv_paths=provider_paths,
                    fetch_manifest_path=fetch_manifest_path,
                    provider_health_path=provider_health_path,
                    failure=blocking_failure,
                )

        if "price" not in provider_paths:
            failure = ReplayFailure(as_of.isoformat(), PROVIDER_FAILURE, "price_provider", "missing required provider input")
            return ReplayDayResult(as_of, PROVIDER_FAILURE, provider_paths, fetch_manifest_path, provider_health_path, failure=failure)

        pipeline = run_daily_pipeline(
            as_of=as_of,
            output_dir=pipeline_dir,
            price_csv=provider_paths.get("price"),
            foreign_csv=provider_paths.get("foreign_flow"),
            fx_csv=provider_paths.get("fx"),
            breadth_csv=provider_paths.get("breadth"),
            leadership_csv=provider_paths.get("leadership"),
            margin_csv=provider_paths.get("margin"),
            scores_csv=provider_paths.get("scores"),
            field_map=provider_field_map_path,
            command="scripts/replay_daily_pipeline.py",
        )
        validation = pipeline.get("validation") if isinstance(pipeline, Mapping) else {}
        if isinstance(validation, Mapping) and (validation.get("has_errors") or validation.get("error_count")):
            failure_type = _validation_failure_type(validation)
            failure = ReplayFailure(as_of.isoformat(), failure_type, "validation_gate", _validation_error_message(validation))
            return ReplayDayResult(as_of, failure_type, provider_paths, fetch_manifest_path, provider_health_path, pipeline.get("artifact_paths", {}) if isinstance(pipeline, Mapping) else {}, failure)
        return _pipeline_result(as_of, SUCCESS, provider_paths, pipeline, fetch_manifest_path, provider_health_path)
    except Exception as exc:  # noqa: BLE001 - replay records failures per day.
        failure_type = classify_pipeline_exception(exc)
        provider = _failure_provider(failure_type)
        failure = ReplayFailure(as_of.isoformat(), failure_type, provider, str(exc))
        return ReplayDayResult(as_of, failure_type, {}, failure=failure)


def classify_fetch_failure(as_of: date, fetch_results: Sequence[PublicDataFetchResult], provider_paths: Mapping[str, str]) -> ReplayFailure | None:
    """Classify required-provider replay failures before pipeline execution."""

    if "price" in provider_paths:
        return None
    price_results = [result for result in fetch_results if result.provider_category == "price"]
    if not price_results:
        return ReplayFailure(as_of.isoformat(), PROVIDER_FAILURE, "price_provider", "missing required provider input")
    final = price_results[-1]
    provider = final.source_id or "price_provider"
    message = _fetch_error_message(final) or "missing required provider input"
    if final.status == "stale" or any(issue.code == "stale_data" for result in price_results for issue in result.issues):
        return ReplayFailure(as_of.isoformat(), FRESHNESS_FAILURE, provider, message)
    if any(_cache_miss(result) for result in price_results) and all(not result.success for result in price_results):
        return ReplayFailure(as_of.isoformat(), CACHE_FAILURE, provider, message)
    if any(result.raw_metadata.get("local_fallback") for result in price_results) and all(not result.success for result in price_results):
        return ReplayFailure(as_of.isoformat(), FALLBACK_FAILURE, provider, message)
    return ReplayFailure(as_of.isoformat(), PROVIDER_FAILURE, provider, message)


def classify_pipeline_exception(exc: Exception) -> str:
    message = str(exc).lower()
    if "freshness" in message or "stale" in message:
        return FRESHNESS_FAILURE
    if "provider assembly failed" in message or "provider" in message or "required provider input" in message:
        return PROVIDER_FAILURE
    if "snapshot" in message:
        return SNAPSHOT_FAILURE
    if "validation" in message:
        return VALIDATION_FAILURE
    if "daily_report" in message or "report" in message or "markdown" in message or "artifact" in message:
        return REPORT_GENERATION_FAILURE
    return UNEXPECTED_EXCEPTION


def build_replay_summary(start_date: date, end_date: date, results: Sequence[ReplayDayResult]) -> dict[str, Any]:
    failures = [result for result in results if not result.succeeded]
    counts = {status: sum(1 for result in failures if result.status == status) for status in REPLAY_STATUS_CATEGORIES if status != SUCCESS}
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_days": len(results),
        "successful_runs": sum(1 for result in results if result.succeeded),
        "failed_runs": len(failures),
        "provider_failures": counts[PROVIDER_FAILURE],
        "validation_failures": counts[VALIDATION_FAILURE],
        "stale_data_failures": counts[FRESHNESS_FAILURE],
        "freshness_failures": counts[FRESHNESS_FAILURE],
        "cache_failures": counts[CACHE_FAILURE],
        "fallback_failures": counts[FALLBACK_FAILURE],
        "snapshot_failures": counts[SNAPSHOT_FAILURE],
        "report_generation_failures": counts[REPORT_GENERATION_FAILURE],
        "unexpected_exceptions": counts[UNEXPECTED_EXCEPTION],
        "status_counts": {status: sum(1 for result in results if result.status == status) for status in REPLAY_STATUS_CATEGORIES},
        "replay_status": "PASSED" if not failures else "FAILED",
    }


def write_replay_summary(path: Path, summary: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_failure_log(path: Path, failures: Iterable[ReplayFailure | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "failure_type", "provider", "error_message"])
        writer.writeheader()
        for failure in failures:
            if failure is not None:
                writer.writerow(failure.as_dict())


def write_replay_manifest(
    path: Path,
    start_date: date,
    end_date: date,
    summary: Mapping[str, Any],
    summary_path: Path,
    failure_log_path: Path,
) -> None:
    manifest = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "total_days": summary["total_days"],
        "successful_runs": summary["successful_runs"],
        "failed_runs": summary["failed_runs"],
        "summary_path": str(summary_path),
        "failure_log_path": str(failure_log_path),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_cli_summary(summary: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "Historical Production Replay Summary",
            f"Start Date: {summary['start_date']}",
            f"End Date: {summary['end_date']}",
            f"Total Days: {summary['total_days']}",
            f"Successful Runs: {summary['successful_runs']}",
            f"Failed Runs: {summary['failed_runs']}",
            f"Provider Failures: {summary['provider_failures']}",
            f"Validation Failures: {summary['validation_failures']}",
            f"Freshness Failures: {summary['freshness_failures']}",
            f"Report Failures: {summary['report_generation_failures']}",
            f"Replay Status: {summary['replay_status']}",
        ]
    )


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _pipeline_result(
    as_of: date,
    status: str,
    provider_paths: Mapping[str, str],
    pipeline: Mapping[str, Any],
    fetch_manifest_path: str | None = None,
    provider_health_path: str | None = None,
) -> ReplayDayResult:
    artifact_paths = pipeline.get("artifact_paths", {}) if isinstance(pipeline, Mapping) else {}
    return ReplayDayResult(as_of, status, provider_paths, fetch_manifest_path, provider_health_path, artifact_paths if isinstance(artifact_paths, Mapping) else {})


def _snapshot_fixture_path(snapshots_dir: Path | None, as_of: date) -> str | None:
    if snapshots_dir is None:
        return None
    candidates = [
        snapshots_dir / f"{as_of.isoformat()}.json",
        snapshots_dir / f"assembled_daily_snapshot_{as_of.isoformat()}.json",
        snapshots_dir / as_of.isoformat() / "snapshot.json",
        snapshots_dir / as_of.isoformat() / f"assembled_daily_snapshot_{as_of.isoformat()}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _provider_fixture_paths(provider_inputs_dir: Path | None, as_of: date) -> dict[str, str]:
    if provider_inputs_dir is None:
        return {}
    day_dir = provider_inputs_dir / as_of.isoformat()
    if not day_dir.exists():
        return {}
    names = {
        "price": "price.csv",
        "foreign_flow": "foreign_flow.csv",
        "fx": "fx.csv",
        "breadth": "breadth.csv",
        "leadership": "leadership.csv",
        "margin": "margin.csv",
        "scores": "scores.csv",
        "field_map": "provider_field_map.json",
    }
    return {category: str(day_dir / filename) for category, filename in names.items() if (day_dir / filename).exists()}


def _fetch_error_message(result: PublicDataFetchResult) -> str:
    messages = [issue.message for issue in result.issues if issue.message]
    if messages:
        return "; ".join(messages)
    if result.raw_metadata.get("exception_message"):
        return str(result.raw_metadata["exception_message"])
    return str(result.status)


def _cache_miss(result: PublicDataFetchResult) -> bool:
    cache = result.raw_metadata.get("cache") if isinstance(result.raw_metadata, Mapping) else None
    return isinstance(cache, Mapping) and cache.get("hit") is False


def _validation_failure_type(validation: Mapping[str, Any]) -> str:
    issues = validation.get("issues", [])
    if isinstance(issues, list):
        codes = {str(issue.get("code")) for issue in issues if isinstance(issue, Mapping)}
        if "stale_trade_date" in codes or "future_trade_date" in codes:
            return FRESHNESS_FAILURE
        if "missing_markdown_artifact" in codes or "markdown_signal_mismatch" in codes or "markdown_trade_date_mismatch" in codes:
            return REPORT_GENERATION_FAILURE
    return VALIDATION_FAILURE


def _validation_error_message(validation: Mapping[str, Any]) -> str:
    issues = validation.get("issues", [])
    if isinstance(issues, list):
        messages = [str(issue.get("message")) for issue in issues if isinstance(issue, Mapping) and issue.get("severity") == "error"]
        if messages:
            return "; ".join(messages)
    return "validation gate failed"


def _failure_provider(failure_type: str) -> str:
    return {
        PROVIDER_FAILURE: "provider",
        FRESHNESS_FAILURE: "freshness_gate",
        VALIDATION_FAILURE: "validation_gate",
        SNAPSHOT_FAILURE: "snapshot_assembler",
        REPORT_GENERATION_FAILURE: "daily_report",
        CACHE_FAILURE: "provider_cache",
        FALLBACK_FAILURE: "provider_fallback",
    }.get(failure_type, "replay")


if __name__ == "__main__":
    raise SystemExit(main())
