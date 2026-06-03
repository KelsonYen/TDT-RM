#!/usr/bin/env python
"""Render a GitHub Actions step summary for FinMind daily ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


LABELS = {
    "price.csv": "Price",
    "foreign_flow.csv": "Foreign Flow",
    "fx.csv": "FX",
    "breadth.csv": "Breadth",
    "futures.csv": "Futures",
    "options.csv": "Options",
    "leadership.csv": "Leadership",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render FinMind ingestion GitHub summary Markdown.")
    parser.add_argument("--fetch-summary", default="outputs/finmind_fetch_summary.json")
    parser.add_argument("--fetch-log", default="outputs/finmind_fetch.log")
    args = parser.parse_args()

    fetch_path = Path(args.fetch_summary)
    log_path = Path(args.fetch_log)
    fetch = json.loads(fetch_path.read_text(encoding="utf-8")) if fetch_path.exists() else {}
    trade_date = str(fetch.get("trade_date") or "")
    reports_dir = Path(str(fetch.get("reports_dir") or f"reports/daily/{trade_date}"))
    pipeline_path = reports_dir / "artifacts" / "pipeline_summary.json"
    pipeline = json.loads(pipeline_path.read_text(encoding="utf-8")) if pipeline_path.exists() else {}
    print(render_summary(fetch, pipeline, log_path))
    return 0


def render_summary(fetch: Mapping[str, Any], pipeline: Mapping[str, Any], log_path: Path) -> str:
    trade_date = str(fetch.get("trade_date") or "")
    scores = _mapping(pipeline.get("scores"))
    missing = list(fetch.get("missing_datasets") or [])
    ready = bool(fetch) and not missing and bool(pipeline)
    lines = ["## FINMIND DATA FETCH RESULT", ""]
    datasets = _mapping(fetch.get("datasets"))
    for filename, label in LABELS.items():
        status = _mapping(datasets.get(filename))
        lines.append(f"- {label}: {'PASS' if status.get('ok') else 'FAIL'}")
    lines.append("")
    if ready:
        lines.append("**AUTOMATED DATA INGESTION READY**")
    else:
        lines.append("**AUTOMATED DATA INGESTION NOT READY**")
        if missing:
            lines.append("- Missing datasets: " + ", ".join(str(item) for item in missing))
        elif not pipeline:
            lines.append("- Missing datasets: production_summary")
    lines.extend([
        "",
        "## TODAY'S TDT-RM MARKET RESULT",
        "",
        f"Trade Date: {trade_date}",
        f"Signal: {_value(pipeline, 'signal')}",
        f"Regime State: {_value(pipeline, 'regime_state', 'market_regime', default='watch')}",
        f"TCWRS: {scores.get('TCWRS', '')}",
        f"MHS: {scores.get('MHS', '')}",
        f"ETI-5: {scores.get('ETI-5', '')}",
        f"Tail Risk: {scores.get('Tail Risk', '')}",
        f"BCD: {scores.get('BCD', '')}",
        f"Crash Probability: {scores.get('CP', '')}",
        f"Exposure Limit: {_value(pipeline, 'exposure_limit')}",
        f"Recommended Action: {_recommended_action(pipeline)}",
        "",
        "### Fetch log",
        "```text",
    ])
    if log_path.exists():
        lines.append(log_path.read_text(encoding="utf-8")[-6000:])
    lines.append("```")
    return "\n".join(lines)


def _recommended_action(pipeline: Mapping[str, Any]) -> str:
    signal = str(_value(pipeline, "signal")).lower()
    exposure = _value(pipeline, "exposure_limit")
    if "exit" in signal:
        return "Exit / remain defensive."
    if exposure:
        return f"Follow model exposure limit: {exposure}."
    return "No normal production recommendation; ingestion is not ready."


def _value(mapping: Mapping[str, Any], *keys: str, default: str = "") -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
