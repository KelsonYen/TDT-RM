#!/usr/bin/env python3
"""Probe official public market-data endpoints from GitHub Actions.

This proof-of-concept is intentionally designed for the GitHub Actions runtime:
it performs plain Python ``urllib`` requests from the runner, normalizes each
source through the existing TDT-RM public-data adapters, writes provider CSVs,
and emits per-source PASS/FAIL evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tdt_rm.public_data_fetchers import (
    PublicDataFetchContext,
    PublicDataFetcherRegistry,
    load_main7_symbols,
    load_source_config,
    write_provider_csvs,
)

PROBE_SOURCES: tuple[tuple[str, str], ...] = (
    ("TWSE TAIEX price", "price"),
    ("Foreign investor flow", "foreign_flow"),
    ("Market breadth", "breadth"),
    ("USD/TWD FX", "fx"),
    ("TAIFEX futures", "futures"),
    ("TAIFEX options", "options"),
    ("Main-7 leadership stocks", "leadership"),
)


@dataclass(frozen=True)
class EndpointProbe:
    url: str
    status: int | None
    ok: bool
    error: str | None = None
    sample_payload: Any | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe whether GitHub Actions can fetch TDT-RM market data sources.")
    parser.add_argument("--as-of", default=datetime.now(UTC).date().isoformat(), help="Market date to probe, YYYY-MM-DD. Defaults to the runner's UTC date.")
    parser.add_argument("--source-config", default="config/public_data_sources.json", help="Public data source config JSON path.")
    parser.add_argument("--main7-config", default="config/main7_symbols.json", help="Main-7 symbols JSON path.")
    parser.add_argument("--output-dir", default="outputs/github_actions_market_data_probe", help="Directory for probe artifacts.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds per request.")
    parser.add_argument("--sample-chars", type=int, default=900, help="Maximum sample payload characters in Markdown report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    output_dir = Path(args.output_dir)
    csv_root = output_dir / "csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_root.mkdir(parents=True, exist_ok=True)

    config = load_source_config(args.source_config)
    registry = PublicDataFetcherRegistry.from_config(config)
    main7_symbols = load_main7_symbols(args.main7_config)
    context = PublicDataFetchContext(as_of=as_of, source_config=config, main7_symbols=main7_symbols, timeout_seconds=args.timeout)

    selected_sources = _selected_sources(registry)
    report_rows: list[dict[str, Any]] = []

    for display_name, category in PROBE_SOURCES:
        source = selected_sources.get(category)
        if source is None:
            report_rows.append(
                {
                    "source": display_name,
                    "category": category,
                    "source_id": None,
                    "endpoint": "not configured",
                    "response_status": "not configured",
                    "sample_payload": None,
                    "csv_generation": {"ok": False, "message": "source is not configured"},
                    "fetch_status": "not_configured",
                    "result": "FAIL",
                }
            )
            continue

        source_config = getattr(source, "config", {})
        endpoints = _endpoint_urls(source_config, context, main7_symbols)
        endpoint_probes = [_probe_endpoint(url, args.timeout, context.user_agent) for url in endpoints]
        source_result = source.fetch(context)
        csv_result = _write_single_source_csv(source_result, csv_root / str(category), as_of)
        all_endpoints_ok = bool(endpoint_probes) and all(item.ok for item in endpoint_probes)
        passed = all_endpoints_ok and source_result.success and csv_result["ok"]
        report_rows.append(
            {
                "source": display_name,
                "category": category,
                "source_id": source.source_id,
                "endpoint": _summarize_endpoints(endpoints),
                "endpoints": endpoints,
                "response_status": _summarize_status(endpoint_probes),
                "endpoint_probe_count": len(endpoint_probes),
                "sample_payload": _first_sample(endpoint_probes),
                "csv_generation": csv_result,
                "fetch_status": source_result.status,
                "normalized_fields": dict(source_result.canonical_fields),
                "issues": [issue.as_dict() for issue in source_result.issues],
                "result": "PASS" if passed else "FAIL",
            }
        )

    summary = {
        "as_of": as_of.isoformat(),
        "retrieved_at": context.retrieved_at.isoformat(),
        "runtime": "GitHub Actions / Python urllib; no Codex Cloud fetchers",
        "overall_result": "PASS" if all(row["result"] == "PASS" for row in report_rows) else "FAIL",
        "sources": report_rows,
    }
    (output_dir / "probe_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = _render_markdown(summary, sample_chars=args.sample_chars)
    (output_dir / "probe_report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if summary["overall_result"] == "PASS" else 1


def _selected_sources(registry: PublicDataFetcherRegistry) -> dict[str, Any]:
    by_category: dict[str, list[Any]] = {}
    for source in registry.sources:
        by_category.setdefault(source.provider_category, []).append(source)
    return {category: sorted(sources, key=_fallback_order)[0] for category, sources in by_category.items() if sources}


def _fallback_order(source: Any) -> int:
    config = getattr(source, "config", {})
    if isinstance(config, Mapping):
        try:
            return int(config.get("fallback_order", config.get("priority", 10_000)))
        except (TypeError, ValueError):
            return 10_000
    return 10_000


def _endpoint_urls(config: Mapping[str, Any], context: PublicDataFetchContext, main7_symbols: Sequence[str]) -> list[str]:
    if "symbol_endpoint_url_template" in config:
        months = int(config.get("lookback_months", 4) or 4)
        urls: list[str] = []
        for symbol in main7_symbols:
            current = date(context.as_of.year, context.as_of.month, 1)
            for _ in range(months):
                urls.append(_render_template(str(config["symbol_endpoint_url_template"]), current, symbol=symbol))
                current = _previous_month(current)
        return list(dict.fromkeys(urls))

    templates = config.get("endpoint_url_templates") or config.get("urls")
    if isinstance(templates, list) and templates:
        return [_render_template(str(template), context.as_of) for template in templates]

    template = str(config.get("endpoint_url_template") or config.get("url") or "")
    if not template:
        return []
    months = int(config.get("lookback_months", 1) or 1)
    if months <= 1:
        return [_render_template(template, context.as_of)]
    urls = []
    current = date(context.as_of.year, context.as_of.month, 1)
    for _ in range(months):
        urls.append(_render_template(template, current))
        current = _previous_month(current)
    return list(reversed(list(dict.fromkeys(urls))))


def _render_template(template: str, value: date, *, symbol: str | None = None) -> str:
    values = {
        "as_of": value.isoformat(),
        "yyyymmdd": value.strftime("%Y%m%d"),
        "yyyymm": value.strftime("%Y%m"),
        "yyyy": value.strftime("%Y"),
        "mm": value.strftime("%m"),
        "dd": value.strftime("%d"),
        "symbol": symbol or "",
        "stock_no": symbol or "",
    }
    return template.format(**values)


def _previous_month(value: date) -> date:
    return date(value.year - (1 if value.month == 1 else 0), 12 if value.month == 1 else value.month - 1, 1)


def _probe_endpoint(url: str, timeout: float, user_agent: str) -> EndpointProbe:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured public endpoints only.
            body = response.read().decode("utf-8-sig", errors="replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        return EndpointProbe(url=url, status=exc.code, ok=False, error=f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001
        return EndpointProbe(url=url, status=None, ok=False, error=f"{exc.__class__.__name__}: {exc}")
    return EndpointProbe(url=url, status=status, ok=200 <= status < 300, sample_payload=_sample_payload(body))


def _sample_payload(body: str) -> Any:
    stripped = body.lstrip()
    if not stripped:
        return ""
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(body)
            return _compact_payload(payload)
        except json.JSONDecodeError:
            pass
    return stripped[:1000]


def _compact_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return {"type": "list", "length": len(payload), "first_item": _compact_payload(payload[0]) if payload else None}
    if isinstance(payload, dict):
        compact: dict[str, Any] = {"keys": list(payload.keys())[:12]}
        for key in ("stat", "date", "title", "fields", "data"):
            if key in payload:
                value = payload[key]
                if key == "data" and isinstance(value, list):
                    compact[key] = {"length": len(value), "first_row": value[0] if value else None}
                else:
                    compact[key] = value if not isinstance(value, (dict, list)) else _compact_payload(value)
        return compact
    return payload


def _first_sample(probes: Sequence[EndpointProbe]) -> Any:
    for probe in probes:
        if probe.sample_payload is not None:
            return probe.sample_payload
    return None


def _summarize_endpoints(urls: Sequence[str]) -> str:
    if not urls:
        return "none"
    if len(urls) == 1:
        return urls[0]
    return f"{urls[0]} (+{len(urls) - 1} more)"


def _summarize_status(probes: Sequence[EndpointProbe]) -> str:
    if not probes:
        return "not attempted"
    ok_count = sum(1 for probe in probes if probe.ok)
    statuses = ", ".join(sorted({str(probe.status) if probe.status is not None else "ERROR" for probe in probes}))
    if ok_count == len(probes):
        return f"{statuses} ({ok_count}/{len(probes)} OK)"
    errors = "; ".join(f"{probe.status or 'ERROR'} {probe.error or ''}".strip() for probe in probes if not probe.ok)
    return f"{statuses} ({ok_count}/{len(probes)} OK; {errors})"


def _write_single_source_csv(result: Any, output_dir: Path, as_of: date) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_result = write_provider_csvs([result], output_dir, as_of)
    path = write_result.provider_csv_paths.get(result.provider_category)
    csv_path = Path(path) if path else None
    ok = bool(path and csv_path and csv_path.exists() and csv_path.stat().st_size > 0)
    return {
        "ok": ok,
        "path": str(csv_path) if csv_path else None,
        "data_status": write_result.data_status,
        "message": "CSV generated" if ok else "CSV not generated",
        "issues": [issue.as_dict() for issue in write_result.issues],
    }


def _render_markdown(summary: Mapping[str, Any], *, sample_chars: int) -> str:
    lines = [
        "# GitHub Actions Market Data Probe",
        "",
        f"- As of: `{summary['as_of']}`",
        f"- Retrieved at: `{summary['retrieved_at']}`",
        f"- Runtime: {summary['runtime']}",
        f"- Overall: **{summary['overall_result']}**",
        "",
        "| Source | Endpoint | Response status | CSV generation | Result |",
        "|---|---|---:|---|---:|",
    ]
    for row in summary["sources"]:
        csv_status = "PASS" if row["csv_generation"].get("ok") else "FAIL"
        lines.append(f"| {row['source']} | `{row['endpoint']}` | `{row['response_status']}` | {csv_status}: `{row['csv_generation'].get('path')}` | **{row['result']}** |")
    lines.extend(["", "## Source evidence", ""])
    for row in summary["sources"]:
        lines.extend(
            [
                f"### {row['source']}: {row['result']}",
                f"- Source ID: `{row.get('source_id')}`",
                f"- Fetch status: `{row.get('fetch_status')}`",
                f"- Endpoint count: `{row.get('endpoint_probe_count', 0)}`",
                f"- Response status: `{row.get('response_status')}`",
                f"- CSV generation result: `{'PASS' if row['csv_generation'].get('ok') else 'FAIL'}` ({row['csv_generation'].get('message')})",
                "- Sample payload:",
                "```json",
                _truncate(json.dumps(row.get("sample_payload"), ensure_ascii=False, indent=2, sort_keys=True), sample_chars),
                "```",
                "",
            ]
        )
        if row.get("issues"):
            lines.extend(["- Issues:", "```json", _truncate(json.dumps(row["issues"], ensure_ascii=False, indent=2, sort_keys=True), sample_chars), "```", ""])
    return "\n".join(lines) + "\n"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 30)] + "\n... truncated ..."


if __name__ == "__main__":
    raise SystemExit(main())
