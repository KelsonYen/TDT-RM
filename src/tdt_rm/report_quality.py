"""Production report quality-control disclosure helpers.

These helpers audit report provenance and operator-facing completeness only. They
intentionally do not alter TDT-RM scoring, signal, exposure, ETF Exit, TCWRS,
MHS, ETI, Tail Risk, BCD, or Crash Probability formulas.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

QUALITY_PASS = "PASS"
QUALITY_PASS_WITH_DISCLOSURE = "PASS_WITH_DISCLOSURE"
QUALITY_FAIL_FOR_OPERATOR_USE = "FAIL_FOR_OPERATOR_USE"
QUALITY_VALUES = (QUALITY_PASS, QUALITY_PASS_WITH_DISCLOSURE, QUALITY_FAIL_FOR_OPERATOR_USE)

_TOP_LEVEL_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "Tail Risk": ("tail_risk",),
    "BCD": ("bcd",),
    "Crash Probability": ("tail_risk", "bcd"),
}
_PLACEHOLDER_GLOBAL_FIELDS = ("nasdaq", "sox")
_GLOBAL_FIELDS = ("nasdaq", "nasdaq_ma20", "sox", "sox_ma20", "sox_ma60")
_OFFICIAL_MARKERS = ("OFFICIAL", "TAIFEX", "TWSE", "CBC")
_FALLBACK_MARKERS = ("FALLBACK", "FINMIND_FALLBACK", "LOCAL_FALLBACK")
_CONFIRMED_FALLBACK_NAMED_PROVIDERS = {"FINMIND_FALLBACK:TAIWANOPTIONDAILY:TXO"}
_UNAVAILABLE_GLOBAL_FIELD_KEYS = ("unavailable_global_risk_fields", "operator_unavailable_fields")


def assess_production_report_quality(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return machine-readable production report QC metadata for a daily payload."""

    data = _mapping(payload.get("data"))
    field_sources = _mapping(data.get("field_sources"))
    source_metadata = _mapping(data.get("source_metadata"))
    etf_exit = _mapping(payload.get("etf_exit"))

    official_datasets = _provider_datasets(source_metadata, fallback=False)
    fallback_datasets = _provider_datasets(source_metadata, fallback=True)
    fallback_dependencies = _fallback_dependencies(field_sources, source_metadata)
    placeholder_fields = _placeholder_global_fields(payload, field_sources)
    non_integrated_modules = _non_integrated_modules(etf_exit)

    blocking_reasons: list[str] = []
    if fallback_dependencies:
        impacted = ", ".join(item["operator_field"] for item in fallback_dependencies)
        blocking_reasons.append(f"fallback provider data feeds top-level operator field(s): {impacted}")
    if placeholder_fields:
        fields = ", ".join(item["field"] for item in placeholder_fields)
        blocking_reasons.append(f"default-like global-risk field(s) without confirmed source: {fields}")

    module_warnings = non_integrated_modules
    if blocking_reasons:
        quality = QUALITY_FAIL_FOR_OPERATOR_USE
        acceptable = False
    else:
        quality = QUALITY_PASS
        acceptable = True

    return {
        "production_report_quality": quality,
        "acceptable_for_real_world_daily_use": acceptable,
        "official_provider_datasets": official_datasets,
        "fallback_provider_datasets": fallback_datasets,
        "fallback_operator_dependencies": fallback_dependencies,
        "placeholder_default_like_fields": placeholder_fields,
        "non_integrated_modules": non_integrated_modules,
        "non_blocking_module_warnings": module_warnings,
        "blocking_reasons": blocking_reasons,
    }


def render_operator_disclosure(quality: Mapping[str, Any]) -> str:
    """Render the Operator Disclosure Markdown section."""

    lines = [
        "## Operator Disclosure",
        "",
        f"* Production Report Quality: `{quality.get('production_report_quality')}`",
        f"* Acceptable for Real-World Daily Use: `{'YES' if quality.get('acceptable_for_real_world_daily_use') else 'NO'}`",
        "",
        "### Blocking Quality Failures",
        *(_bullet_lines(quality.get("blocking_reasons"), empty="No blocking quality-control reasons detected.")),
        "",
        "### Non-Blocking Module Warnings",
        *_bullet_lines(_module_warnings(quality), empty="none reported"),
        "",
        "### Data-Source Warnings",
        "#### Fallback Provider Datasets",
        *_bullet_lines(quality.get("fallback_provider_datasets"), empty="none reported"),
        "",
        "#### Fallback-Dependent Operator Fields",
        *_bullet_lines(quality.get("fallback_operator_dependencies"), empty="none reported"),
        "",
        "#### Placeholder / Default-Like Fields",
        *_bullet_lines(quality.get("placeholder_default_like_fields"), empty="none reported"),
        "",
        "### Official Provider Datasets",
        *_bullet_lines(quality.get("official_provider_datasets"), empty="none reported"),
        "",
    ]
    return "\n".join(lines)


def _module_warnings(quality: Mapping[str, Any]) -> Any:
    warnings = quality.get("non_blocking_module_warnings")
    return warnings if warnings is not None else quality.get("non_integrated_modules")


