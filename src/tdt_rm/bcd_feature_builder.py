"""Derived BCD recovery feature enrichment for daily snapshots.

This module derives only auditable BCD inputs from provider rows or local daily
artifacts.  It never fabricates neutral values and never backfills from an
existing BCD score.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .daily_snapshot import DailyMarketSnapshot

BCD_RECOVERY_FIELDS: tuple[str, ...] = (
    "breadth_history",
    "main7_closes",
    "main7_previous_closes",
    "main7_turnover_amounts",
    "main7_returns",
    "main7_weights",
    "main7_concentration",
    "sector_returns",
    "sector_above_ma20",
    "sector_breadth",
    "sector_diffusion",
    "otc_return_pct",
    "small_mid_breadth",
    "small_mid_weakness",
    "turnover_concentration_topn",
    "turnover_concentration",
)

_BCD_DERIVED_SOURCE = "bcd_feature_builder"
_MIN_BREADTH_HISTORY_ROWS = 2
_DEFAULT_TOPN = 10


@dataclass(frozen=True)
class BCDFeatureEnrichmentResult:
    """Enriched immutable snapshot plus an auditable derivation trace."""

    snapshot: DailyMarketSnapshot
    trace: Mapping[str, Any]


@dataclass(frozen=True)
class BCDFeatureBuilderContext:
    """Local artifact paths available to the BCD recovery feature builder."""

    trade_date: date
    output_dir: str | Path | None = None
    input_paths: Mapping[str, str | Path | None] = field(default_factory=dict)
    historical_roots: Sequence[str | Path] = (Path("inputs/daily"), Path("reports/daily"))


def enrich_bcd_features(snapshot: DailyMarketSnapshot, context: BCDFeatureBuilderContext) -> BCDFeatureEnrichmentResult:
    """Return a snapshot enriched with real BCD extras and a trace.

    Existing provider-supplied non-empty fields win.  Derived fields are merged
    only when the canonical row does not already contain a usable value.
    """

    row = dict(snapshot.canonical_row)
    field_sources = dict(snapshot.field_sources)
    source_metadata = {key: dict(value) for key, value in snapshot.source_metadata.items()}
    source_metadata.setdefault(
        _BCD_DERIVED_SOURCE,
        {
            "name": "BCD derived feature builder",
            "notes": "Derives BCD recovery extras from local provider rows/artifacts without score backfill.",
        },
    )

    source_paths_used: list[str] = []
    generated_fields: dict[str, Any] = {}
    generated_from: dict[str, list[str]] = {}
    source_provider: dict[str, str] = {}
    unavailable_fields: list[str] = []
    missing_reasons: dict[str, str] = {}
    derivation_notes: dict[str, str] = {}
    raw_preserved: list[str] = []

    for field_name in BCD_RECOVERY_FIELDS:
        if _present(row.get(field_name)):
            raw_preserved.append(field_name)

    breadth_history, breadth_sources, breadth_window, breadth_reason = _derive_breadth_history(row, context)
    source_paths_used.extend(breadth_sources)
    historical_window_used: dict[str, Any] = {"breadth_history": breadth_window}
    _merge_field(
        "breadth_history",
        breadth_history,
        row,
        field_sources,
        generated_fields,
        unavailable_fields,
        missing_reasons,
        derivation_notes,
        generated_from,
        source_provider,
        breadth_sources,
        "breadth_csv",
        breadth_reason,
        "advancing_issues/declining_issues history from local daily breadth artifacts",
    )

    main7_returns, main7_weights, main7_sources, main7_reasons, main7_symbols_used = _derive_main7(row, context)
    source_paths_used.extend(main7_sources)
    historical_window_used["main7"] = {"symbols": main7_symbols_used, "requires_previous_close": True}
    _merge_field(
        "main7_returns",
        main7_returns,
        row,
        field_sources,
        generated_fields,
        unavailable_fields,
        missing_reasons,
        derivation_notes,
        generated_from,
        source_provider,
        main7_sources,
        "leadership_csv",
        main7_reasons.get("main7_returns"),
        "symbol close vs previous close from leadership/price artifacts",
    )
    _merge_field(
        "main7_weights",
        main7_weights,
        row,
        field_sources,
        generated_fields,
        unavailable_fields,
        missing_reasons,
        derivation_notes,
        generated_from,
        source_provider,
        main7_sources,
        "leadership_csv",
        main7_reasons.get("main7_weights"),
        "market-cap or turnover weights from leadership artifacts",
    )
    if _present(row.get("main7_returns")) and _present(row.get("main7_weights")) and not _present(row.get("main7_concentration")):
        concentration = _weighted_average(_mapping_of_float(row.get("main7_returns")), _mapping_of_float(row.get("main7_weights")))
        _merge_field(
            "main7_concentration",
            concentration,
            row,
            field_sources,
            generated_fields,
            unavailable_fields,
            missing_reasons,
            derivation_notes,
            generated_from,
            source_provider,
            main7_sources,
            "bcd_feature_builder",
            None,
            "weighted Main-7 return derived from main7_returns and main7_weights",
        )
    elif not _present(row.get("main7_concentration")):
        unavailable_fields.append("main7_concentration")
        missing_reasons.setdefault("main7_concentration", "requires both main7_returns and main7_weights; no fake equal weights are used")

    turnover, turnover_sources, turnover_reason, turnover_topn_symbols = _derive_turnover_concentration(row, context)
    source_paths_used.extend(turnover_sources)
    _merge_field(
        "turnover_concentration_topn",
        turnover,
        row,
        field_sources,
        generated_fields,
        unavailable_fields,
        missing_reasons,
        derivation_notes,
        generated_from,
        source_provider,
        turnover_sources,
        "turnover_csv",
        turnover_reason,
        f"top {_DEFAULT_TOPN} turnover_amount share from symbol-level turnover artifacts",
    )
    if _present(row.get("turnover_concentration_topn")) and not _present(row.get("turnover_concentration")):
        _merge_field(
            "turnover_concentration",
            row.get("turnover_concentration_topn"),
            row,
            field_sources,
            generated_fields,
            unavailable_fields,
            missing_reasons,
            derivation_notes,
            generated_from,
            source_provider,
            turnover_sources,
            "turnover_csv",
            None,
            "alias of turnover_concentration_topn for legacy audit output",
        )

    for field_name, reason in _nullable_provider_reasons(row).items():
        if not _present(row.get(field_name)) and field_name not in missing_reasons:
            unavailable_fields.append(field_name)
            missing_reasons[field_name] = reason

    trace = {
        "trade_date": context.trade_date.isoformat(),
        "enrichment_status": "GENERATED" if generated_fields else "NO_FIELDS_GENERATED",
        "generated_fields": sorted(generated_fields),
        "preserved_provider_fields": sorted(raw_preserved),
        "unavailable_fields": sorted(dict.fromkeys(unavailable_fields)),
        "missing_reasons": dict(sorted(missing_reasons.items())),
        "source_paths_used": sorted(dict.fromkeys(source_paths_used)),
        "generated_from": generated_from,
        "source_provider": source_provider,
        "historical_window_used": historical_window_used,
        "field_derivation_notes": dict(sorted(derivation_notes.items())),
        "final_fields_passed_to_BCDInput": _final_bcd_fields(row),
        "main7_symbols_used": main7_symbols_used,
        "turnover_topn_symbols": turnover_topn_symbols,
    }

    enriched = DailyMarketSnapshot(
        trade_date=snapshot.trade_date,
        observed_at=snapshot.observed_at,
        canonical_row=row,
        price_bars=snapshot.price_bars,
        field_sources=field_sources,
        source_metadata=source_metadata,
        data_status=snapshot.data_status,
        limitations=snapshot.limitations,
        warnings=snapshot.warnings,
    )
    return BCDFeatureEnrichmentResult(enriched, trace)


def write_bcd_feature_enrichment_trace(trace: Mapping[str, Any], output_dir: str | Path) -> Path:
    """Write the BCD enrichment trace artifact."""

    path = Path(output_dir) / "bcd_feature_enrichment_trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _merge_field(
    field_name: str,
    value: Any,
    row: dict[str, Any],
    field_sources: dict[str, str],
    generated_fields: dict[str, Any],
    unavailable_fields: list[str],
    missing_reasons: dict[str, str],
    derivation_notes: dict[str, str],
    generated_from: dict[str, list[str]],
    source_provider: dict[str, str],
    source_paths: Sequence[str],
    provider: str,
    missing_reason: str | None,
    note: str,
) -> None:
    if _present(row.get(field_name)):
        return
    if _present(value):
        row[field_name] = value
        field_sources[field_name] = _BCD_DERIVED_SOURCE
        generated_fields[field_name] = value
        derivation_notes[field_name] = note
        generated_from[field_name] = sorted(dict.fromkeys(str(path) for path in source_paths))
        source_provider[field_name] = provider
        return
    unavailable_fields.append(field_name)
    if missing_reason:
        missing_reasons[field_name] = missing_reason


def _derive_breadth_history(row: Mapping[str, Any], context: BCDFeatureBuilderContext) -> tuple[list[dict[str, Any]] | None, list[str], dict[str, Any], str | None]:
    records: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for item, path in _iter_breadth_rows(context):
        trade_date = str(item.get("trade_date") or item.get("observed_at") or item.get("date") or "")
        if not trade_date or trade_date > context.trade_date.isoformat():
            continue
        adv = _optional_int(item.get("advancing_issues"))
        dec = _optional_int(item.get("declining_issues"))
        if adv is None or dec is None:
            continue
        records[trade_date] = {
            "trade_date": trade_date,
            "advancing_issues": adv,
            "declining_issues": dec,
            "taiex_return_pct": _optional_float(item.get("taiex_return_pct") or item.get("one_day_return_pct")),
        }
        sources.append(str(path))
    current_date = context.trade_date.isoformat()
    current_adv = _optional_int(row.get("advancing_issues"))
    current_dec = _optional_int(row.get("declining_issues"))
    if current_adv is not None and current_dec is not None:
        records[current_date] = {
            "trade_date": current_date,
            "advancing_issues": current_adv,
            "declining_issues": current_dec,
            "taiex_return_pct": _optional_float(row.get("one_day_return_pct")),
        }
    ordered = [records[key] for key in sorted(records)]
    window = {
        "start": ordered[0]["trade_date"] if ordered else None,
        "end": ordered[-1]["trade_date"] if ordered else None,
        "rows": len(ordered),
        "minimum_rows": _MIN_BREADTH_HISTORY_ROWS,
    }
    if len(ordered) < _MIN_BREADTH_HISTORY_ROWS:
        return None, sources, window, f"requires at least {_MIN_BREADTH_HISTORY_ROWS} real breadth rows; found {len(ordered)}"
    return ordered, sources, window, None


def _iter_breadth_rows(context: BCDFeatureBuilderContext) -> list[tuple[Mapping[str, Any], Path]]:
    paths: list[Path] = []
    explicit = context.input_paths.get("breadth") or context.input_paths.get("breadth_csv")
    if explicit:
        paths.append(Path(explicit))
    for root in context.historical_roots:
        root_path = Path(root)
        if root_path.name == "daily" and root_path.parent.name == "inputs":
            paths.extend(root_path.glob("*/breadth.csv"))
            paths.extend(root_path.glob("*/twse_market_breadth.csv"))
        else:
            paths.extend(root_path.glob("*/artifacts/assembled_daily_snapshot_*.json"))
    rows: list[tuple[Mapping[str, Any], Path]] = []
    for path in sorted(dict.fromkeys(paths)):
        if not path.exists():
            continue
        if path.suffix.lower() == ".json":
            payload = _read_json(path)
            canonical = payload.get("canonical_row") if isinstance(payload, Mapping) else None
            if isinstance(canonical, Mapping):
                payload_date = str(payload.get("trade_date") or "")
                if payload_date >= context.trade_date.isoformat():
                    continue
                item = dict(canonical)
                item.setdefault("trade_date", payload.get("trade_date"))
                rows.append((item, path))
            continue
        for item in _read_csv_rows(path):
            rows.append((item, path))
    return rows


def _derive_main7(row: Mapping[str, Any], context: BCDFeatureBuilderContext) -> tuple[dict[str, float] | None, dict[str, float] | None, list[str], dict[str, str], list[str]]:
    sources: list[str] = []
    records = _leadership_records(context)
    if records:
        sources.extend(str(path) for _, path in records)
    current = _select_record_for_date(records, context.trade_date)
    previous = _previous_record(records, context.trade_date)
    current_row = dict(current[0]) if current else dict(row)
    previous_row = dict(previous[0]) if previous else {}

    symbols = _symbols_from_row(current_row) or _symbols_from_row(row)
    returns = _returns_from_row(current_row, previous_row, symbols)
    weights = _weights_from_row(current_row, symbols)
    reasons: dict[str, str] = {}
    if not returns:
        reasons["main7_returns"] = "requires Main-7 symbol return fields or today's and previous trading-day closes; no previous closes found"
    if not weights:
        reasons["main7_weights"] = "requires Main-7 market-cap or turnover weights; equal-weight fallback is forbidden"
    return returns or None, weights or None, sources, reasons, list(symbols)


def _leadership_records(context: BCDFeatureBuilderContext) -> list[tuple[Mapping[str, Any], Path]]:
    paths: list[Path] = []
    explicit = context.input_paths.get("leadership") or context.input_paths.get("leadership_csv")
    if explicit:
        paths.append(Path(explicit))
    for root in context.historical_roots:
        root_path = Path(root)
        if root_path.name == "daily" and root_path.parent.name == "inputs":
            paths.extend(root_path.glob("*/leadership.csv"))
    records: list[tuple[Mapping[str, Any], Path]] = []
    for path in sorted(dict.fromkeys(paths)):
        if path.exists():
            for item in _read_csv_rows(path):
                records.append((item, path))
    return records


def _returns_from_row(current: Mapping[str, Any], previous: Mapping[str, Any], symbols: Sequence[str]) -> dict[str, float]:
    direct = _json_mapping(current.get("main7_returns") or current.get("main_7_returns"))
    if direct:
        return _mapping_of_float(direct)
    closes = _symbol_values(current, symbols, ("close", "price"), json_keys=("main7_closes", "main_7_closes", "main7_prices"))
    prev_closes = _symbol_values(current, symbols, ("previous_close", "prev_close"), json_keys=("main7_previous_closes", "main_7_previous_closes"))
    if not prev_closes:
        prev_closes = _symbol_values(previous, symbols, ("close", "price"), json_keys=("main7_closes", "main_7_closes", "main7_prices"))
    returns: dict[str, float] = {}
    for symbol in symbols:
        close = closes.get(symbol)
        prev = prev_closes.get(symbol)
        if close is None or prev in (None, 0):
            continue
        returns[symbol] = round((close - prev) / prev * 100.0, 6)
    return returns


def _weights_from_row(current: Mapping[str, Any], symbols: Sequence[str]) -> dict[str, float]:
    direct = _json_mapping(current.get("main7_weights") or current.get("main_7_weights"))
    if direct:
        return _mapping_of_float(direct)
    candidates = (
        _symbol_values(current, symbols, ("market_cap",), json_keys=("main7_market_caps",)),
        _symbol_values(current, symbols, ("market_value",), json_keys=("main7_market_values",)),
        _symbol_values(current, symbols, ("turnover", "turnover_amount"), json_keys=("main7_turnover", "main7_turnover_amounts")),
    )
    raw = next((candidate for candidate in candidates if any(value > 0 for value in candidate.values())), {})
    total = sum(value for value in raw.values() if value > 0)
    if total <= 0:
        return {}
    return {symbol: round(value / total, 8) for symbol, value in raw.items() if value > 0}


def _derive_turnover_concentration(row: Mapping[str, Any], context: BCDFeatureBuilderContext) -> tuple[float | None, list[str], str | None, list[str]]:
    paths = [Path(value) for key, value in context.input_paths.items() if value and "turnover" in key]
    for root in context.historical_roots:
        root_path = Path(root)
        if root_path.name == "daily" and root_path.parent.name == "inputs":
            paths.extend(root_path.glob(f"{context.trade_date.isoformat()}/*turnover*.csv"))
            paths.extend(root_path.glob(f"{context.trade_date.isoformat()}/*volume*.csv"))
    sources: list[str] = []
    values: list[tuple[str, float]] = []
    for path in sorted(dict.fromkeys(paths)):
        if not path.exists():
            continue
        rows = _read_csv_rows(path)
        symbol_rows = [item for item in rows if item.get("symbol") or item.get("stock_id") or item.get("證券代號")]
        if not symbol_rows:
            sources.append(str(path))
            continue
        for item in symbol_rows:
            symbol = str(item.get("symbol") or item.get("stock_id") or item.get("證券代號") or "").strip()
            amount = _optional_float(item.get("turnover_amount") or item.get("turnover") or item.get("成交金額") or item.get("TradeValue") or item.get("Trading Value"))
            if symbol and amount is not None and amount > 0:
                values.append((symbol, amount))
        sources.append(str(path))
    if not values:
        return None, sources, "requires symbol-level turnover_amount rows; aggregate market turnover cannot produce Top-N concentration", []
    total = sum(amount for _, amount in values)
    if total <= 0:
        return None, sources, "symbol-level turnover rows have non-positive total turnover", []
    topn = sorted(values, key=lambda item: item[1], reverse=True)[:_DEFAULT_TOPN]
    return round(sum(amount for _, amount in topn) / total, 8), sources, None, [symbol for symbol, _ in topn]


def _nullable_provider_reasons(row: Mapping[str, Any]) -> dict[str, str]:
    reasons = {
        "sector_returns": "requires sector provider returns; nullable interface only until real sector source is supplied",
        "sector_above_ma20": "requires sector provider MA20 status; nullable interface only until real sector source is supplied",
        "sector_breadth": "requires sector provider breadth data; no sector source available",
        "sector_diffusion": "requires sector_returns and sector_above_ma20; no sector provider source available",
        "otc_return_pct": "requires OTC index return provider; no OTC source available",
        "small_mid_breadth": "requires small/mid breadth provider; no source available",
        "small_mid_weakness": "requires otc_return_pct and small_mid_breadth; no source available",
    }
    return {field_name: reason for field_name, reason in reasons.items() if not _present(row.get(field_name))}


def _final_bcd_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field_name: row.get(field_name) for field_name in BCD_RECOVERY_FIELDS if _present(row.get(field_name))}


def _select_record_for_date(records: Sequence[tuple[Mapping[str, Any], Path]], trade_date: date) -> tuple[Mapping[str, Any], Path] | None:
    target = trade_date.isoformat()
    matches = [item for item in records if str(item[0].get("trade_date") or item[0].get("observed_at") or item[0].get("date") or "") == target]
    return matches[-1] if matches else None


def _previous_record(records: Sequence[tuple[Mapping[str, Any], Path]], trade_date: date) -> tuple[Mapping[str, Any], Path] | None:
    target = trade_date.isoformat()
    previous = [item for item in records if str(item[0].get("trade_date") or item[0].get("observed_at") or item[0].get("date") or "") < target]
    return sorted(previous, key=lambda item: str(item[0].get("trade_date") or item[0].get("observed_at") or item[0].get("date") or ""))[-1] if previous else None


def _symbols_from_row(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("main_7_symbols") or row.get("main7_symbols") or row.get("symbols")
    if isinstance(raw, str):
        return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


def _symbol_values(row: Mapping[str, Any], symbols: Sequence[str], suffixes: Sequence[str], *, json_keys: Sequence[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for key in json_keys:
        values.update(_mapping_of_float(_json_mapping(row.get(key))))
    for symbol in symbols:
        for suffix in suffixes:
            for key in (f"{symbol}_{suffix}", f"{suffix}_{symbol}"):
                value = _optional_float(row.get(key))
                if value is not None:
                    values[symbol] = value
                    break
            if symbol in values:
                break
    return values


def _weighted_average(values: Mapping[str, float], weights: Mapping[str, float]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for symbol, value in values.items():
        weight = float(weights.get(symbol, 0.0))
        if math.isfinite(weight) and weight > 0:
            numerator += float(value) * weight
            denominator += weight
    return round(numerator / denominator, 6) if denominator > 0 else None


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _mapping_of_float(value: Mapping[str, Any] | None) -> dict[str, float]:
    output: dict[str, float] = {}
    for key, raw in (value or {}).items():
        number = _optional_float(raw)
        if number is not None:
            output[str(key)] = number
    return output


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    return int(number) if number is not None else None


def _present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes)):
        return bool(value)
    return True


__all__ = [
    "BCDFeatureBuilderContext",
    "BCDFeatureEnrichmentResult",
    "BCD_RECOVERY_FIELDS",
    "enrich_bcd_features",
    "write_bcd_feature_enrichment_trace",
]
