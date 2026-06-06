import json
import subprocess
import sys
from pathlib import Path

from tdt_rm.daily_snapshot import derive_eti_available_components, load_daily_snapshot_json
from tdt_rm.daily_validation import validate_daily_artifacts

FIXTURE_DIR = Path("examples/daily_snapshots")
JSON_FIXTURE = FIXTURE_DIR / "sample_enriched_snapshot.json"
CSV_FIXTURE = FIXTURE_DIR / "sample_enriched_snapshot.csv"
FIELD_MAP_FIXTURE = FIXTURE_DIR / "sample_field_map.json"
AS_OF = "2026-05-29"


def test_sample_json_snapshot_runs_through_smoke_script(tmp_path: Path):
    output_dir = tmp_path / "json_smoke"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_daily_production.py",
            "--snapshot-path",
            str(JSON_FIXTURE),
            "--output-dir",
            str(output_dir),
            "--as-of",
            AS_OF,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "validation_status: passed" in completed.stdout
    assert "incomplete_bcd" in completed.stdout
    json_path = output_dir / "tdt_rm_daily_2026-05-29.json"
    markdown_path = output_dir / "tdt_rm_daily_2026-05-29.md"
    manifest_path = output_dir / "tdt_rm_daily_2026-05-29_manifest.json"
    assert json_path.exists()
    assert markdown_path.exists()
    assert manifest_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation = validate_daily_artifacts(json_path, markdown_path)
    assert validation.status == "passed"
    assert payload["data"]["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"
    assert set(payload["data"]["available_eti_components"]) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}
    assert payload["traces"]["eti_5"]["eti_available_count"] == 5
    assert manifest["validation_status"] == "passed"
    assert manifest["artifact_paths"] == {"json": str(json_path), "markdown": str(markdown_path)}


def test_sample_csv_snapshot_can_be_normalized_and_run(tmp_path: Path):
    normalized_snapshot = tmp_path / "normalized" / "sample_enriched_snapshot.normalized.json"
    output_dir = tmp_path / "csv_smoke"

    build = subprocess.run(
        [
            sys.executable,
            "scripts/build_daily_snapshot.py",
            "--input-csv",
            str(CSV_FIXTURE),
            "--field-map",
            str(FIELD_MAP_FIXTURE),
            "--output-json",
            str(normalized_snapshot),
            "--as-of",
            AS_OF,
            "--validate",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert normalized_snapshot.exists()

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_daily_production.py",
            "--snapshot-path",
            str(normalized_snapshot),
            "--output-dir",
            str(output_dir),
            "--as-of",
            AS_OF,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "validation_status: passed" in completed.stdout
    json_path = output_dir / "tdt_rm_daily_2026-05-29.json"
    markdown_path = output_dir / "tdt_rm_daily_2026-05-29.md"
    manifest_path = output_dir / "tdt_rm_daily_2026-05-29_manifest.json"
    assert json_path.exists()
    assert markdown_path.exists()
    assert manifest_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    validation = validate_daily_artifacts(json_path, markdown_path)
    assert validation.status == "passed"
    assert payload["data"]["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"
    assert set(payload["data"]["available_eti_components"]) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}
    assert payload["traces"]["eti_5"]["eti_available_count"] == 5


def test_sample_fixture_eti_available_components_match_supplied_fields():
    snapshot = load_daily_snapshot_json(JSON_FIXTURE)

    assert derive_eti_available_components(snapshot) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}
