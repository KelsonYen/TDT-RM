#!/usr/bin/env python
"""Generate a fail-closed daily production report from existing artifacts only."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_runner import render_user_daily_report

REQUIRED_CORE_OUTPUTS: Mapping[str, tuple[str, ...]] = {
    "TCWRS": ("scores.TCWRS", "tcwrs", "TCWRS"),
    "MHS": ("scores.MHS", "mhs", "MHS"),
    "ETI-5": ("scores.ETI-5", "eti_5", "ETI-5"),
    "Tail Risk": ("scores.Tail Risk", "tail_risk", "Tail Risk"),
    "BCD": ("scores.BCD", "bcd", "BCD"),
    "Crash Probability": ("scores.CP", "cp", "CP"),
    "Regime State": ("regime_state", "market_regime"),
    "Signal": ("signal",),
    "Exposure Limit": ("equity_exposure_limit", "exposure_limit"),
}
DEFAULT_REQUIRED_PROVIDERS = ("price_provider",)
PASSING_VALIDATION_STATUSES = {"passed", "warning"}
PASSING_FRESHNESS_STATUSES = {"passed", "fresh", "fresh_or_not_applicable", "not_applicable", "ok"}
PASSING_PROVIDER_STATUSES = {"healthy", "warning", "passed"}
FAILING_PIPELINE_STATUSES = {"failed", "error", "blocked", "fail", "price_unavailable"}


class ReportGenerationError(RuntimeError):
    """Raised when report generation must fail closed."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate outputs/daily_report.md from existing TDT-RM daily production artifacts."
    )
    parser.add_argument("--trade-date", help="Daily production trade date, YYYY-MM-DD.")
    parser.add_argument("--outputs-dir", default="outputs", help="Directory containing existing output artifacts.")
    parser.add_argument("--report-path", help="Markdown report path (default: <outputs-dir>/daily_report.md).")
    parser.add_argument("--failed-report-path", help="Optional failed report path (default: sibling daily_report_failed.md).")

    # Backward-compatible aliases for the existing audit-report CLI.
    parser.add_argument("--fetch-manifest", help="Explicit fetch_manifest.json path.")
    parser.add_argument("--provider-health", help="Explicit provider_health.json path.")
    parser.add_argument("--model-output", help="Explicit model output JSON path.")
    parser.add_argument("--daily-validation", help="Explicit daily_validation/production manifest JSON path.")
    parser.add_argument("--pipeline-summary", help="Optional pipeline summary JSON path.")
    parser.add_argument("--output", help="Alias for --report-path.")
    args = parser.parse_args(argv)

    outputs_dir = Path(args.outputs_dir)
    report_path = Path(args.report_path or args.output or outputs_dir / "daily_report.md")
    failed_report_path = Path(args.failed_report_path or report_path.with_name("daily_report_failed.md"))

    try:
        bundle = load_report_bundle(
            trade_date=args.trade_date,
            outputs_dir=outputs_dir,
            fetch_manifest_path=Path(args.fetch_manifest) if args.fetch_manifest else None,
            provider_health_path=Path(args.provider_health) if args.provider_health else None,
            model_output_path=Path(args.model_output) if args.model_output else None,
            daily_validation_path=Path(args.daily_validation) if args.daily_validation else None,
            pipeline_summary_path=Path(args.pipeline_summary) if args.pipeline_summary else None,
        )
        report = render_daily_report(bundle)
        _write_report(report_path, report)
        _record_report_status(bundle, status="passed", report_path=report_path, generated_at=bundle["generated_at"], error_message="")
    except Exception as exc:  # noqa: BLE001 - fail-closed CLI should be concise.
        try:
            if report_path.exists():
                report_path.unlink()
            _write_report(failed_report_path, render_failed_report(str(exc)))
            _record_failure_status_from_args(args, outputs_dir, report_path, str(exc))
        except Exception as secondary_exc:  # noqa: BLE001 - preserve primary error.
            print(f"ERROR {exc}; additionally failed to write failure status: {secondary_exc}", file=sys.stderr)
            return 1
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    print(str(report_path))
    return 0


