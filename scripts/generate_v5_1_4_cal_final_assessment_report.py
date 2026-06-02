"""Generate the V5.1.4+CAL final assessment report.

The report is intentionally artifact-driven: it inspects the outputs directory
for V5.1.3, V5.1.4, and V5.1.4+CAL CSV/JSON artifacts and summarizes whatever
is present.  Missing expected CAL artifacts are listed by file name so the
report never collapses a partial inventory into an inaccurate "no CAL outputs"
statement.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MODEL_ORDER = {
    "V5.1.3": 0,
    "V5.1.4": 1,
    "V5.1.4+CAL": 2,
}
SCENARIO_ORDER = {
    "2020 COVID": 0,
    "2022 Bear Market": 1,
    "2024 AI/semiconductor selloff": 2,
    "2026 overheating regime": 3,
    "Unclassified": 99,
}
EXPECTED_CAL_FILENAMES = (
    "tdt_rm_v5_1_4_cal_2020_covid_crash_stress.csv",
    "tdt_rm_v5_1_4_cal_2020_covid_crash_summary.json",
    "tdt_rm_v5_1_4_cal_2022_bear_market_backtest.csv",
    "tdt_rm_v5_1_4_cal_2022_bear_market_summary.json",
    "tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv",
    "tdt_rm_v5_1_4_cal_2024_ai_selloff_summary.json",
    "tdt_rm_v5_1_4_cal_2026_overheating_stress.csv",
    "tdt_rm_v5_1_4_cal_2026_overheating_summary.json",
)


@dataclass(frozen=True)
class Artifact:
    path: Path
    model: str
    scenario: str
    artifact_type: str


@dataclass(frozen=True)
class AssessmentRow:
    artifact: Artifact
    observations: int
    first_date: str | None
    last_date: str | None
    red_signals: int
    orange_signals: int
    false_positives: int
    max_drawdown_avoided_pct: float | None
    average_cp: float | None
    signal_distribution: Mapping[str, int]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--report", default="outputs/v5_1_4_cal_final_assessment_report.md")
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(outputs_dir=outputs_dir, report_path=report_path)
    report_path.write_text(report, encoding="utf-8")
    print(str(report_path))


def build_report(outputs_dir: str | Path = "outputs", report_path: str | Path | None = None) -> str:
    outputs_path = Path(outputs_dir)
    artifacts = discover_artifacts(outputs_path)
    rows = summarize_artifacts(artifacts)
    pattern_matches = discover_requested_pattern_matches(outputs_path)
    missing_expected = missing_expected_cal_artifacts(outputs_path)
    return render_report(
        rows=rows,
        artifacts=artifacts,
        pattern_matches=pattern_matches,
        missing_expected_cal=missing_expected,
        report_path=Path(report_path) if report_path is not None else None,
    )


def discover_requested_pattern_matches(outputs_dir: Path) -> dict[str, list[Path]]:
    """Return files matching the user's requested CAL/year discovery patterns.

    The previous failure mode was checking overly literal names such as
    ``*cal.csv``.  Generated CAL files commonly include the scenario between
    ``cal`` and the extension (for example
    ``tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv``), so discovery must match
    CAL/year tokens anywhere in the file name.
    """

    files = [path for path in outputs_dir.iterdir() if path.is_file()] if outputs_dir.exists() else []
    return {
        "cal.csv": sorted(path for path in files if "cal" in path.name.lower() and path.suffix == ".csv"),
        "cal.json": sorted(path for path in files if "cal" in path.name.lower() and path.suffix == ".json"),
        "2024.csv": sorted(path for path in files if "2024" in path.name and path.suffix == ".csv"),
        "2026.csv": sorted(path for path in files if "2026" in path.name and path.suffix == ".csv"),
    }


def discover_artifacts(outputs_dir: Path) -> list[Artifact]:
    artifacts: list[Artifact] = []
    if not outputs_dir.exists():
        return artifacts
    for path in sorted(p for p in outputs_dir.iterdir() if p.is_file() and p.suffix in {".csv", ".json"}):
        model = classify_model(path)
        scenario = classify_scenario(path)
        if model is None or scenario == "Unclassified":
            continue
        artifacts.append(Artifact(path=path, model=model, scenario=scenario, artifact_type=path.suffix.removeprefix(".")))
    return sorted(artifacts, key=lambda artifact: (SCENARIO_ORDER[artifact.scenario], MODEL_ORDER[artifact.model], artifact.path.name))


def classify_model(path: Path) -> str | None:
    name = path.name.lower()
    if "v5_1_4_cal" in name or ("v5_1_4" in name and "cal" in name):
        return "V5.1.4+CAL"
    if "v5_1_3" in name:
        return "V5.1.3"
    if "v5_1_4" in name or name == "covid_2020_backtest.csv" or name == "covid_2020_summary.json":
        return "V5.1.4"
    return None


def classify_scenario(path: Path) -> str:
    name = path.name.lower()
    if "2020" in name or "covid" in name:
        return "2020 COVID"
    if "2022" in name or "bear" in name:
        return "2022 Bear Market"
    if "2024" in name or "ai_selloff" in name or "semiconductor" in name:
        return "2024 AI/semiconductor selloff"
    if "2026" in name or "overheating" in name:
        return "2026 overheating regime"
    return "Unclassified"


def missing_expected_cal_artifacts(outputs_dir: Path) -> list[str]:
    return [name for name in EXPECTED_CAL_FILENAMES if not (outputs_dir / name).exists()]


def summarize_artifacts(artifacts: Iterable[Artifact]) -> list[AssessmentRow]:
    rows: list[AssessmentRow] = []
    for artifact in artifacts:
        if artifact.artifact_type != "csv":
            continue
        csv_rows = load_csv_rows(artifact.path)
        rows.append(summarize_csv_artifact(artifact, csv_rows))
    return sorted(rows, key=lambda row: (SCENARIO_ORDER[row.artifact.scenario], MODEL_ORDER[row.artifact.model], row.artifact.path.name))


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize_csv_artifact(artifact: Artifact, rows: Sequence[Mapping[str, str]]) -> AssessmentRow:
    cp_values = [_float(row.get("CP")) for row in rows]
    cp_values = [value for value in cp_values if value is not None]
    avoided_values = [_float(row.get("Drawdown Avoided %")) for row in rows]
    avoided_values = [value for value in avoided_values if value is not None]
    return AssessmentRow(
        artifact=artifact,
        observations=len(rows),
        first_date=rows[0].get("Date") if rows else None,
        last_date=rows[-1].get("Date") if rows else None,
        red_signals=sum(row.get("Signal") == "Red" for row in rows),
        orange_signals=sum(row.get("Signal") == "Orange" for row in rows),
        false_positives=sum(_bool(row.get("False Positive")) for row in rows),
        max_drawdown_avoided_pct=max(avoided_values) if avoided_values else None,
        average_cp=sum(cp_values) / len(cp_values) if cp_values else None,
        signal_distribution=dict(sorted(Counter(row.get("Signal", "") for row in rows).items())),
    )


def render_report(
    *,
    rows: Sequence[AssessmentRow],
    artifacts: Sequence[Artifact],
    pattern_matches: Mapping[str, Sequence[Path]],
    missing_expected_cal: Sequence[str],
    report_path: Path | None = None,
) -> str:
    lines: list[str] = [
        "# V5.1.4+CAL Final Assessment Report",
        "",
        "## Report metadata",
        "",
        f"- Report path: `{report_path.as_posix() if report_path else 'n/a'}`",
        "- Artifact discovery: automatic scan of the outputs directory for V5.1.3, V5.1.4, and V5.1.4+CAL CSV/JSON artifacts.",
        "- CAL discovery rule: any output CSV/JSON with a `cal` token anywhere in the file name is considered a CAL artifact candidate.",
        "",
        "## Requested artifact pattern inventory",
        "",
        "| Pattern | Matching files |",
        "| --- | --- |",
    ]
    for pattern in ("cal.csv", "cal.json", "2024.csv", "2026.csv"):
        matches = pattern_matches.get(pattern, [])
        rendered = ", ".join(f"`{path.as_posix()}`" for path in matches) if matches else "None found"
        lines.append(f"| `{pattern}` | {rendered} |")

    lines.extend([
        "",
        "## Discovered assessment artifacts",
        "",
        "| Scenario | Model | Type | File |",
        "| --- | --- | --- | --- |",
    ])
    if artifacts:
        for artifact in artifacts:
            lines.append(f"| {artifact.scenario} | {artifact.model} | {artifact.artifact_type} | `{artifact.path.as_posix()}` |")
    else:
        lines.append("| n/a | n/a | n/a | No assessment artifacts discovered |")

    lines.extend([
        "",
        "## V5.1.4+CAL expected coverage",
        "",
        "| Scenario | Model | Expected CSV | Status |",
        "| --- | --- | --- | --- |",
    ])
    present_names = {artifact.path.name for artifact in artifacts}
    for filename, scenario in (
        ("tdt_rm_v5_1_4_cal_2020_covid_crash_stress.csv", "2020 COVID"),
        ("tdt_rm_v5_1_4_cal_2022_bear_market_backtest.csv", "2022 Bear Market"),
        ("tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv", "2024 AI/semiconductor selloff"),
        ("tdt_rm_v5_1_4_cal_2026_overheating_stress.csv", "2026 overheating regime"),
    ):
        status = "Found" if filename in present_names else "Missing"
        lines.append(f"| {scenario} | V5.1.4+CAL | `{filename}` | {status} |")

    lines.extend([
        "",
        "## Missing expected V5.1.4+CAL artifacts",
        "",
    ])
    if missing_expected_cal:
        lines.extend(f"- `{name}`" for name in missing_expected_cal)
    else:
        lines.append("- None. All expected V5.1.4+CAL artifact file names are present.")

    lines.extend([
        "",
        "## Assessment summary",
        "",
        "| Scenario | Model | Observations | Window | Red | Orange | False positives | Max drawdown avoided | Average CP | Source CSV |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    if rows:
        for row in rows:
            lines.append(_assessment_table_row(row))
    else:
        lines.append("| n/a | n/a | 0 | n/a | 0 | 0 | 0 | n/a | n/a | n/a |")

    lines.extend([
        "",
        "## Signal distributions",
        "",
        "| Scenario | Model | Signal distribution |",
        "| --- | --- | --- |",
    ])
    if rows:
        for row in rows:
            distribution = ", ".join(f"{signal}: {count}" for signal, count in row.signal_distribution.items()) or "n/a"
            lines.append(f"| {row.artifact.scenario} | {row.artifact.model} | {distribution} |")
    else:
        lines.append("| n/a | n/a | n/a |")

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- The report includes every discovered V5.1.3, V5.1.4, and V5.1.4+CAL CSV artifact instead of relying on hard-coded final-assessment file names.",
        "- If CAL artifacts are missing, the missing-file section lists exact expected names rather than using a blanket absence statement.",
        "- 2024 AI/semiconductor selloff and 2026 overheating regime rows appear automatically when matching CSV artifacts exist in outputs.",
        "",
    ])
    return "\n".join(lines)


def _assessment_table_row(row: AssessmentRow) -> str:
    window = _window(row.first_date, row.last_date)
    max_avoided = _format_float(row.max_drawdown_avoided_pct, suffix="%")
    avg_cp = _format_float(row.average_cp)
    return (
        f"| {row.artifact.scenario} | {row.artifact.model} | {row.observations} | {window} | "
        f"{row.red_signals} | {row.orange_signals} | {row.false_positives} | {max_avoided} | {avg_cp} | "
        f"`{row.artifact.path.as_posix()}` |"
    )


def _window(first_date: str | None, last_date: str | None) -> str:
    if first_date and last_date:
        return f"{first_date} to {last_date}"
    return "n/a"


def _format_float(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}{suffix}"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


if __name__ == "__main__":
    main()
