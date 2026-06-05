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
            "success": False,
        }
    ]
    assert "`price` | `TWSE_OFFICIAL` | `https://example.invalid` | `HTTP 403` | 17" in markdown
    assert "`not_reached` | `not_reached` | `auth/token`" in markdown


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