def load_report_bundle(
    *,
    trade_date: str | None,
    outputs_dir: Path,
    fetch_manifest_path: Path | None = None,
    provider_health_path: Path | None = None,
    model_output_path: Path | None = None,
    daily_validation_path: Path | None = None,
    pipeline_summary_path: Path | None = None,
) -> dict[str, Any]:
    """Load and validate existing artifacts without fetching, assembly, or model recomputation."""

    fetch_manifest_path = fetch_manifest_path or _find_existing(outputs_dir, ("fetch_manifest.json", "*_fetch_manifest.json"), required=False)
    pipeline_summary_path = pipeline_summary_path or _find_existing(outputs_dir, ("*_summary.json", "pipeline_summary.json"), required=False)
    pipeline_summary = _load_json(pipeline_summary_path) if pipeline_summary_path else {}
    pipeline_payload = _pipeline_payload(pipeline_summary)

    if not trade_date:
        trade_date = _infer_trade_date(fetch_manifest_path=fetch_manifest_path, pipeline_payload=pipeline_payload, outputs_dir=outputs_dir)
    if not trade_date:
        raise ReportGenerationError("trade_date is required and could not be inferred from output artifacts")

    model_output_path = model_output_path or _find_model_output(outputs_dir, trade_date, pipeline_payload)
    daily_validation_path = daily_validation_path or _find_validation_artifact(outputs_dir, trade_date, pipeline_payload)
    provider_health_path = provider_health_path or _find_existing(outputs_dir, ("provider_health.json", "*_provider_health.json"), required=False)

    model_output = _load_required_json(model_output_path, "model output")
    validation_artifact = _load_required_json(daily_validation_path, "daily validation")
    fetch_manifest = _load_json(fetch_manifest_path) if fetch_manifest_path else {}
    provider_health = _load_provider_health(provider_health_path, fetch_manifest, model_output)

    generated_at = datetime.now(UTC).isoformat()
    bundle = {
        "trade_date": trade_date,
        "generated_at": generated_at,
        "outputs_dir": outputs_dir,
        "fetch_manifest_path": fetch_manifest_path,
        "provider_health_path": provider_health_path,
        "model_output_path": model_output_path,
        "daily_validation_path": daily_validation_path,
        "pipeline_summary_path": pipeline_summary_path,
        "fetch_manifest": fetch_manifest,
        "provider_health": provider_health,
        "model_output": model_output,
        "validation_artifact": validation_artifact,
        "pipeline_payload": pipeline_payload,
    }
    _validate_bundle(bundle)
    return bundle


def render_daily_report(bundle: Mapping[str, Any], pipeline_summary: Mapping[str, Any] | None = None) -> str:
    """Render Dr. Yen's final user-facing daily investment risk report."""

    if "model_output" not in bundle:
        legacy_bundle = _legacy_bundle(bundle, pipeline_summary)
        _validate_bundle(legacy_bundle)
        bundle = legacy_bundle

    model_output = dict(_mapping(bundle.get("model_output")))
    data = dict(_mapping(model_output.get("data")))
    data.setdefault("data_status", _data_status(_mapping(bundle.get("fetch_manifest")), model_output, _mapping(bundle.get("pipeline_payload"))))
    data.setdefault("latest_bar_date", bundle.get("trade_date"))
    model_output["data"] = data
    model_output.setdefault("trade_date", bundle.get("trade_date"))
    return render_user_daily_report(model_output, generated_at=bundle.get("generated_at"))


def render_failed_report(error_message: str) -> str:
    return "\n".join(
        [
            "# PRODUCTION REPORT FAILED",
            "",
            "**NOT FOR TRADING USE**",
            "",
            f"* Generated At: {datetime.now(UTC).isoformat()}",
            f"* Error: {error_message}",
            "",
        ]
    )


