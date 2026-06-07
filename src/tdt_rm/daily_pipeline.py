"""One-command daily production pipeline for assembled provider snapshots.

This module only orchestrates existing provider assembly, daily production, and
artifact validation helpers.  It deliberately does not change TDT-RM scoring
logic, TCWRS weights, ETI-5 rules, Crash Probability, Bear Trend Filter, CAL,
or the five-light decision matrix.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bcd_feature_builder import (
    BCDFeatureBuilderContext,
    enrich_bcd_features,
    write_bcd_feature_enrichment_trace,
)
from .daily_providers import (
    FORBIDDEN_PROVIDER_BCD_FIELDS,
    PROVIDER_BCD_FORBIDDEN_MESSAGE,
    DailyProviderContext,
    DailySnapshotAssembler,
    LocalCsvProvider,
    ManualScoreProvider,
    TAIEXPriceProvider,
)
from .daily_runner import DailyRunResult, _bcd_result_from_snapshot, render_user_daily_report, run_daily_production, write_bcd_audit_artifacts
from .daily_snapshot import DailyMarketSnapshot, load_daily_snapshot_json
from .daily_validation import validate_daily_artifacts
from .report_quality import assess_production_report_quality, render_operator_disclosure


@dataclass(frozen=True)
class DailyPipelineInputs:
    """Serializable path inputs accepted by the daily pipeline."""

    as_of: date
    output_dir: str | Path
    snapshot_out: str | Path | None = None
    price_csv: str | Path | None = None
    foreign_csv: str | Path | None = None
    fx_csv: str | Path | None = None
    breadth_csv: str | Path | None = None
    leadership_csv: str | Path | None = None
    margin_csv: str | Path | None = None
    scores_csv: str | Path | None = None
    futures_csv: str | Path | None = None
    options_csv: str | Path | None = None
    field_map: str | Path | None = None
    snapshot_path: str | Path | None = None
    write_manifest: bool = True
    command: str | None = None


@dataclass(frozen=True)
class DailyPipelineResult:
    """Serializable result emitted by a complete daily pipeline run."""

    trade_date: str
    data_status: str | None
    signal: str | None
    exposure_limit: str | None
    regime_state: str | None
    latest_bar_date: str | None
    scores: Mapping[str, Any]
    available_eti_components: tuple[str, ...]
    fallback_proxies: Mapping[str, Any]
    provider_warnings: tuple[str, ...]
    validation: Mapping[str, Any]
    artifact_paths: Mapping[str, str]
    production_report_quality: str | None = None
    operator_disclosure: Mapping[str, Any] | None = None
    assembled_snapshot_path: str | None = None

    @property
    def validation_status(self) -> str | None:
        return str(self.validation.get("status")) if self.validation.get("status") is not None else None

    @property
    def has_blocking_validation_errors(self) -> bool:
        return bool(self.validation.get("has_errors") or self.validation.get("error_count"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "data_status": self.data_status,
            "signal": self.signal,
            "exposure_limit": self.exposure_limit,
            "regime_state": self.regime_state,
            "latest_bar_date": self.latest_bar_date,
            "scores": dict(self.scores),
            "TCWRS": self.scores.get("TCWRS"),
            "MHS": self.scores.get("MHS"),
            "ETI-5": self.scores.get("ETI-5"),
            "Tail Risk": self.scores.get("Tail Risk"),
            "BCD": self.scores.get("BCD"),
            "CP": self.scores.get("CP"),
            "available_eti_components": list(self.available_eti_components),
            "fallback_proxies": dict(self.fallback_proxies),
            "provider_warnings": list(self.provider_warnings),
            "validation_status": self.validation_status,
            "validation": dict(self.validation),
            "artifact_paths": dict(self.artifact_paths),
            "production_report_quality": self.production_report_quality,
            "operator_disclosure": dict(self.operator_disclosure or {}),
            "assembled_snapshot_path": self.assembled_snapshot_path,
        }


def run_daily_pipeline(
    *,
    as_of: date,
    output_dir: str | Path,
    snapshot_out: str | Path | None = None,
    price_csv: str | Path | None = None,
    foreign_csv: str | Path | None = None,
    fx_csv: str | Path | None = None,
    breadth_csv: str | Path | None = None,
    leadership_csv: str | Path | None = None,
    margin_csv: str | Path | None = None,
    scores_csv: str | Path | None = None,
    futures_csv: str | Path | None = None,
    options_csv: str | Path | None = None,
    field_map: str | Path | None = None,
    snapshot_path: str | Path | None = None,
    write_manifest: bool = True,
    command: str | None = None,
) -> dict[str, Any]:
    """Run provider assembly -> daily production -> validation -> summary.

    Warning-only validation results are surfaced but are not made blocking here;
    blocking behavior follows :func:`validate_daily_artifacts` errors.
    """

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    provider_warnings: tuple[str, ...] = ()
    assembled_snapshot_path: Path | None = None
    bcd_enrichment_trace: dict[str, Any] | None = None
    bcd_enrichment_path: Path | None = None
    snapshot: DailyMarketSnapshot

    if snapshot_path is not None:
        snapshot = load_daily_snapshot_json(snapshot_path)
        enrichment = enrich_bcd_features(
            snapshot,
            BCDFeatureBuilderContext(trade_date=as_of, output_dir=destination),
        )
        snapshot = enrichment.snapshot
        bcd_enrichment_trace = dict(enrichment.trace)
        assembled_snapshot_path = Path(snapshot_path)
    else:
        if price_csv is None:
            raise ValueError("--price-csv is required unless --snapshot-path is supplied")
        snapshot, provider_warnings, assembled_snapshot_path, bcd_enrichment_trace = _assemble_snapshot(
            as_of=as_of,
            output_dir=destination,
            snapshot_out=snapshot_out,
            price_csv=price_csv,
            foreign_csv=foreign_csv,
            fx_csv=fx_csv,
            breadth_csv=breadth_csv,
            leadership_csv=leadership_csv,
            margin_csv=margin_csv,
            scores_csv=scores_csv,
            futures_csv=futures_csv,
            options_csv=options_csv,
            field_map=field_map,
        )

    if bcd_enrichment_trace is not None:
        pre_bcd = _bcd_result_from_snapshot(snapshot, taiex_return_pct=float(snapshot.canonical_row.get("one_day_return_pct") or 0.0))
        bcd_enrichment_trace["bcd_status_after_enrichment"] = pre_bcd.data_quality_status
        bcd_enrichment_trace["missing_components_after_enrichment"] = list(pre_bcd.missing_components)
        bcd_enrichment_path = write_bcd_feature_enrichment_trace(bcd_enrichment_trace, destination)

    production = run_daily_production(
        as_of=as_of,
        output_dir=destination,
        snapshot=snapshot,
        write_manifest=write_manifest,
        command=command,
    )
    bcd_artifacts = write_bcd_audit_artifacts(production.payload, destination)
    validation = validate_daily_artifacts(production.json_path, production.markdown_path, as_of=as_of)
    result = _build_pipeline_result(
        production=production,
        validation=validation.as_dict(),
        provider_warnings=provider_warnings,
        assembled_snapshot_path=assembled_snapshot_path,
        extra_artifacts={**bcd_artifacts, **({"bcd_feature_enrichment_trace": bcd_enrichment_path} if bcd_enrichment_path else {})},
    )
    summary = result.as_dict()
    if bcd_enrichment_trace is not None:
        summary["bcd_feature_enrichment"] = {
            "status": bcd_enrichment_trace.get("enrichment_status"),
            "generated_fields": list(bcd_enrichment_trace.get("generated_fields") or []),
            "unavailable_fields": list(bcd_enrichment_trace.get("unavailable_fields") or []),
            "missing_reasons": dict(bcd_enrichment_trace.get("missing_reasons") or {}),
            "trace_path": str(bcd_enrichment_path) if bcd_enrichment_path else None,
        }
    return summary


def render_operator_summary(result: Mapping[str, Any]) -> str:
    """Render the concise line-oriented summary operators see in the CLI."""

    scores = _mapping(result.get("scores"))
    artifacts = _mapping(result.get("artifact_paths"))
    lines = [
        "TDT-RM daily production pipeline summary",
        f"trade_date: {result.get('trade_date')}",
        f"data_status: {result.get('data_status')}",
        f"signal: {result.get('signal')}",
        f"exposure_limit: {result.get('exposure_limit')}",
        f"TCWRS: {scores.get('TCWRS')}",
        f"MHS: {scores.get('MHS')}",
        f"ETI-5: {scores.get('ETI-5')}",
        "available_eti_components: " + (", ".join(str(item) for item in result.get("available_eti_components", []) or []) or "none"),
        f"Tail Risk: {scores.get('Tail Risk')}",
        f"BCD: {scores.get('BCD')}",
        f"CP: {scores.get('CP')}",
        f"production_report_quality: {result.get('production_report_quality')}",
        f"fallback_proxies: {json.dumps(result.get('fallback_proxies', {}), ensure_ascii=False, sort_keys=True)}",
        "provider_warnings: " + (str(len(result.get("provider_warnings", []) or []))),
    ]
    for warning in result.get("provider_warnings", []) or []:
        lines.append(f"- {warning}")
    lines.append(f"validation_status: {result.get('validation_status')}")
    lines.append("artifact_paths:")
    for name in ("assembled_snapshot", "json", "markdown", "manifest", "bcd_audit_trace_json", "bcd_audit_trace_csv"):
        if artifacts.get(name):
            lines.append(f"  {name}: {artifacts[name]}")
    return "\n".join(lines)


def render_market_result_block(result: Mapping[str, Any]) -> str:
    """Render the operator-required market-result block for task summaries."""

    scores = _mapping(result.get("scores"))
    action = _recommended_action(result)
    cp_value = scores.get("CP")
    lines = [
        "TODAY'S TDT-RM MARKET RESULT",
        "",
        f"Data Date: {result.get('trade_date')}",
        f"Signal: {result.get('signal')}",
        f"Regime State: {_result_value(result, 'regime_state', 'market_regime', default='watch')}",
        f"TCWRS: {scores.get('TCWRS')}",
        f"MHS: {scores.get('MHS')}",
        f"ETI-5: {scores.get('ETI-5')}",
        f"Tail Risk: {scores.get('Tail Risk')}",
        f"BCD: {scores.get('BCD')}",
        f"Crash Probability: {_format_crash_probability(cp_value)}",
        f"Exposure Limit: {result.get('exposure_limit')}",
        f"Production Report Quality: {result.get('production_report_quality')}",
        f"Recommended Action: {action}",
    ]
    return "\n".join(lines)


def render_final_operator_report(result: Mapping[str, Any]) -> str:
    """Render Dr. Yen's final user-facing daily investment risk report."""

    payload = _payload_for_user_report(result)
    return render_user_daily_report(payload)


