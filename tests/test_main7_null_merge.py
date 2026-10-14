from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.bcd_feature_builder import BCDFeatureBuilderContext, enrich_bcd_features
from tdt_rm.daily_providers import (
    DailyProviderContext,
    DailySnapshotAssembler,
    LocalCsvProvider,
    StaticMappingProvider,
)
from tdt_rm.daily_runner import _bcd_result_from_snapshot

DAY = date(2026, 6, 5)
LINEAGE = {
    "main7_closes": {"2330": 110, "2454": 190},
    "main7_previous_closes": {"2330": 100, "2454": 200},
    "main7_turnover_amounts": {"2330": 30, "2454": 70},
}


def _assemble(*providers):
    result = DailySnapshotAssembler(providers).assemble(DailyProviderContext(as_of=DAY))
    assert not result.provider_errors
    return result.snapshot


@pytest.mark.parametrize("blank", [None, "", "  ", "null", {}, [], "{}", "[]"])
@pytest.mark.parametrize("blank_kind,real_kind", [("auto", "auto"), ("manual", "auto"), ("auto", "manual")])
@pytest.mark.parametrize("blank_first", [True, False])
def test_only_non_missing_lineage_values_compete_by_precedence(blank, blank_kind, real_kind, blank_first):
    blank_provider = StaticMappingProvider(
        "blank", "空值來源", dict.fromkeys(LINEAGE, blank), source_kind=blank_kind,
    )
    real_provider = StaticMappingProvider("real", "實值來源", LINEAGE, source_kind=real_kind)
    providers = (blank_provider, real_provider) if blank_first else (real_provider, blank_provider)
    snapshot = _assemble(*providers)
    for field, value in LINEAGE.items():
        assert snapshot.canonical_row[field] == value
        assert snapshot.field_sources[field] == "real"


@pytest.mark.parametrize("first_kind,second_kind,winner", [("auto", "auto", "first"), ("manual", "auto", "first"), ("auto", "manual", "second")])
def test_real_lineage_conflicts_keep_original_precedence(first_kind, second_kind, winner):
    first = StaticMappingProvider("first", "第一來源", LINEAGE, source_kind=first_kind)
    other = {field: {"2330": 999} for field in LINEAGE}
    second = StaticMappingProvider("second", "第二來源", other, source_kind=second_kind)
    snapshot = _assemble(first, second)
    for field in LINEAGE:
        assert snapshot.canonical_row[field] == (LINEAGE if winner == "first" else other)[field]
        assert snapshot.field_sources[field] == winner


def test_all_blank_lineage_keeps_explicit_absence_and_bcd_incomplete(tmp_path):
    snapshot = _assemble(StaticMappingProvider("blank", "空值來源", dict.fromkeys(LINEAGE)))
    for field in LINEAGE:
        assert field in snapshot.canonical_row
        assert snapshot.canonical_row[field] is None
        assert snapshot.field_sources[field] == "blank"
    enriched = enrich_bcd_features(snapshot, BCDFeatureBuilderContext(DAY, historical_roots=(tmp_path,)))
    bcd = _bcd_result_from_snapshot(enriched.snapshot, taiex_return_pct=1.0)
    assert bcd.final_score is None
    assert bcd.data_quality_status == "INCOMPLETE"
    assert {"main7_returns", "main7_weights"} <= set(bcd.missing_components)


def _write_csv(path, row):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def test_csv_blank_before_leadership_reaches_snapshot_enrichment_and_bcd(tmp_path: Path):
    breadth = tmp_path / "breadth.csv"
    leadership = tmp_path / "leadership.csv"
    _write_csv(breadth, {"observed_at": DAY.isoformat(), "advancing_issues": 60, "declining_issues": 40, **dict.fromkeys(LINEAGE, "")})
    _write_csv(leadership, {"observed_at": DAY.isoformat(), "main_7_symbols": "2330,2454", **LINEAGE})
    snapshot = _assemble(
        LocalCsvProvider("breadth_csv", "市場廣度", breadth, "breadth"),
        LocalCsvProvider("leadership_csv", "主要權值股", leadership, "leadership"),
    )
    for field, value in LINEAGE.items():
        assert snapshot.canonical_row[field] == value
        assert snapshot.field_sources[field] == "leadership_csv"

    # Exercise snapshot-only recovery: no raw leadership artifact can mask loss.
    enriched = enrich_bcd_features(snapshot, BCDFeatureBuilderContext(DAY, historical_roots=(tmp_path,)))
    assert enriched.snapshot.canonical_row["main7_returns"] == {"2330": 10.0, "2454": -5.0}
    assert enriched.snapshot.canonical_row["main7_weights"] == {"2330": 0.3, "2454": 0.7}
    bcd = _bcd_result_from_snapshot(enriched.snapshot, taiex_return_pct=1.0)
    for field, value in LINEAGE.items():
        assert bcd.raw_inputs[field] == value
        assert bcd.source_fields[field] == "leadership_csv"
    assert "main7_returns" not in bcd.missing_components
    assert "main7_weights" not in bcd.missing_components
    # Other independent components are still missing; recovered Main7 is insufficient.
    assert bcd.final_score is None
    assert bcd.data_quality_status == "INCOMPLETE"