def _validate_bundle(bundle: Mapping[str, Any]) -> None:
    trade_date = str(bundle.get("trade_date") or "")
    fetch_manifest = _mapping(bundle.get("fetch_manifest"))
    model_output = _mapping(bundle.get("model_output"))
    provider_health = _provider_entries(_mapping(bundle.get("provider_health")))
    validation_artifact = _mapping(bundle.get("validation_artifact"))
    pipeline_payload = _mapping(bundle.get("pipeline_payload"))

    if not trade_date:
        raise ReportGenerationError("trade_date is required")
    if not model_output:
        raise ReportGenerationError("missing required model output artifact")
    if not validation_artifact:
        raise ReportGenerationError("missing required daily validation artifact")
    if not provider_health:
        raise ReportGenerationError("provider_health.json is missing provider entries")

    _assert_artifact_trade_date("model output", model_output.get("trade_date"), trade_date)
    latest_bar_date = _path_get(model_output, "data.latest_bar_date")
    if latest_bar_date is not None:
        _assert_artifact_trade_date("model output data.latest_bar_date", latest_bar_date, trade_date)

    manifest_as_of = fetch_manifest.get("as_of") or fetch_manifest.get("trade_date")
    if manifest_as_of is not None:
        _assert_artifact_trade_date("fetch manifest", manifest_as_of, trade_date)
    if str(fetch_manifest.get("data_status") or "").lower() in FAILING_PIPELINE_STATUSES:
        raise ReportGenerationError(f"manifest data_status is blocking: {fetch_manifest.get('data_status')}")
    if fetch_manifest.get("pipeline_status") and str(fetch_manifest.get("pipeline_status")).lower() not in {"passed", "warning", "success"}:
        raise ReportGenerationError(f"manifest pipeline_status is blocking: {fetch_manifest.get('pipeline_status')}")
    if fetch_manifest.get("failed_sources"):
        raise ReportGenerationError("manifest records failed source attempts")
    if fetch_manifest.get("stale_sources"):
        raise ReportGenerationError("manifest records stale source attempts")

    validation = _validation_payload(validation_artifact)
    status = _validation_status(validation)
    if status.lower() not in PASSING_VALIDATION_STATUSES:
        raise ReportGenerationError(f"validation_status failed: {status}")
    if not _validation_passed(validation):
        raise ReportGenerationError("validation_passed is false")

    for label, paths in REQUIRED_CORE_OUTPUTS.items():
        if _first_present(model_output, paths) is None:
            raise ReportGenerationError(f"model output missing required field: {label}")

    required_providers = _required_provider_names(fetch_manifest, provider_health)
    missing_providers = sorted(provider for provider in required_providers if provider not in provider_health)
    if missing_providers:
        raise ReportGenerationError("provider_health.json missing required provider(s): " + ", ".join(missing_providers))

    for provider_name, provider in provider_health.items():
        item = _mapping(provider)
        status = str(item.get("status") or "").lower()
        freshness_status = _effective_provider_freshness_status(item)
        as_of = item.get("as_of")
        if provider_name in required_providers and status not in PASSING_PROVIDER_STATUSES:
            raise ReportGenerationError(f"required provider failed: {provider_name} status={item.get('status')}")
        if provider_name in required_providers and freshness_status not in PASSING_FRESHNESS_STATUSES:
            raise ReportGenerationError(f"required provider stale or freshness failed: {provider_name}")
        if as_of is not None:
            _assert_artifact_trade_date(f"provider {provider_name} as_of", as_of, trade_date)
        if provider_name in required_providers and _provider_records_loaded(item) <= 0:
            raise ReportGenerationError(f"required provider has no loaded records: {provider_name}")

    pipeline_status = str(pipeline_payload.get("pipeline_status") or pipeline_payload.get("status") or "").lower()
    if pipeline_status and pipeline_status not in {"passed", "warning", "success"}:
        raise ReportGenerationError(f"pipeline summary status is blocking: {pipeline_status}")