def _payload_for_user_report(result: Mapping[str, Any]) -> Mapping[str, Any]:
    artifacts = _mapping(result.get("artifact_paths"))
    json_path = artifacts.get("json")
    if json_path:
        path = Path(str(json_path))
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, Mapping):
                merged = dict(payload)
                merged.setdefault("trade_date", result.get("trade_date"))
                merged.setdefault("signal", result.get("signal"))
                merged.setdefault("equity_exposure_limit", result.get("exposure_limit"))
                merged.setdefault("market_regime", _result_value(result, "regime_state", "market_regime", default="watch"))
                if "scores" not in merged and isinstance(result.get("scores"), Mapping):
                    merged["scores"] = dict(_mapping(result.get("scores")))
                data = dict(_mapping(merged.get("data")))
                data.setdefault("status", result.get("data_status"))
                data.setdefault("latest_bar_date", result.get("latest_bar_date") or result.get("trade_date"))
                merged["data"] = data
                return merged
    return {
        "trade_date": result.get("trade_date"),
        "signal": result.get("signal"),
        "equity_exposure_limit": result.get("exposure_limit"),
        "market_regime": _result_value(result, "regime_state", "market_regime", default="watch"),
        "scores": dict(_mapping(result.get("scores"))),
        "data": {"status": result.get("data_status"), "latest_bar_date": result.get("latest_bar_date") or result.get("trade_date")},
    }


