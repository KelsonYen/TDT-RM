from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from tdt_rm.daily_providers import DailyProviderContext, DailySnapshotAssembler, LocalCsvProvider
from tdt_rm.daily_runner import _bcd_result_from_snapshot
from tdt_rm.daily_snapshot import DailyMarketSnapshot
from tdt_rm.data_providers.normalizers import BCD_RECOVERY_EXTRA_COLUMNS, normalize_public_row, write_strict_csv
from tdt_rm.public_data_fetchers import PublicDataFetchResult, write_provider_csvs


BCD_EXTRAS = tuple(BCD_RECOVERY_EXTRA_COLUMNS)


def _read_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _complete_breadth_row() -> dict[str, object]:
    return {
        "date": "2026-06-05",
        "advancing_issues": 420,
        "declining_issues": 880,
        "index_down": False,
        "declining_issues_significantly_expand": True,
        "declining_issues_significantly_gt_advancing": True,
        "declining_gt_advancing_consecutive_days": 2,
        "breadth_weakens_for_2_days": True,
        "breadth_history": [
            {"trade_date": "2026-06-03", "advancing_issues": 700, "declining_issues": 500, "taiex_return_pct": 0.3},
            {"trade_date": "2026-06-04", "advancing_issues": 500, "declining_issues": 760, "taiex_return_pct": -0.2},
        ],
        "main7_returns": {"2330": 1.2, "2317": 0.7},
        "main7_weights": {"2330": 0.32, "2317": 0.05},
        "main7_concentration": 0.37,
        "sector_returns": {"Tech": -0.3, "Finance": 0.1},
        "sector_above_ma20": {"Tech": False, "Finance": True},
        "sector_breadth": {"above": 1, "total": 2},
        "sector_diffusion": 0.5,
        "otc_return_pct": -1.1,
        "small_mid_breadth": {"advancing_issues": 180, "declining_issues": 620, "taiex_return_pct": -1.3},
        "small_mid_weakness": 0.7,
        "turnover_concentration_topn": 0.46,
        "turnover_concentration": 0.46,
    }


def test_provider_and_strict_csv_headers_preserve_bcd_recovery_extras(tmp_path: Path) -> None:
    row = _complete_breadth_row()
    result = PublicDataFetchResult("fixture", "Fixture", "breadth", "success", rows=(row,))

    written = write_provider_csvs([result], tmp_path / "provider", date(2026, 6, 5))
    provider_path = Path(written.provider_csv_paths["breadth"])
    provider_header = _read_header(provider_path)

    for field in BCD_EXTRAS:
        assert field in provider_header
    provider_row = next(csv.DictReader(provider_path.open(encoding="utf-8")))
    assert json.loads(provider_row["breadth_history"])[0]["advancing_issues"] == 700
    assert json.loads(provider_row["main7_returns"]) == {"2317": 0.7, "2330": 1.2}

    strict_row = normalize_public_row("breadth", row, trade_date=date(2026, 6, 5), provider_source="fixture")
    strict_path = tmp_path / "strict" / "breadth.csv"
    write_strict_csv(strict_path, "breadth", strict_row)
    strict_header = _read_header(strict_path)

    for field in BCD_EXTRAS:
        assert field in strict_header
    strict_csv_row = next(csv.DictReader(strict_path.open(encoding="utf-8")))
    assert json.loads(strict_csv_row["small_mid_breadth"])["declining_issues"] == 620



def test_strict_csv_keeps_optional_bcd_extra_headers_when_values_are_missing(tmp_path: Path) -> None:
    minimal = {
        "advancing_issues": 420,
        "declining_issues": 880,
        "index_down": False,
        "declining_issues_significantly_expand": True,
        "declining_issues_significantly_gt_advancing": True,
        "declining_gt_advancing_consecutive_days": 2,
        "breadth_weakens_for_2_days": True,
    }
    row = normalize_public_row("breadth", minimal, trade_date=date(2026, 6, 5), provider_source="fixture")
    strict_path = tmp_path / "strict_missing_extras" / "breadth.csv"

    write_strict_csv(strict_path, "breadth", row)

    header = _read_header(strict_path)
    csv_row = next(csv.DictReader(strict_path.open(encoding="utf-8")))
    for field in BCD_EXTRAS:
        assert field in header
        assert csv_row[field] == ""

def test_local_csv_snapshot_and_bcd_input_round_trip_bcd_recovery_extras(tmp_path: Path) -> None:
    row = normalize_public_row("breadth", _complete_breadth_row(), trade_date=date(2026, 6, 5), provider_source="fixture")
    csv_path = tmp_path / "breadth.csv"
    write_strict_csv(csv_path, "breadth", row)

    provider_result = LocalCsvProvider("breadth_csv", "Breadth CSV", csv_path, "breadth").fetch_or_load(
        DailyProviderContext(as_of=date(2026, 6, 5))
    )
    canonical = provider_result.canonical_fields
    assert canonical["breadth_history"][0]["advancing_issues"] == 700
    assert canonical["main7_returns"] == {"2317": 0.7, "2330": 1.2}
    assert canonical["otc_return_pct"] == -1.1
    assert canonical["turnover_concentration"] == 0.46
    assert provider_result.field_sources["breadth_history"] == "breadth_csv"

    assembled = DailySnapshotAssembler([LocalCsvProvider("breadth_csv", "Breadth CSV", csv_path, "breadth")]).assemble(
        DailyProviderContext(as_of=date(2026, 6, 5))
    )
    snapshot_row = assembled.snapshot.canonical_row
    for field in ("breadth_history", "main7_returns", "main7_weights", "sector_returns", "sector_above_ma20", "otc_return_pct", "small_mid_breadth", "turnover_concentration"):
        assert field in snapshot_row

    bcd = _bcd_result_from_snapshot(assembled.snapshot, taiex_return_pct=0.8)
    raw = bcd.raw_inputs
    assert raw["breadth_history"][0]["advancing_issues"] == 700
    assert raw["main7_returns"] == {"2317": 0.7, "2330": 1.2}
    assert raw["main7_weights"] == {"2317": 0.05, "2330": 0.32}
    assert raw["sector_returns"] == {"Finance": 0.1, "Tech": -0.3}
    assert raw["sector_above_ma20"] == {"Finance": True, "Tech": False}
    assert raw["otc_return_pct"] == -1.1
    assert raw["small_mid_breadth"]["advancing_issues"] == 180
    assert raw["turnover_concentration_topn"] == 0.46
    assert "main7_returns" not in bcd.missing_components
    assert bcd.final_score is not None
    assert bcd.data_quality_status == "COMPLETE"


def test_bcd_is_incomplete_when_recovery_extras_are_absent() -> None:
    snapshot = DailyMarketSnapshot(
        trade_date=date(2026, 6, 5),
        observed_at=date(2026, 6, 5),
        canonical_row={"observed_at": "2026-06-05", "advancing_issues": 420, "declining_issues": 880},
        field_sources={"advancing_issues": "breadth_csv", "declining_issues": "breadth_csv"},
    )

    bcd = _bcd_result_from_snapshot(snapshot, taiex_return_pct=0.8)

    assert bcd.final_score is None
    assert bcd.data_quality_status == "INCOMPLETE"
    assert {"breadth_history", "main7_returns", "main7_weights", "sector_diffusion", "otc_return_pct", "small_mid_breadth", "turnover_concentration_topn"} <= set(bcd.missing_components)
