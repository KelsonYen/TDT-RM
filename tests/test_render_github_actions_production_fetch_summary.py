from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_github_actions_production_fetch_summary.py"
_SPEC = importlib.util.spec_from_file_location("render_github_actions_production_fetch_summary", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_attempt_rows_prefers_manifest_source_attempts_unchanged() -> None:
    manifest_attempt = {
        "provider_category": "price",
        "source_id": "MANIFEST_PROVIDER",
        "success": False,
        "http_status": 429,
        "rows_fetched": 12,
        "parser_status": "failed",
        "validation_status": "not_reached",
        "failure_class": "rate_limit",
        "error": "manifest diagnostic",
    }
    provider_health = {
        "providers": {
            "price_provider": {
                "dataset": "price",
                "attempts": [
                    {
                        "provider": "HEALTH_PROVIDER",
                        "status": "healthy",
                        "http_status": 200,
                        "rows_fetched": 99,
                    }
                ],
            }
        }
    }

    rows = _MODULE._attempt_rows({"source_attempts": [manifest_attempt]}, provider_health)

    assert rows == [manifest_attempt]


def test_attempt_rows_provider_health_fallback_preserves_diagnostics() -> None:
    provider_health = {
        "providers": {
            "price_provider": {
                "dataset": "price",
                "attempts": [
                    {
                        "provider_id": "TWSE_OFFICIAL",
                        "status": "failed",
                        "http_status": 403,
                        "network_exception": "",
                        "error": "HTTP 403 from https://example.invalid",
                        "rows_fetched": 17,
                        "parser_status": "not_reached",
                        "validation_status": "not_reached",
                        "failure_class": "auth/token",
                        "endpoint_attempted": "https://example.invalid",
                    }
                ],
            }
        }
    }

    rows = _MODULE._attempt_rows({"source_attempts": []}, provider_health)
    markdown = _MODULE._render_markdown(
        "2026-06-03",
        Path("/tmp/input"),
        Path("/tmp/output"),
        Path("/tmp/reports"),
        {"source_attempts": []},
        {},
        provider_health,
        {},
        {},
    )

    assert rows == [
        {
            "provider_id": "TWSE_OFFICIAL",
            "status": "failed",
            "http_status": 403,
            "network_exception": "",
            "error": "HTTP 403 from https://example.invalid",
            "rows_fetched": 17,
            "parser_status": "not_reached",
            "validation_status": "not_reached",
            "failure_class": "auth/token",
            "endpoint_attempted": "https://example.invalid",
            "provider_category": "price",
            "source_id": "TWSE_OFFICIAL",
            "failure_layer": "AUTH",
            "success": False,
        }
    ]
    assert "`price` | `TWSE_OFFICIAL` | `https://example.invalid` | `HTTP 403` | 17" in markdown
    assert "`not_reached` | `not_reached` | `auth/token` | `AUTH`" in markdown


def test_provider_health_legacy_minimal_attempts_still_render() -> None:
    provider_health = {
        "providers": {
            "price_provider": {
                "dataset": "price",
                "attempts": [
                    {
                        "provider": "LEGACY_PROVIDER",
                        "status": "failed",
                    }
                ],
            }
        }
    }

    markdown = _MODULE._render_markdown(
        "2026-06-03",
        Path("/tmp/input"),
        Path("/tmp/output"),
        Path("/tmp/reports"),
        {},
        {},
        provider_health,
        {},
        {},
    )

    assert "`price` | `LEGACY_PROVIDER` | `n/a` | `none` | 0 | `n/a` | `n/a` | `n/a`" in markdown


def test_provider_health_fallback_uses_url_fetch_metadata_when_manifest_incomplete() -> None:
    provider_health = {
        "providers": {
            "price_provider": {
                "dataset": "price",
                "attempts": [
                    {
                        "provider": "TWSE_OFFICIAL",
                        "status": "failed",
                        "failure_reason": "URL fetch failed",
                        "metadata": {
                            "url_fetch": {
                                "final_url": "https://example.invalid/final",
                                "status": 503,
                                "attempts": 3,
                                "errors": [{"url": "https://example.invalid/final", "attempt": 3, "status": 503, "error": "HTTP 503"}],
                            }
                        },
                    }
                ],
            }
        }
    }

    rows = _MODULE._attempt_rows({"source_attempts": []}, provider_health)
    markdown = _MODULE._render_markdown(
        "2026-06-03",
        Path("/tmp/input"),
        Path("/tmp/output"),
        Path("/tmp/reports"),
        {"source_attempts": []},
        {},
        provider_health,
        {},
        {},
    )

    assert rows[0]["endpoint_attempted"] == "https://example.invalid/final"
    assert rows[0]["http_status"] == 503
    assert "`price` | `TWSE_OFFICIAL` | `https://example.invalid/final` | `HTTP 503`" in markdown


def test_provider_health_fallback_classifies_tunnel_403_as_network_layer() -> None:
    provider_health = {
        "providers": {
            "breadth_provider": {
                "dataset": "breadth",
                "attempts": [
                    {
                        "provider": "TWSE_OFFICIAL",
                        "status": "failed",
                        "failure_reason": "URL fetch failed from https://example.invalid after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>",
                    }
                ],
            }
        }
    }

    rows = _MODULE._attempt_rows({"source_attempts": []}, provider_health)

    assert rows[0]["failure_layer"] == "NETWORK"


def test_renderer_writes_dataset_matrix_to_fetch_summary_from_partial_provider_health(tmp_path: Path, monkeypatch) -> None:
    import json

    trade_date = "2026-06-03"
    input_dir = tmp_path / "inputs" / trade_date
    output_dir = tmp_path / "outputs" / trade_date
    reports_dir = tmp_path / "reports" / trade_date
    artifacts_dir = reports_dir / "artifacts"
    artifacts_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (output_dir / "fetch_manifest.json").write_text(
        json.dumps(
            {
                "as_of": trade_date,
                "trade_date": trade_date,
                "data_status": "NOT_READY",
                "production_ready": False,
                "missing_production_csvs": ["price.csv"],
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "provider_health.json").write_text(
        json.dumps(
            {
                "providers": {
                    "price_provider": {
                        "dataset": "price",
                        "attempts": [
                            {
                                "provider": "TWSE_OFFICIAL",
                                "status": "failed",
                                "failure_reason": "HTTP 403 from https://example.invalid after 1 attempts",
                                "parser_status": "not_reached",
                                "validation_status": "not_reached",
                                "failure_class": "auth/token",
                                "metadata": {
                                    "endpoint": "https://example.invalid",
                                    "url_fetch": {"status": 403, "final_url": "https://example.invalid"},
                                },
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_github_actions_production_fetch_summary.py",
            "--trade-date",
            trade_date,
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--reports-dir",
            str(reports_dir),
        ],
    )

    assert _MODULE.main() == 0

    summary = json.loads((artifacts_dir / "production_fetch_summary.json").read_text(encoding="utf-8"))
    matrix = {row["dataset"]: row for row in summary["dataset_audit_matrix"]}
    assert matrix["price"]["provider_chain"] == "TWSE_OFFICIAL"
    assert matrix["price"]["provider_attempted"] == "TWSE_OFFICIAL"
    assert matrix["price"]["endpoint_attempted"] == "https://example.invalid"
    assert matrix["price"]["exception_message"] == "HTTP 403 from https://example.invalid after 1 attempts"
    assert matrix["price"]["http_status"] == "403"
    assert matrix["price"]["failure_happened_at"] == "remote HTTP response"
    assert matrix["price"]["parser_executed"] == "NO"
    assert matrix["price"]["validation_executed"] == "NO"
    assert matrix["price"]["output_csv_written"] == "NO"
    assert matrix["price"]["root_cause_classification"] == "auth/token"