def write_final_operator_reports(
    result: Mapping[str, Any],
    reports_dir: str | Path = "reports",
    *,
    pipeline_summary_path: str | Path | None = None,
) -> dict[str, Path]:
    """Write dated and latest operator reports, returning their paths.

    When a selected pipeline summary is supplied, fail closed unless the
    operator-facing report would cite the exact canonical JSON artifact and
    manifest recorded by that summary.
    """

    destination = Path(reports_dir)
    if pipeline_summary_path is not None:
        validate_operator_report_canonical_sources(result, pipeline_summary_path, duplicate_family_roots=(Path(pipeline_summary_path).parent, destination / "artifacts", Path("reports") / "artifacts"))

    destination.mkdir(parents=True, exist_ok=True)
    report = render_final_operator_report(result)
    trade_date = str(result.get("trade_date"))
    dated_path = destination / f"{trade_date}_tdt_rm_user_report.md"
    latest_path = destination / "latest_report.md"
    dated_path.write_text(report, encoding="utf-8")
    latest_path.write_text(report, encoding="utf-8")
    root_latest = Path("reports") / "latest_report.md"
    should_update_root_latest = not destination.is_absolute() and (destination == Path("reports") or Path("reports") in destination.parents)
    if should_update_root_latest and latest_path.resolve() != root_latest.resolve():
        root_latest.parent.mkdir(parents=True, exist_ok=True)
        root_latest.write_text(report, encoding="utf-8")
    return {"dated": dated_path, "latest": latest_path}