def _legacy_bundle(fetch_manifest: Mapping[str, Any], pipeline_summary: Mapping[str, Any] | None = None) -> dict[str, Any]:
    pipeline = _pipeline_payload(pipeline_summary or {})
    trade_date = str(pipeline.get("trade_date") or fetch_manifest.get("as_of") or "")
    scores = _mapping(pipeline.get("scores"))
    model_output = {
        "trade_date": trade_date,
        "model_version": pipeline.get("model_version") or "unknown",
        "scores": scores,
        "signal": pipeline.get("signal") or "unknown",
        "equity_exposure_limit": pipeline.get("exposure_limit") or "unknown",
        "market_regime": pipeline.get("regime_state") or pipeline.get("market_regime") or "unknown",
        "data": {"latest_bar_date": trade_date, "data_status": fetch_manifest.get("data_status")},
    }
    for key in ("TCWRS", "MHS", "ETI-5", "Tail Risk", "BCD", "CP"):
        scores.setdefault(key, 0 if key in {"TCWRS", "ETI-5"} else 0.0)
    validation = pipeline.get("validation") if isinstance(pipeline.get("validation"), Mapping) else {"status": "passed", "passed": True}
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "fetch_manifest": dict(fetch_manifest),
        "provider_health": {"providers": _provider_entries(fetch_manifest)},
        "model_output": model_output,
        "validation_artifact": validation,
        "pipeline_payload": pipeline,
    }


def _load_provider_health(path: Path | None, fetch_manifest: Mapping[str, Any], model_output: Mapping[str, Any]) -> Mapping[str, Any]:
    del model_output  # Provider health must come from provider health artifacts, not recomputation.
    if path is not None and path.exists():
        return _load_json(path)
    if isinstance(fetch_manifest.get("provider_health"), Mapping):
        return {"providers": fetch_manifest.get("provider_health", {})}
    return {}

def _core_outputs(model_output: Mapping[str, Any]) -> dict[str, Any]:
    return {label: _first_present(model_output, paths) for label, paths in REQUIRED_CORE_OUTPUTS.items()}


def _required_provider_names(fetch_manifest: Mapping[str, Any], provider_health: Mapping[str, Any]) -> tuple[str, ...]:
    raw = fetch_manifest.get("required_providers") or fetch_manifest.get("required_provider_names")
    if isinstance(raw, list) and raw:
        return tuple(str(provider) for provider in raw)
    health_summary = fetch_manifest.get("provider_health_summary")
    if isinstance(health_summary, Mapping):
        raw = health_summary.get("required_providers")
        if isinstance(raw, list) and raw:
            return tuple(str(provider) for provider in raw)
    if "price_provider" in provider_health:
        return DEFAULT_REQUIRED_PROVIDERS
    return tuple(provider_health)


def _effective_provider_freshness_status(provider: Mapping[str, Any]) -> str:
    raw_freshness_status = provider.get("freshness_status")
    if raw_freshness_status is not None and str(raw_freshness_status).strip():
        return str(raw_freshness_status).lower()

    if str(provider.get("status") or "").lower() != "healthy":
        return ""
    if not _provider_has_usable_selected_attempt(provider):
        return ""
    if not (provider.get("source_selected") or provider.get("provider_used")):
        return ""
    if not _provider_checks_passed(provider.get("reconciliation_checks")):
        return ""
    return "fresh_or_not_applicable"


def _provider_has_usable_selected_attempt(provider: Mapping[str, Any]) -> bool:
    attempts = provider.get("attempts")
    if not isinstance(attempts, list):
        return False
    for attempt in attempts:
        item = _mapping(attempt)
        if item.get("attempted") is False or item.get("selected") is not True:
            continue
        if str(item.get("status") or "").lower() not in PASSING_PROVIDER_STATUSES:
            continue
        if not (item.get("output_path") or item.get("provider") or item.get("source")):
            continue
        if not _provider_checks_passed(item.get("checks")):
            continue
        return True
    return False


def _provider_checks_passed(raw_checks: Any) -> bool:
    if not isinstance(raw_checks, list) or not raw_checks:
        return False
    passing_check_statuses = PASSING_VALIDATION_STATUSES | PASSING_FRESHNESS_STATUSES | {"success"}
    for check in raw_checks:
        status = str(_mapping(check).get("status") or "").lower()
        if status not in passing_check_statuses:
            return False
    return True


def _provider_records_loaded(provider: Mapping[str, Any]) -> int:
    raw_records_loaded = provider.get("records_loaded")
    if raw_records_loaded is not None:
        return int(raw_records_loaded or 0)

    attempts = provider.get("attempts")
    if not isinstance(attempts, list):
        return 0
    for attempt in attempts:
        item = _mapping(attempt)
        if item.get("selected") is not True:
            continue
        attempt_records = item.get("records_loaded")
        if attempt_records is not None:
            return int(attempt_records or 0)
        metadata = _mapping(item.get("metadata"))
        bar_count = metadata.get("bar_count")
        if bar_count is not None:
            return int(bar_count or 0)
    return 0


