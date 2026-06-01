"""Generate a Buy-and-Hold versus TDT-RM Signals performance report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm import generate_performance_report, load_performance_observations_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="outputs/tdt_rm_v5_1_3_2022_bear_market_backtest.csv",
        help="Backtest CSV with Date, Close, and Signal columns.",
    )
    parser.add_argument(
        "--markdown-output",
        default="outputs/tdt_rm_v5_1_3_2022_performance_report.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--json-output",
        default="outputs/tdt_rm_v5_1_3_2022_performance_report.json",
        help="JSON report output path.",
    )
    parser.add_argument(
        "--risk-off-signal",
        action="append",
        dest="risk_off_signals",
        help="Signal to treat as risk-off. Repeat to specify multiple values. Defaults to Red and Orange.",
    )
    args = parser.parse_args()

    observations = load_performance_observations_csv(args.input)
    report = generate_performance_report(
        observations,
        risk_off_signals=args.risk_off_signals or ("Red", "Orange"),
    )

    markdown_output = Path(args.markdown_output)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(report.to_markdown(), encoding="utf-8")

    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")

    print(report.to_markdown())
    print(json.dumps({"markdown": str(markdown_output), "json": str(json_output)}, indent=2))


if __name__ == "__main__":
    main()
