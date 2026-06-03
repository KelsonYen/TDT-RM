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
from typing import Any, Mapping

from .daily_providers import (
    DailyProviderContext,
    DailySnapshotAssembler,
    LocalCsvProvider,
    ManualScoreProvider,
    TAIEXPriceProvider,
)
from .daily_runner import DailyRunResult, run_daily_production
from .daily_snapshot import DailyMarketSnapshot, load_daily_snapshot_json
from .daily_validation import validate_daily_artifacts


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
    scores: Mapping[str, Any]
    available_eti_components: tuple[str, ...]
    fallback_proxies: Mapping[str, Any]
    provider_warnings: tuple[str, ...]
    validation: Mapping[str, Any]
    artifact_paths: Mapping[str, str]
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
    snapshot: DailyMarketSnapshot

    if snapshot_path is not None:
        snapshot = load_daily_snapshot_json(snapshot_path)
        assembled_snapshot_path = Path(snapshot_path)
    else:
        if price_csv is None:
            raise ValueError("--price-csv is required unless --snapshot-path is supplied")
        snapshot, provider_warnings, assembled_snapshot_path = _assemble_snapshot(
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
            field_map=field_map,
        )

    production = run_daily_production(
        as_of=as_of,
        output_dir=destination,
        snapshot=snapshot,
        write_manifest=write_manifest,
        command=command,
    )
    validation = validate_daily_artifacts(production.json_path, production.markdown_path, as_of=as_of)
    result = _build_pipeline_result(
        production=production,
        validation=validation.as_dict(),
        provider_warnings=provider_warnings,
        assembled_snapshot_path=assembled_snapshot_path,
    )
    return result.as_dict()


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
        f"fallback_proxies: {json.dumps(result.get('fallback_proxies', {}), ensure_ascii=False, sort_keys=True)}",
        "provider_warnings: " + (str(len(result.get("provider_warnings", []) or []))),
    ]
    for warning in result.get("provider_warnings", []) or []:
        lines.append(f"- {warning}")
    lines.append(f"validation_status: {result.get('validation_status')}")
    lines.append("artifact_paths:")
    for name in ("assembled_snapshot", "json", "markdown", "manifest"):
        if artifacts.get(name):
            lines.append(f"  {name}: {artifacts[name]}")
    return "\n".join(lines)


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
    field_map: str | Path | None,
) -> tuple[DailyMarketSnapshot, tuple[str, ...], Path]:
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
    if margin_csv:
        providers.append(LocalCsvProvider("margin_csv", "Local margin CSV", margin_csv, "margin"))
    if scores_csv:
        providers.append(ManualScoreProvider("scores_csv", "Local manual/formal scores CSV", _load_score_row(scores_csv, as_of)))

    assembly = DailySnapshotAssembler(providers).assemble(
        DailyProviderContext(as_of=as_of, field_map=field_map_values, provider_field_maps=provider_maps)
    )
    if assembly.provider_errors:
        raise ValueError("provider assembly failed: " + "; ".join(assembly.provider_errors))
    if not assembly.validation.is_valid:
        details = "; ".join(issue.message for issue in assembly.validation.issues if issue.severity == "error")
        raise ValueError(f"daily snapshot validation failed: {details}")

    snapshot_path = Path(snapshot_out) if snapshot_out is not None else output_dir / f"assembled_daily_snapshot_{as_of.isoformat()}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = assembly.snapshot.as_dict()
    payload["assembly"] = {
        "supplied_providers": [item.provider_id for item in assembly.provider_results],
        "provider_errors": list(assembly.provider_errors),
        "conflicts": list(assembly.conflicts),
        "missing_field_categories": list(assembly.missing_field_categories),
    }
    payload["validation"] = assembly.validation.as_dict()
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return assembly.snapshot, tuple(assembly.warnings), snapshot_path


def _build_pipeline_result(
    *,
    production: DailyRunResult,
    validation: Mapping[str, Any],
    provider_warnings: tuple[str, ...],
    assembled_snapshot_path: Path | None,
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

    return DailyPipelineResult(
        trade_date=str(payload.get("trade_date")),
        data_status=str(data.get("status") or data.get("data_status")) if data else None,
        signal=str(payload.get("signal")) if payload.get("signal") is not None else None,
        exposure_limit=str(payload.get("equity_exposure_limit")) if payload.get("equity_exposure_limit") is not None else None,
        scores=scores,
        available_eti_components=tuple(str(item) for item in data.get("available_eti_components", []) or []),
        fallback_proxies=dict(data.get("fallback_proxies", {})) if isinstance(data.get("fallback_proxies"), Mapping) else {},
        provider_warnings=provider_warnings,
        validation=validation,
        artifact_paths=artifacts,
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
                    scoped[str(key)] = {str(k): str(v) for k, v in value.items()}
    return {str(key): str(value) for key, value in global_map.items()}, scoped


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