def validate_operator_report_canonical_sources(
    result: Mapping[str, Any],
    pipeline_summary_path: str | Path,
    *,
    duplicate_family_roots: Sequence[str | Path] | None = None,
) -> None:
    """Fail closed when operator-facing source paths differ from the selected summary."""

    summary_path = Path(pipeline_summary_path)
    summary = _load_summary_object(summary_path)
    summary_artifacts = _mapping(summary.get("artifact_paths"))
    result_artifacts = _mapping(result.get("artifact_paths"))
    trade_date = str(summary.get("trade_date") or result.get("trade_date") or "")

    for key in ("json", "manifest"):
        expected = summary_artifacts.get(key)
        actual = result_artifacts.get(key)
        if not expected or not actual:
            raise ValueError(f"canonical source guard missing artifact_paths.{key} in selected pipeline summary or report result")
        if _canonical_path_string(expected) != _canonical_path_string(actual):
            raise ValueError(
                f"canonical source guard mismatch for artifact_paths.{key}: "
                f"selected pipeline_summary.json has {expected!r}, report would cite {actual!r}"
            )
        if "_strict_provider_csvs" in Path(str(actual)).parts:
            raise ValueError(f"canonical source guard rejected staging artifact as operator source: artifact_paths.{key}={actual}")

    duplicate_families = detect_duplicate_operator_artifact_families(trade_date, duplicate_family_roots or (summary_path.parent, Path("reports") / "artifacts"))
    canonical_json = _canonical_path_string(summary_artifacts["json"])
    noncanonical = [family for family in duplicate_families if _canonical_path_string(family.get("json", "")) != canonical_json]
    if noncanonical:
        locations = ", ".join(str(family.get("root")) for family in noncanonical)
        raise ValueError(f"canonical source guard detected duplicate operator artifact families for {trade_date}: {locations}")


def detect_duplicate_operator_artifact_families(trade_date: str, roots: Sequence[str | Path]) -> list[dict[str, str]]:
    """Return complete daily JSON/manifest/pipeline-summary families below roots."""

    families: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_root in roots:
        root = Path(raw_root)
        if not root.exists():
            continue
        for json_path in root.rglob(f"tdt_rm_daily_{trade_date}.json"):
            manifest_path = json_path.with_name(f"tdt_rm_daily_{trade_date}_manifest.json")
            summary_path = json_path.parent / "pipeline_summary.json"
            if not manifest_path.exists() or not summary_path.exists():
                continue
            family = {"root": str(json_path.parent), "json": str(json_path), "manifest": str(manifest_path), "pipeline_summary": str(summary_path)}
            identity = (family["root"], family["json"], family["manifest"])
            if identity not in seen:
                seen.add(identity)
                families.append(family)
    return families


def _load_summary_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read selected pipeline summary {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"selected pipeline summary must be a JSON object: {path}")
    return payload


def _canonical_path_string(value: Any) -> str:
    return str(Path(str(value)))


def render_report_task_summary(report_path: str | Path, result: Mapping[str, Any]) -> str:
    """Render the Codex-visible task summary block plus complete report contents."""

    path = Path(report_path)
    if not path.exists():
        trade_date = result.get("trade_date") or "<YYYY-MM-DD>"
        raise FileNotFoundError(
            f"{path} does not exist. Generate it with: "
            f"python scripts/run_daily_production_pipeline.py --trade-date {trade_date} "
            f"--inputs-dir inputs/daily/{trade_date} --outputs-dir outputs/daily "
            f"--pipeline-summary outputs/daily/tdt_rm_daily_{trade_date}_summary.json"
        )
    return render_market_result_block(result) + "\n\n" + path.read_text(encoding="utf-8")


def _recommended_action(result: Mapping[str, Any]) -> str:
    signal = str(result.get("signal") or "")
    exposure_limit = str(result.get("exposure_limit") or "")
    normalized = signal.lower()
    if normalized == "yellow":
        return "Hold. Do not chase. Do not use leverage."
    if normalized in {"red", "deep red"}:
        return "De-risk according to the approved exposure limit; do not add leverage."
    if normalized == "green":
        return f"Operate within the approved exposure limit ({exposure_limit}); no leverage beyond policy."
    return "Follow the approved decision matrix and do not override validation gate results."