def _validation_payload(validation_artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    value = validation_artifact.get("validation")
    return value if isinstance(value, Mapping) else validation_artifact


def _validation_status(validation: Mapping[str, Any]) -> str:
    status = validation.get("status") or validation.get("validation_status")
    if status is not None:
        return str(status)
    return "passed" if _validation_passed(validation) else "failed"


def _validation_passed(validation: Mapping[str, Any]) -> bool:
    if "passed" in validation:
        return bool(validation.get("passed"))
    if "validation_passed" in validation:
        return bool(validation.get("validation_passed"))
    if validation.get("has_errors") or validation.get("error_count"):
        return False
    return _validation_status(validation).lower() in PASSING_VALIDATION_STATUSES


def _validation_messages(validation: Mapping[str, Any], key: str) -> list[str]:
    raw = validation.get(key) or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        return []
    messages: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            messages.append(str(item.get("message") or item.get("code") or item))
        else:
            messages.append(str(item))
    return messages


def _provider_warning_messages(provider_health: Mapping[str, Any]) -> list[str]:
    messages: list[str] = []
    for provider_name, provider in provider_health.items():
        item = _mapping(provider)
        if str(item.get("status") or "").lower() == "warning" or str(item.get("source_type") or "").lower() == "local_fallback":
            diagnostics = _mapping(item.get("diagnostics"))
            diagnostics_messages = diagnostics.get("messages") if isinstance(diagnostics.get("messages"), list) else []
            if diagnostics_messages:
                messages.extend(str(message) for message in diagnostics_messages)
            else:
                messages.append(f"{provider_name} status={item.get('status')} source_type={item.get('source_type')}")
    return messages


def _operator_action(signal: str, exposure_limit: str) -> str:
    normalized = signal.lower()
    if normalized == "yellow":
        return "Hold. Do not chase. Do not use leverage."
    if normalized in {"red", "deep red"}:
        return "De-risk according to the approved exposure limit; do not add leverage."
    if normalized == "green":
        return f"Operate within the approved exposure limit ({exposure_limit}); no leverage beyond policy."
    return "Follow the approved decision matrix and do not override validation gate results."


def _pipeline_status(fetch_manifest: Mapping[str, Any], pipeline_payload: Mapping[str, Any], validation: Mapping[str, Any]) -> str:
    for value in (fetch_manifest.get("pipeline_status"), pipeline_payload.get("pipeline_status"), pipeline_payload.get("status")):
        if value:
            return str(value)
    return "passed" if _validation_passed(validation) else "failed"


def _data_status(fetch_manifest: Mapping[str, Any], model_output: Mapping[str, Any], pipeline_payload: Mapping[str, Any]) -> str:
    data = _mapping(model_output.get("data"))
    value = fetch_manifest.get("data_status") or pipeline_payload.get("data_status") or data.get("data_status") or data.get("status")
    return str(value) if value is not None else "unknown"


def _record_report_status(bundle: Mapping[str, Any], *, status: str, report_path: Path, generated_at: str, error_message: str) -> None:
    payload = {
        "status": status,
        "report_path": str(report_path),
        "generated_at": generated_at,
        "error_message": error_message,
    }
    for key in ("fetch_manifest_path", "daily_validation_path"):
        path = bundle.get(key)
        if isinstance(path, Path) and path.exists():
            _update_json_file(path, payload)


def _record_failure_status_from_args(args: argparse.Namespace, outputs_dir: Path, report_path: Path, error_message: str) -> None:
    paths = []
    if args.fetch_manifest:
        paths.append(Path(args.fetch_manifest))
    else:
        found = _find_existing(outputs_dir, ("fetch_manifest.json", "*_fetch_manifest.json"), required=False)
        if found:
            paths.append(found)
    if args.daily_validation:
        paths.append(Path(args.daily_validation))
    for path in dict.fromkeys(paths):
        if path.exists():
            _update_json_file(
                path,
                {
                    "status": "failed",
                    "report_path": str(report_path),
                    "generated_at": datetime.now(UTC).isoformat(),
                    "error_message": error_message,
                },
            )


def _update_json_file(path: Path, daily_report_payload: Mapping[str, Any]) -> None:
    payload = _load_json(path)
    payload = dict(payload)
    payload["daily_report"] = dict(daily_report_payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _find_model_output(outputs_dir: Path, trade_date: str, pipeline_payload: Mapping[str, Any]) -> Path | None:
    artifacts = _mapping(pipeline_payload.get("artifact_paths"))
    if artifacts.get("json"):
        return Path(str(artifacts["json"]))
    return _find_existing(
        outputs_dir,
        (f"tdt_rm_daily_{trade_date}.json", f"model_output_{trade_date}.json", "model_output.json", "daily_snapshot.json"),
        required=False,
    )


def _find_validation_artifact(outputs_dir: Path, trade_date: str, pipeline_payload: Mapping[str, Any]) -> Path | None:
    artifacts = _mapping(pipeline_payload.get("artifact_paths"))
    if artifacts.get("manifest"):
        return Path(str(artifacts["manifest"]))
    return _find_existing(
        outputs_dir,
        (f"tdt_rm_daily_{trade_date}_manifest.json", "daily_validation.json", f"daily_validation_{trade_date}.json"),
        required=False,
    )


def _find_existing(outputs_dir: Path, patterns: Sequence[str], *, required: bool) -> Path | None:
    for pattern in patterns:
        matches = sorted(outputs_dir.glob(pattern))
        for match in matches:
            if match.exists() and match.is_file():
                return match
    if required:
        raise ReportGenerationError(f"missing required output file matching: {', '.join(patterns)}")
    return None


def _infer_trade_date(*, fetch_manifest_path: Path | None, pipeline_payload: Mapping[str, Any], outputs_dir: Path) -> str | None:
    if pipeline_payload.get("trade_date"):
        return str(pipeline_payload["trade_date"])
    if fetch_manifest_path and fetch_manifest_path.exists():
        manifest = _load_json(fetch_manifest_path)
        if manifest.get("as_of") or manifest.get("trade_date"):
            return str(manifest.get("as_of") or manifest.get("trade_date"))
    for pattern in ("tdt_rm_daily_*.json", "model_output_*.json"):
        for path in sorted(outputs_dir.glob(pattern)):
            stem = path.stem
            if stem.endswith("_manifest") or stem.endswith("_summary"):
                continue
            candidate = stem.rsplit("_", 1)[-1]
            if len(candidate) == 10:
                return candidate
    return None


def _pipeline_payload(summary: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(summary, Mapping):
        return {}
    value = summary.get("pipeline")
    return value if isinstance(value, Mapping) else summary


def _load_required_json(path: Path | None, label: str) -> Mapping[str, Any]:
    if path is None:
        raise ReportGenerationError(f"missing required output file: {label}")
    return _load_json(path)


def _load_json(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise ReportGenerationError(f"missing required output file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ReportGenerationError(f"JSON root must be an object: {path}")
    return payload


def _provider_entries(health: Mapping[str, Any]) -> Mapping[str, Any]:
    providers = health.get("providers") if isinstance(health.get("providers"), Mapping) else health.get("provider_health")
    if isinstance(providers, Mapping):
        return providers
    if all(isinstance(value, Mapping) and "status" in value for value in health.values()):
        return health
    return {}


def _first_present(payload: Mapping[str, Any], paths: Sequence[str], *, default: Any = None) -> Any:
    for path in paths:
        value = _path_get(payload, path)
        if value is not None:
            return value
    return default


def _path_get(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _assert_artifact_trade_date(label: str, raw_value: Any, trade_date: str) -> None:
    if raw_value is None:
        return
    value = str(raw_value)[:10]
    if value != trade_date:
        raise ReportGenerationError(f"{label} date {value} does not match trade_date {trade_date}")


def _format_messages(messages: Sequence[str]) -> str:
    return "; ".join(message for message in messages if message) if messages else "none"


if __name__ == "__main__":
    raise SystemExit(main())
