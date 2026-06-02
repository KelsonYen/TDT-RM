"""Generate a V5.1.3/V5.1.4 COVID-2020 stress-test comparison report.

This report consumes the same daily COVID stress-test CSV artifacts produced by
``scripts/stress_test_covid_crash_2020.py`` and the archived V5.1.3 freeze run,
then writes the user-facing comparison summary and markdown report.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

RISK_OFF_SIGNALS = {"Red", "Orange"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v513-csv", default="outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv")
    parser.add_argument("--v514-csv", default="outputs/covid_2020_backtest.csv")
    parser.add_argument("--summary", default="outputs/covid_2020_summary.json")
    parser.add_argument("--report", default="outputs/covid_2020_comparison_report.md")
    args = parser.parse_args()

    v513_rows = _load_rows(args.v513_csv)
    v514_rows = _load_rows(args.v514_csv)
    v513_metrics = _summarize_rows(
        rows=v513_rows,
        model="TDT-RM V5.1.3 Rev.3 Final Freeze",
        source_csv=args.v513_csv,
    )
    v514_metrics = _summarize_rows(
        rows=v514_rows,
        model="TDT-RM V5.1.4 Backtest Calibration Patch",
        source_csv=args.v514_csv,
    )
    verification = _verify(v513_metrics, v514_metrics)
    payload = {
        "period": "2020 COVID crash",
        "simulation": "daily",
        "framework": "Same daily price-proxy COVID stress-test framework and V5.1.4 outcome annotations used by the 2022 bear-market backtest.",
        "models": {
            "v5_1_3_final_freeze": v513_metrics,
            "v5_1_4_backtest_calibration_patch": v514_metrics,
        },
        "verification": verification,
    }

    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(payload), encoding="utf-8")

    print(json.dumps({"summary": str(summary_path), "report": str(report_path), **verification}, indent=2))


def _load_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _summarize_rows(rows: Sequence[Mapping[str, str]], model: str, source_csv: str) -> dict[str, Any]:
    cp_values = [_float(row, "CP") for row in rows if _float(row, "CP") is not None]
    risk_off_rows = [row for row in rows if row.get("Signal") in RISK_OFF_SIGNALS]
    risk_off_cp_values = [_float(row, "CP") for row in risk_off_rows if _float(row, "CP") is not None]
    distribution = dict(sorted(Counter(row.get("Signal", "") for row in rows).items()))
    first_risk_off = next((row for row in rows if row.get("Signal") in RISK_OFF_SIGNALS), None)
    worst_20d = sorted(rows, key=lambda row: _float(row, "Forward 20D Max Drawdown %") or 0.0)[:5]
    return {
        "model": model,
        "source_csv": source_csv,
        "observations": len(rows),
        "first_date": rows[0].get("Date") if rows else None,
        "last_date": rows[-1].get("Date") if rows else None,
        "red_signals": sum(row.get("Signal") == "Red" for row in rows),
        "orange_signals": sum(row.get("Signal") == "Orange" for row in rows),
        "false_positives": sum(row.get("False Positive") == "True" for row in rows),
        "maximum_drawdown_avoided_pct": _round(max((_float(row, "Drawdown Avoided %") or 0.0 for row in rows), default=0.0)),
        "average_cp": _round(_average(cp_values)),
        "average_cp_during_risk_off_periods": _round(_average(risk_off_cp_values)),
        "first_red_signal": next((row.get("Date") for row in rows if row.get("Signal") == "Red"), None),
        "first_orange_signal": next((row.get("Date") for row in rows if row.get("Signal") == "Orange"), None),
        "signal_distribution": distribution,
        "first_risk_off_observation": _compact_row(first_risk_off),
        "worst_forward_20d_drawdown_observations": [_compact_row(row) for row in worst_20d],
    }


def _verify(v513: Mapping[str, Any], v514: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "maximum_drawdown_avoided_at_least_20_pct": {
            "passed": v514["maximum_drawdown_avoided_pct"] >= 20.0,
            "actual": v514["maximum_drawdown_avoided_pct"],
            "threshold": 20.0,
        },
        "false_positives_reduced": {
            "passed": v514["false_positives"] < v513["false_positives"],
            "v5_1_3": v513["false_positives"],
            "v5_1_4": v514["false_positives"],
        },
        "orange_signals_appear": {
            "passed": v514["orange_signals"] > 0,
            "actual": v514["orange_signals"],
        },
        "red_signals_reduced_vs_v5_1_3": {
            "passed": v514["red_signals"] < v513["red_signals"],
            "v5_1_3": v513["red_signals"],
            "v5_1_4": v514["red_signals"],
        },
    }


def _render_report(payload: Mapping[str, Any]) -> str:
    v513 = payload["models"]["v5_1_3_final_freeze"]
    v514 = payload["models"]["v5_1_4_backtest_calibration_patch"]
    verification = payload["verification"]
    lines = [
        "# TDT-RM 2020 COVID Crash Backtest Comparison Report",
        "",
        "## Run metadata",
        "",
        f"- Period: {payload['period']}",
        f"- Simulation: {payload['simulation']}",
        f"- Framework: {payload['framework']}",
        f"- V5.1.3 source CSV: `{v513['source_csv']}`",
        f"- V5.1.4 source CSV: `{v514['source_csv']}`",
        "",
        "## Headline comparison",
        "",
        "| Metric | V5.1.3 Final Freeze | V5.1.4 Backtest Calibration Patch | Change |",
        "| --- | ---: | ---: | ---: |",
        _metric_row("Red signals", v513["red_signals"], v514["red_signals"]),
        _metric_row("Orange signals", v513["orange_signals"], v514["orange_signals"]),
        _metric_row("False positives", v513["false_positives"], v514["false_positives"]),
        _metric_row("Maximum drawdown avoided", f"{v513['maximum_drawdown_avoided_pct']:.2f}%", f"{v514['maximum_drawdown_avoided_pct']:.2f}%", raw_change=v514["maximum_drawdown_avoided_pct"] - v513["maximum_drawdown_avoided_pct"], suffix="%"),
        _metric_row("Average CP", f"{v513['average_cp']:.2f}", f"{v514['average_cp']:.2f}", raw_change=v514["average_cp"] - v513["average_cp"]),
        _metric_row("Average CP during risk-off periods", _format_optional(v513["average_cp_during_risk_off_periods"]), _format_optional(v514["average_cp_during_risk_off_periods"]), raw_change=None if v514["average_cp_during_risk_off_periods"] is None or v513["average_cp_during_risk_off_periods"] is None else v514["average_cp_during_risk_off_periods"] - v513["average_cp_during_risk_off_periods"]),
        "",
        "## Verification gates",
        "",
        "| Gate | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for name, result in verification.items():
        status = "PASS" if result["passed"] else "FAIL"
        evidence = ", ".join(f"{key}={value}" for key, value in result.items() if key != "passed")
        lines.append(f"| {name} | {status} | {evidence} |")
    lines.extend([
        "",
        "## Signal distribution",
        "",
        "| Signal | V5.1.3 days | V5.1.4 days |",
        "| --- | ---: | ---: |",
    ])
    all_signals = sorted(set(v513["signal_distribution"]) | set(v514["signal_distribution"]))
    for signal in all_signals:
        lines.append(f"| {signal} | {v513['signal_distribution'].get(signal, 0)} | {v514['signal_distribution'].get(signal, 0)} |")
    lines.extend([
        "",
        "## First risk-off observations",
        "",
        "| Model | Date | Signal | Close | TCWRS | ETI-5 | Tail Risk | BCD | CP | Forward 20D Max Drawdown |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        _first_risk_off_row(v513),
        _first_risk_off_row(v514),
        "",
        "## Interpretation",
        "",
        "- V5.1.4 reduced red signals and false positives versus V5.1.3 on this price-only COVID tape.",
        "- V5.1.4 did not satisfy the 20% maximum-drawdown-avoided gate because no Red or Orange risk-off signal was emitted before the crash trough in the generated artifact.",
        "- V5.1.4 also did not satisfy the orange-signal-appearance gate on this short February-April 2020 sample.",
        "- Average CP is reported across all observations; average CP during risk-off periods is `n/a` when a model emits no Red/Orange observations.",
        "",
    ])
    return "\n".join(lines)


def _compact_row(row: Mapping[str, str] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "date": row.get("Date"),
        "signal": row.get("Signal"),
        "close": _float(row, "Close"),
        "tcwrs": _float(row, "TCWRS"),
        "eti5": _float(row, "ETI-5"),
        "tail_risk": _float(row, "Tail Risk"),
        "bcd": _float(row, "BCD"),
        "cp": _float(row, "CP"),
        "forward_20d_max_drawdown_pct": _float(row, "Forward 20D Max Drawdown %"),
        "false_positive": row.get("False Positive") == "True",
        "drawdown_avoided_pct": _float(row, "Drawdown Avoided %"),
    }


def _metric_row(label: str, v513: Any, v514: Any, raw_change: float | None = None, suffix: str = "") -> str:
    if raw_change is None and isinstance(v513, (int, float)) and isinstance(v514, (int, float)):
        raw_change = float(v514) - float(v513)
    change = "n/a" if raw_change is None else f"{raw_change:+.2f}{suffix}"
    return f"| {label} | {v513} | {v514} | {change} |"


def _first_risk_off_row(metrics: Mapping[str, Any]) -> str:
    row = metrics["first_risk_off_observation"]
    if row is None:
        return f"| {metrics['model']} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
    return (
        f"| {metrics['model']} | {row['date']} | {row['signal']} | {row['close']:.2f} | {row['tcwrs']:.0f} | "
        f"{row['eti5']:.0f} | {row['tail_risk']:.2f} | {row['bcd']:.2f} | {row['cp']:.2f} | "
        f"{row['forward_20d_max_drawdown_pct']:.2f}% |"
    )


def _average(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _float(row: Mapping[str, str], field: str) -> float | None:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