def _provider_datasets(source_metadata: Mapping[str, Any], *, fallback: bool) -> list[dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    for source_id, raw_metadata in sorted(source_metadata.items()):
        metadata = _mapping(raw_metadata)
        provider_source = str(metadata.get("provider_source") or "")
        source_type = str(metadata.get("source_type") or "")
        text = " ".join([str(source_id), provider_source, source_type, str(metadata.get("name") or "")]).upper()
        is_fallback = _is_fallback_source(str(source_id), metadata)
        is_official = (
            any(marker in text for marker in _OFFICIAL_MARKERS) or _is_confirmed_provider(metadata)
        ) and not is_fallback
        if fallback and is_fallback:
            datasets.append(_dataset_entry(str(source_id), metadata))
        elif not fallback and is_official:
            datasets.append(_dataset_entry(str(source_id), metadata))
    return datasets


def _dataset_entry(source_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "category": metadata.get("category"),
        "provider_source": metadata.get("provider_source"),
        "source_type": metadata.get("source_type"),
        "name": metadata.get("name"),
        "notes": metadata.get("notes"),
    }


def _fallback_dependencies(field_sources: Mapping[str, Any], source_metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    dependencies: list[dict[str, Any]] = []
    for operator_field, canonical_fields in _TOP_LEVEL_DEPENDENCIES.items():
        for canonical_field in canonical_fields:
            source_id = _field_source_id(field_sources.get(canonical_field))
            metadata = _mapping(source_metadata.get(source_id)) if source_id else {}
            if source_id and _is_fallback_source(source_id, metadata):
                dependencies.append(
                    {
                        "operator_field": operator_field,
                        "canonical_field": canonical_field,
                        "source_id": source_id,
                        "provider_source": metadata.get("provider_source"),
                        "source_type": metadata.get("source_type"),
                    }
                )
                break
    return dependencies


def _placeholder_global_fields(payload: Mapping[str, Any], field_sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = _find_global_field_values(payload)
    fields: list[dict[str, Any]] = []
    for field in _PLACEHOLDER_GLOBAL_FIELDS:
        if (
            field in values
            and _is_zero_like(values[field])
            and not _field_source_id(field_sources.get(field))
            and field not in _unavailable_global_fields(payload)
        ):
            fields.append(
                {"field": field, "value": values[field], "reason": "0.0 default-like value and no confirmed source"}
            )
    return fields


def _find_global_field_values(value: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for field in _GLOBAL_FIELDS:
            if field in value and field not in found:
                found[field] = value[field]
        for child in value.values():
            found.update({k: v for k, v in _find_global_field_values(child).items() if k not in found})
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found.update({k: v for k, v in _find_global_field_values(child).items() if k not in found})
    return found


def _non_integrated_modules(etf_exit: Mapping[str, Any]) -> list[dict[str, Any]]:
    status = str(etf_exit.get("status") or "").lower()
    if status == "not_integrated":
        return [{"module": "ETF Exit", "status": etf_exit.get("status"), "notes": etf_exit.get("notes")}]
    return []


def _is_confirmed_provider(metadata: Mapping[str, Any]) -> bool:
    return (
        str(metadata.get("provider_source") or "").upper() in _CONFIRMED_FALLBACK_NAMED_PROVIDERS
        and str(metadata.get("source_type") or "").upper() == "REAL_PROVIDER"
    )


def _is_fallback_source(source_id: str, metadata: Mapping[str, Any]) -> bool:
    provider_source = str(metadata.get("provider_source") or "").upper()
    source_type = str(metadata.get("source_type") or "").upper()
    if _is_confirmed_provider(metadata):
        return False
    text = " ".join([source_id, provider_source, source_type, str(metadata.get("name") or "")]).upper()
    return any(marker in text for marker in _FALLBACK_MARKERS)


def _unavailable_global_fields(payload: Mapping[str, Any]) -> set[str]:
    data = _mapping(payload.get("data"))
    unavailable: set[str] = set()
    for container in (data, payload):
        for key in _UNAVAILABLE_GLOBAL_FIELD_KEYS:
            raw = container.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                unavailable.update(str(item) for item in raw)
            elif isinstance(raw, Mapping):
                unavailable.update(str(field) for field, value in raw.items() if value)
    return unavailable


def _field_source_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        raw = value.get("source_id")
        return str(raw) if raw else None
    return str(value) if value else None


def _is_zero_like(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def _bullet_lines(items: Any, *, empty: str) -> list[str]:
    if not items:
        return [f"* {empty}"]
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        return [f"* {_format_item(item)}" for item in items]
    return [f"* {_format_item(items)}"]


def _format_item(item: Any) -> str:
    if isinstance(item, Mapping):
        preferred = []
        for key in ("source_id", "provider_source", "source_type", "operator_field", "canonical_field", "field", "module", "status", "reason", "notes"):
            if key in item and item.get(key) not in (None, ""):
                preferred.append(f"{key}={item.get(key)}")
        return "; ".join(preferred) if preferred else str(dict(item))
    return str(item)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
