import csv
import json
from pathlib import Path

from tdt_rm.daily_pipeline import run_daily_pipeline


def copy_inputs(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True)
    for name in ("price.csv", "foreign_flow.csv", "fx.csv", "breadth.csv", "futures.csv", "options.csv", "leadership.csv", "margin.csv"):
        (dst / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")


def test_daily_pipeline_writes_bcd_audit_artifacts(tmp_path):
    inputs = tmp_path / "inputs"
    copy_inputs(Path("inputs/daily/2026-06-05"), inputs)
    out = tmp_path / "artifacts"
    result = run_daily_pipeline(as_of=__import__("datetime").date(2026, 6, 5), output_dir=out, price_csv=inputs / "price.csv", foreign_csv=inputs / "foreign_flow.csv", fx_csv=inputs / "fx.csv", breadth_csv=inputs / "breadth.csv", futures_csv=inputs / "futures.csv", options_csv=inputs / "options.csv", leadership_csv=inputs / "leadership.csv", margin_csv=inputs / "margin.csv")
    json_path = out / "bcd_audit_trace.json"
    csv_path = out / "bcd_audit_trace.csv"
    assert json_path.exists()
    assert csv_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["final_score"] == result["scores"]["BCD"]
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert {"trade_date", "component", "raw_value", "threshold", "threshold_hit", "score", "source_field", "missing_reason"} <= set(rows[0])