def _final_conclusion(result: Mapping[str, Any]) -> str:
    signal = result.get("signal")
    cp = _format_crash_probability(_mapping(result.get("scores")).get("CP"))
    exposure_limit = result.get("exposure_limit")
    quality = result.get("production_report_quality")
    if quality == "FAIL_FOR_OPERATOR_USE":
        return (
            f"TDT-RM closes the latest available market date with a {signal} signal and crash probability {cp}, "
            "but operator quality control fails. This report is not acceptable for real-world daily use until "
            "the Operator Disclosure blocking reasons are resolved."
        )
    return (
        f"TDT-RM closes the latest available market date with a {signal} signal and crash probability {cp}. "
        f"The operator should follow the recommended action within the approved {exposure_limit} equity exposure band."
    )


def _format_crash_probability(value: Any) -> str:
    if value is None:
        return "None"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 1:
        percent = number * 100
        return f"{number:g} ({percent:.1f}%)"
    return f"{number:g}%"


def _result_value(result: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if result.get(key) is not None:
            return result.get(key)
    return default


def write_json_summary(result: Mapping[str, Any], path: str | Path) -> Path:
    """Write the machine-readable pipeline summary JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _assemble_snapshot(
    *,
    as_of: date,
    output_dir: Path,
    snapshot_out: str | Path | None,
    price_csv: str | Path,
    foreign_csv: str | Path | None,
    fx_csv: str | Path | None,
    breadth_csv: str | Path | None,
    leadership_csv: str | Path | None,
    margin_csv: str | Path | None,
    scores_csv: str | Path | None,
    futures_csv: str | Path | None,
    options_csv: str | Path | None,
    field_map: str | Path | None,
) -> tuple[DailyMarketSnapshot, tuple[str, ...], Path, dict[str, Any]]:
    field_map_values, provider_maps = _load_field_maps(field_map)
    providers = [TAIEXPriceProvider(source_path=price_csv)]
    if foreign_csv:
        providers.append(LocalCsvProvider("foreign_flow_csv", "Local foreign-flow CSV", foreign_csv, "foreign_flow"))
    if fx_csv:
        providers.append(LocalCsvProvider("fx_csv", "Local FX CSV", fx_csv, "fx"))
    if breadth_csv:
        providers.append(LocalCsvProvider("breadth_csv", "Local breadth CSV", breadth_csv, "breadth"))
    if leadership_csv:
        providers.append(LocalCsvProvider("leadership_csv", "Local leadership CSV", leadership_csv, "leadership"))
    if futures_csv:
        providers.append(LocalCsvProvider("futures_csv", "Local futures CSV", futures_csv, "futures"))
    if options_csv:
        providers.append(LocalCsvProvider("options_csv", "Local options CSV", options_csv, "options"))
    if margin_csv:
        providers.append(LocalCsvProvider("margin_csv", "Local margin CSV", margin_csv, "margin"))
    if scores_csv:
        providers.append(ManualScoreProvider("scores_csv", "Local manual/formal scores CSV", _load_score_row(scores_csv, as_of)))

    input_paths = {
        "price": price_csv,
        "foreign_flow": foreign_csv,
        "fx": fx_csv,
        "breadth": breadth_csv,
        "leadership": leadership_csv,
        "margin": margin_csv,
        "scores": scores_csv,
        "futures": futures_csv,
        "options": options_csv,
    }
    assembly = DailySnapshotAssembler(providers).assemble(
        DailyProviderContext(as_of=as_of, field_map=field_map_values, provider_field_maps=provider_maps)
    )
    if assembly.provider_errors:
        raise ValueError("provider assembly failed: " + "; ".join(assembly.provider_errors))
    if not assembly.validation.is_valid:
        details = "; ".join(issue.message for issue in assembly.validation.issues if issue.severity == "error")
        raise ValueError(f"daily snapshot validation failed: {details}")

    enrichment = enrich_bcd_features(
        assembly.snapshot,
        BCDFeatureBuilderContext(trade_date=as_of, output_dir=output_dir, input_paths=input_paths),
    )
    snapshot = enrichment.snapshot
    enrichment_trace = dict(enrichment.trace)

    snapshot_path = Path(snapshot_out) if snapshot_out is not None else output_dir / f"assembled_daily_snapshot_{as_of.isoformat()}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.as_dict()
    payload["assembly"] = {
        "supplied_providers": [item.provider_id for item in assembly.provider_results],
        "provider_errors": list(assembly.provider_errors),
        "conflicts": list(assembly.conflicts),
        "missing_field_categories": list(assembly.missing_field_categories),
    }
    payload["validation"] = assembly.validation.as_dict()
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot, tuple(assembly.warnings), snapshot_path, enrichment_trace


def _build_pipeline_result(
    *,
    production: DailyRunResult,
    validation: Mapping[str, Any],
    provider_warnings: tuple[str, ...],
    assembled_snapshot_path: Path | None,
    extra_artifacts: Mapping[str, Path] | None = None,
) -> DailyPipelineResult:
    payload = production.payload
    data = _mapping(payload.get("data"))
    scores = _mapping(payload.get("scores"))
    artifacts: dict[str, str] = {
        "json": str(production.json_path),
        "markdown": str(production.markdown_path),
    }
    if production.manifest_path is not None:
        artifacts["manifest"] = str(production.manifest_path)
    if assembled_snapshot_path is not None:
        artifacts["assembled_snapshot"] = str(assembled_snapshot_path)
    for key, value in (extra_artifacts or {}).items():
        artifacts[str(key)] = str(value)

    quality = _mapping(payload.get("operator_disclosure")) or assess_production_report_quality(payload)

    return DailyPipelineResult(
        trade_date=str(payload.get("trade_date")),
        data_status=str(data.get("status") or data.get("data_status")) if data else None,
        signal=str(payload.get("signal")) if payload.get("signal") is not None else None,
        exposure_limit=str(payload.get("equity_exposure_limit")) if payload.get("equity_exposure_limit") is not None else None,
        regime_state=str(payload.get("market_regime") or payload.get("regime_state")) if (payload.get("market_regime") or payload.get("regime_state")) is not None else None,
        latest_bar_date=str(data.get("latest_bar_date")) if data.get("latest_bar_date") is not None else None,
        scores=scores,
        available_eti_components=tuple(str(item) for item in data.get("available_eti_components", []) or []),
        fallback_proxies=dict(data.get("fallback_proxies", {})) if isinstance(data.get("fallback_proxies"), Mapping) else {},
        provider_warnings=provider_warnings,
        validation=validation,
        artifact_paths=artifacts,
        production_report_quality=str(quality.get("production_report_quality")) if quality.get("production_report_quality") is not None else None,
        operator_disclosure=quality,
        assembled_snapshot_path=str(assembled_snapshot_path) if assembled_snapshot_path is not None else None,
    )


def _load_field_maps(path: str | Path | None) -> tuple[dict[str, str], dict[str, Mapping[str, str]]]:
    if not path:
        return {}, {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--field-map must be a JSON object")
    provider_maps = payload.get("providers") or payload.get("provider_field_maps") or {}
    categories = payload.get("categories") or {}
    if not categories and not provider_maps:
        categories = {key: value for key, value in payload.items() if isinstance(value, dict)}
    global_map = payload.get("global") or {}
    if not global_map:
        global_map = {key: value for key, value in payload.items() if isinstance(value, str)}
    scoped: dict[str, Mapping[str, str]] = {}
    for group in (provider_maps, categories):
        if isinstance(group, dict):
            for key, value in group.items():
                if isinstance(value, dict):
                    _fail_if_forbidden_bcd_field_map(value)
                    scoped[str(key)] = {str(k): str(v) for k, v in value.items()}
    _fail_if_forbidden_bcd_field_map(global_map)
    return {str(key): str(value) for key, value in global_map.items()}, scoped


def _fail_if_forbidden_bcd_field_map(field_map: Mapping[str, Any]) -> None:
    offenders = [f"{left}->{right}" for left, right in field_map.items() if str(left) in FORBIDDEN_PROVIDER_BCD_FIELDS or str(right) in FORBIDDEN_PROVIDER_BCD_FIELDS]
    if offenders:
        raise ValueError(f"forbidden provider BCD field_map entry(ies): {', '.join(offenders)}. {PROVIDER_BCD_FORBIDDEN_MESSAGE}")


def _load_score_row(path: str | Path, as_of: date) -> Mapping[str, Any]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    if len(rows) == 1:
        return rows[0]
    for row in rows:
        for key in ("observed_at", "trade_date", "date"):
            if row.get(key) and date.fromisoformat(str(row[key])[:10]) == as_of:
                return row
    return rows[-1]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
