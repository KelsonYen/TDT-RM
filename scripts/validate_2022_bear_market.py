"""Validate generated V5.1.4 2022 bear-market backtest artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm import validate_2022_bear_market_backtest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="outputs/tdt_rm_v5_1_4_2022_bear_market_backtest.csv")
    parser.add_argument("--summary", default="outputs/tdt_rm_v5_1_4_2022_bear_market_summary.json")
    parser.add_argument("--output", default="outputs/tdt_rm_v5_1_4_2022_bear_market_validation.json")
    args = parser.parse_args()

    result = validate_2022_bear_market_backtest(args.csv, args.summary)
    payload = result.as_dict()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"validation": str(output), **payload}, indent=2, ensure_ascii=False))
    if not result.is_valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