@pytest.mark.parametrize("supply_other_inputs", [False, True])
def test_production_pipeline_preserves_lineage_and_completeness(tmp_path, supply_other_inputs, monkeypatch):
    from tdt_rm.daily_pipeline import run_daily_pipeline

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = Path("inputs/daily/2026-06-05")
    for path in source.glob("*.csv"):
        (inputs / path.name).write_bytes(path.read_bytes())
    with (inputs / "breadth.csv").open(newline="", encoding="utf-8-sig") as handle:
        breadth = next(csv.DictReader(handle))
    breadth.update(dict.fromkeys(LINEAGE, ""))
    if supply_other_inputs:
        breadth.update({
            "breadth_history": [
                {"advancing_issues": 700, "declining_issues": 300},
                {"advancing_issues": 650, "declining_issues": 350},
            ],
            "sector_returns": {"tech": -0.2, "finance": 0.1},
            "sector_above_ma20": {"tech": False, "finance": True},
            "otc_return_pct": -0.4,
            "small_mid_breadth": {"advancing_issues": 250, "declining_issues": 750},
            "turnover_concentration_topn": 0.42,
        })
    _write_csv(inputs / "breadth.csv", breadth)
    with (inputs / "leadership.csv").open(newline="", encoding="utf-8-sig") as handle:
        leadership = next(csv.DictReader(handle))
    leadership.update(LINEAGE)
    leadership["main_7_symbols"] = "2330,2454"
    _write_csv(inputs / "leadership.csv", leadership)
    # Isolate default historical roots from unrelated repository fixtures.
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "artifacts"
    summary = run_daily_pipeline(
        as_of=DAY, output_dir=out,
        **{arg + "_csv": inputs / filename for arg, filename in (
            ("price", "price.csv"), ("foreign", "foreign_flow.csv"), ("fx", "fx.csv"),
            ("breadth", "breadth.csv"), ("leadership", "leadership.csv"),
            ("futures", "futures.csv"), ("options", "options.csv"), ("margin", "margin.csv"),
        )},
    )
    snapshot = json.loads(Path(summary["assembled_snapshot_path"]).read_text())
    bcd = json.loads((out / "bcd_audit_trace.json").read_text())
    payload = json.loads((out / "tdt_rm_daily_2026-06-05.json").read_text())
    for field, value in LINEAGE.items():
        assert snapshot["canonical_row"][field] == value
        assert snapshot["field_sources"][field] == "leadership_csv"
        assert bcd["raw_inputs"][field] == value
        assert bcd["source_fields"][field] == "leadership_csv"
    assert bcd["raw_inputs"]["main7_returns"] == {"2330": 10.0, "2454": -5.0}
    assert bcd["raw_inputs"]["main7_weights"] == {"2330": 0.3, "2454": 0.7}
    if supply_other_inputs:
        assert payload["bcd_status"] == "COMPLETE"
        assert payload["bcd"] == round(bcd["final_score"], 2)
        assert payload["bcd"] is not None
    else:
        assert payload["bcd_status"] == "INCOMPLETE"
        assert payload["bcd"] is None
        cp = payload["traces"]["crash_probability"]["trace_output"]
        assert cp["raw"]["bcd"] is None
        assert cp["contributions"]["bcd"] == 0.0

    # Replaying the assembled snapshot without raw CSVs must also recover Main7.
    for field in ("main7_returns", "main7_weights", "main7_concentration"):
        snapshot["canonical_row"].pop(field, None)
        snapshot["field_sources"].pop(field, None)
    replay_input = tmp_path / "snapshot_only.json"
    replay_input.write_text(json.dumps(snapshot), encoding="utf-8")
    replay_out = tmp_path / "replay"
    run_daily_pipeline(as_of=DAY, output_dir=replay_out, snapshot_path=replay_input)
    replay = json.loads((replay_out / "tdt_rm_daily_2026-06-05.json").read_text())
    assert replay["bcd_status"] == payload["bcd_status"]
    assert replay["bcd"] == payload["bcd"]
    for field in ("signal", "equity_exposure_limit", "scores"):
        assert replay[field] == payload[field]
