#!/usr/bin/env python3
"""Audit GitHub Actions connectivity to production market-data providers.

This script is intentionally limited to provider connectivity and sample-payload
validation. It does not fetch production snapshots, normalize model inputs,
score, backtest, or alter any TDT-RM model logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

USER_AGENT = "TDT-RM production data connectivity audit/2.0"
RATE_LIMIT_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")
AUTH_STATUSES = {401, 403}
MATRIX_FIELDS = (
    "provider_name",
    "dataset_type",
    "endpoint_or_method",
    "requires_token",
    "token_present",
    "dns_ok",
    "https_ok",
    "http_status",
    "sample_rows_or_payload_present",
    "usable_for_production",
    "failure_reason",
)


def _twse_fmtqik_url(as_of: str) -> str:
    return f"https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date={as_of.replace('-', '')}&response=json"


def _finmind_url(token_present: bool) -> str:
    query = {"dataset": "TaiwanStockInfo"}
    if token_present:
        query["token"] = "__FINMIND_TOKEN_REDACTED__"
    return "https://api.finmindtrade.com/api/v4/data?" + urlencode(query)


def _finmind_request_url(token: str | None) -> str:
    query = {"dataset": "TaiwanStockInfo"}
    if token:
        query["token"] = token
    return "https://api.finmindtrade.com/api/v4/data?" + urlencode(query)


@dataclass(frozen=True)
class ProviderProbe:
    provider_name: str
    dataset_type: str
    endpoint_or_method: str
    request_url: str
    requires_token: bool = False
    token_env_var: str = ""
    official: bool = False
    production_role: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ProviderMatrixRow:
    provider_name: str
    dataset_type: str
    endpoint_or_method: str
    requires_token: bool
    token_present: bool
    dns_ok: bool
    https_ok: bool
    http_status: int | None
    sample_rows_or_payload_present: bool
    usable_for_production: bool
    failure_reason: str
    runtime_context: str
    official: bool
    production_role: str
    host: str
    dns_error: str = ""
    resolved_addresses: tuple[str, ...] = ()
    response_error: str = ""
    elapsed_ms: int | None = None
    rate_limited: bool = False
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    sample_evidence: str = ""
    notes: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit market-data provider connectivity from a GitHub Actions compatible runner.")
    parser.add_argument("--output-dir", default="outputs/market_data_connectivity_audit", help="Directory for JSON/Markdown/CSV reports.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP/DNS timeout seconds.")
    parser.add_argument("--repeat", type=int, default=1, help="HTTPS attempts per provider for lightweight rate-limit observation.")
    parser.add_argument("--as-of", default=datetime.now(UTC).date().isoformat(), help="Probe date for date-parameterized official endpoints, YYYY-MM-DD.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("FINMIND_TOKEN") or os.environ.get("FINMIND_API_TOKEN")
    probes = build_provider_probes(args.as_of, token)
    runtime_context = detect_runtime_context()
    results = [probe_provider(probe, timeout=args.timeout, repeat=max(1, args.repeat), runtime_context=runtime_context) for probe in probes]
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "generated_at": generated_at,
        "as_of": args.as_of,
        "runtime_context": runtime_context,
        "runner_note": "GitHub Actions workflow_dispatch is the authoritative production-connectivity environment; local/Codex failures are classified separately.",
        "artifact_files": {
            "markdown_summary": "connectivity_audit.md",
            "json_artifact": "connectivity_audit.json",
            "csv_provider_matrix": "provider_matrix.csv",
        },
        "fail_closed": True,
        "provider_matrix_columns": list(MATRIX_FIELDS),
        "providers": [asdict(result) for result in results],
        "summary": summarize(results),
        "next_step_options": {
            "provider_authentication_failure": "Add/verify GitHub Actions secrets token, especially FINMIND_TOKEN for FinMind fallback.",
            "provider_schema_api_failure": "Implement or repair an official source parser with strict schema validation.",
            "provider_rate_limit": "Add throttling/backoff or choose a paid provider with an SLA.",
            "github_actions_runner_network_failure": "Use a paid provider, scheduled external fetcher, or alternate official endpoint reachable from GitHub-hosted runners.",
            "codex_runtime_network_failure": "Do not treat Codex/local network failure as final; rerun the workflow on GitHub Actions.",
        },
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "connectivity_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_provider_matrix_csv(output_dir / "provider_matrix.csv", results)
    report = render_markdown(payload)
    (output_dir / "connectivity_audit.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def build_provider_probes(as_of: str, finmind_token: str | None) -> tuple[ProviderProbe, ...]:
    return (
        ProviderProbe(
            provider_name="TWSE official endpoint",
            dataset_type="TAIEX cash-market price",
            endpoint_or_method=_twse_fmtqik_url(as_of),
            request_url=_twse_fmtqik_url(as_of),
            official=True,
            production_role="Official source candidate for TAIEX price features.",
        ),
        ProviderProbe(
            provider_name="TAIFEX official endpoint",
            dataset_type="TAIEX futures derivatives",
            endpoint_or_method="https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
            request_url="https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
            official=True,
            production_role="Official source candidate for futures/options-derived fields.",
        ),
        ProviderProbe(
            provider_name="Yahoo Finance chart API",
            dataset_type="public TAIEX price (yfinance-compatible)",
            endpoint_or_method="Yahoo Finance chart endpoint for ^TWII, equivalent to the public endpoint used by yfinance-style fetches",
            request_url="https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?range=10d&interval=1d",
            production_role="Public price-source candidate; not official TWSE.",
        ),
        ProviderProbe(
            provider_name="Stooq CSV endpoint",
            dataset_type="public TAIEX price",
            endpoint_or_method="https://stooq.com/q/d/l/?s=^twii&i=d",
            request_url="https://stooq.com/q/d/l/?s=^twii&i=d",
            production_role="Public price-source candidate; not official TWSE.",
        ),
        ProviderProbe(
            provider_name="FinMind API",
            dataset_type="vendor Taiwan market metadata/sample",
            endpoint_or_method=_finmind_url(bool(finmind_token)),
            request_url=_finmind_request_url(finmind_token),
            requires_token=True,
            token_env_var="FINMIND_TOKEN or FINMIND_API_TOKEN",
            production_role="Vendor fallback only; production use must be explicitly token-gated.",
            notes="Missing token is reported as authentication-not-tested, not as provider failure.",
        ),
        ProviderProbe(
            provider_name="CBC FX official endpoint",
            dataset_type="USD/TWD FX",
            endpoint_or_method="https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en",
            request_url="https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en",
            official=True,
            production_role="Official public USD/TWD FX source candidate.",
        ),
    )


def detect_runtime_context() -> str:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return "github_actions_runner"
    if os.environ.get("CODEX_CI") or os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX") or os.environ.get("OPENAI_SANDBOX") or "codex" in os.environ.get("USER", "").lower():
        return "codex_runtime"
    return "local_runtime"


def probe_provider(probe: ProviderProbe, *, timeout: float, repeat: int, runtime_context: str) -> ProviderMatrixRow:
    host = urlparse(probe.request_url).hostname or ""
    dns_ok, addresses, dns_error = resolve_host(host, timeout=timeout)
    status = None
    error = ""
    elapsed_ms = None
    headers: dict[str, str] = {}
    rate_limited = False
    sample_present = False
    sample_evidence = ""
    https_ok = False

    for attempt in range(repeat):
        started = time.monotonic()
        status, error, headers, sample_present, sample_evidence = https_get_sample(probe.request_url, timeout=timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        rate_limited = rate_limited or status == 429 or bool(headers.get("retry-after"))
        https_ok = status is not None and 200 <= status < 400
        if rate_limited or not https_ok or sample_present:
            break
        if attempt + 1 < repeat:
            time.sleep(0.5)

    token_present = bool(os.environ.get(probe.token_env_var.split()[0])) if probe.token_env_var else False
    if probe.provider_name == "FinMind API":
        token_present = bool(os.environ.get("FINMIND_TOKEN") or os.environ.get("FINMIND_API_TOKEN"))
    failure_reason = classify_failure_reason(
        runtime_context=runtime_context,
        probe=probe,
        token_present=token_present,
        dns_ok=dns_ok,
        https_ok=https_ok,
        status=status,
        error=error,
        sample_present=sample_present,
        rate_limited=rate_limited,
    )
    usable = failure_reason == ""
    if probe.requires_token and not token_present:
        usable = False
    return ProviderMatrixRow(
        provider_name=probe.provider_name,
        dataset_type=probe.dataset_type,
        endpoint_or_method=probe.endpoint_or_method,
        requires_token=probe.requires_token,
        token_present=token_present,
        dns_ok=dns_ok,
        https_ok=https_ok,
        http_status=status,
        sample_rows_or_payload_present=sample_present,
        usable_for_production=usable,
        failure_reason=failure_reason,
        runtime_context=runtime_context,
        official=probe.official,
        production_role=probe.production_role,
        host=host,
        dns_error=dns_error,
        resolved_addresses=tuple(addresses),
        response_error=error,
        elapsed_ms=elapsed_ms,
        rate_limited=rate_limited,
        rate_limit_headers=headers,
        sample_evidence=sample_evidence,
        notes=probe.notes,
    )


def resolve_host(host: str, *, timeout: float) -> tuple[bool, list[str], str]:
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({info[4][0] for info in infos})
        return True, addresses, ""
    except OSError as exc:
        return False, [], f"{exc.__class__.__name__}: {exc}"
    finally:
        socket.setdefaulttimeout(previous_timeout)


def https_get_sample(url: str, *, timeout: float) -> tuple[int | None, str, dict[str, str], bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,text/plain,text/html;q=0.9,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:  # noqa: S310 - configured public endpoints only.
            raw = response.read(262144)
            headers = {name.lower(): value for name, value in response.headers.items() if name.lower() in RATE_LIMIT_HEADERS}
            sample_present, sample_evidence = inspect_sample_payload(raw, response.headers.get("Content-Type", ""))
            return int(response.status), "", headers, sample_present, sample_evidence
    except urllib.error.HTTPError as exc:
        raw = exc.read(32768)
        headers = {name.lower(): value for name, value in exc.headers.items() if name.lower() in RATE_LIMIT_HEADERS}
        sample_present, sample_evidence = inspect_sample_payload(raw, exc.headers.get("Content-Type", ""))
        return int(exc.code), f"HTTP {exc.code}", headers, sample_present, sample_evidence
    except Exception as exc:  # noqa: BLE001 - diagnostics must capture exact environment failure.
        return None, f"{exc.__class__.__name__}: {exc}", {}, False, ""


def inspect_sample_payload(raw: bytes, content_type: str) -> tuple[bool, str]:
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return False, "empty response body"
    lowered_content_type = content_type.lower()
    if text.startswith("{") or text.startswith("[") or "json" in lowered_content_type:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return False, f"json parse error: {exc}"
        count = count_json_rows(parsed)
        if count > 0:
            return True, f"json payload rows/items detected: {count}"
        return False, "json parsed but no rows/items detected"
    if "," in text or "csv" in lowered_content_type:
        rows = list(csv.reader(text.splitlines()))
        data_rows = max(0, len(rows) - 1)
        if data_rows > 0:
            return True, f"csv data rows detected: {data_rows}"
    if len(text) > 20:
        return True, f"non-empty payload bytes: {len(raw)}"
    return False, "payload too small to validate"


def count_json_rows(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("data", "chart", "result", "records", "items"):
            child = value.get(key)
            if isinstance(child, list):
                return len(child)
            if isinstance(child, dict):
                nested_count = count_json_rows(child)
                if nested_count > 0:
                    return nested_count
        return 1 if value else 0
    return 0


def classify_failure_reason(
    *,
    runtime_context: str,
    probe: ProviderProbe,
    token_present: bool,
    dns_ok: bool,
    https_ok: bool,
    status: int | None,
    error: str,
    sample_present: bool,
    rate_limited: bool,
) -> str:
    if probe.requires_token and not token_present:
        return "Provider authentication not tested: token required for production fallback and FINMIND_TOKEN/FINMIND_API_TOKEN is absent; not counted as provider failure"
    if rate_limited or status == 429:
        return "Provider rate limit"
    if not dns_ok or status is None or is_proxy_or_transport_error(error):
        if runtime_context == "github_actions_runner":
            return "GitHub Actions runner network failure"
        if runtime_context == "codex_runtime":
            return "Codex runtime network failure"
        return "Local runtime network failure"
    if status in AUTH_STATUSES:
        return "Provider authentication failure"
    if not https_ok:
        return "Provider schema / API failure"
    if not sample_present:
        return "Provider schema / API failure"
    return ""


def is_proxy_or_transport_error(error: str) -> bool:
    lowered = error.lower()
    markers = ("urlerror", "timeout", "tunnel connection failed", "temporary failure in name resolution", "ssl", "connection refused", "network is unreachable")
    return any(marker in lowered for marker in markers)


def summarize(results: list[ProviderMatrixRow]) -> dict[str, Any]:
    return {
        "production_usable_providers": [row.provider_name for row in results if row.usable_for_production],
        "unusable_providers": [row.provider_name for row in results if not row.usable_for_production],
        "github_actions_authoritative": any(row.runtime_context == "github_actions_runner" for row in results),
        "finmind_token_present": any(row.provider_name == "FinMind API" and row.token_present for row in results),
        "failure_categories": sorted({row.failure_reason for row in results if row.failure_reason}),
    }


def write_provider_matrix_csv(path: Path, results: list[ProviderMatrixRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_FIELDS)
        writer.writeheader()
        for row in results:
            data = asdict(row)
            writer.writerow({field: data[field] for field in MATRIX_FIELDS})


def render_markdown(payload: dict[str, Any]) -> str:
    providers = payload.get("providers", [])
    lines = [
        "# Production Data Provider Connectivity Audit",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Probe as-of date: `{payload.get('as_of')}`",
        f"- Runtime context: `{payload.get('runtime_context')}`",
        "- Scope: connectivity/sample-payload audit only; no scoring model, ETF Exit model, or manual fallback changes.",
        "- GitHub Actions `workflow_dispatch` runs are authoritative for production connectivity; Codex/local network failures are not final provider conclusions.",
        "",
        "## Artifact files",
        "",
        "- Markdown summary: `connectivity_audit.md`",
        "- JSON artifact: `connectivity_audit.json`",
        "- CSV provider matrix: `provider_matrix.csv`",
        "",
        "## Provider matrix",
        "",
        "| provider_name | dataset_type | requires_token | token_present | dns_ok | https_ok | http_status | sample_rows_or_payload_present | usable_for_production | failure_reason |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in providers if isinstance(providers, list) else []:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {provider_name} | {dataset_type} | `{requires_token}` | `{token_present}` | `{dns_ok}` | `{https_ok}` | `{http_status}` | `{sample_rows_or_payload_present}` | `{usable_for_production}` | {failure_reason} |".format(
                provider_name=row.get("provider_name"),
                dataset_type=row.get("dataset_type"),
                requires_token=row.get("requires_token"),
                token_present=row.get("token_present"),
                dns_ok=row.get("dns_ok"),
                https_ok=row.get("https_ok"),
                http_status=row.get("http_status"),
                sample_rows_or_payload_present=row.get("sample_rows_or_payload_present"),
                usable_for_production=row.get("usable_for_production"),
                failure_reason=row.get("failure_reason") or "",
            )
        )
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    usable = summary.get("production_usable_providers", [])
    categories = summary.get("failure_categories", [])
    lines.extend(
        [
            "",
            "## Production usability conclusion",
            "",
            f"- Usable providers in this runtime: `{', '.join(usable) if usable else 'none'}`",
            f"- Observed failure categories: `{', '.join(categories) if categories else 'none'}`",
            "- FinMind: requires a GitHub Actions secret (`FINMIND_TOKEN` or `FINMIND_API_TOKEN`) for production fallback acceptance; an absent token is reported as authentication-not-tested, not provider failure.",
            "- Local fallback/manual CSV paths are intentionally not counted as production success.",
            "",
            "## Failure category handling",
            "",
            "- Codex runtime network failure: rerun the GitHub Actions workflow before drawing provider conclusions.",
            "- GitHub Actions runner network failure: change endpoint/provider, use a paid provider, or move fetching to a scheduled external fetcher.",
            "- Provider authentication failure: add or rotate GitHub Actions secrets token.",
            "- Provider schema / API failure: implement or repair an official source parser and validation contract.",
            "- Provider rate limit: add backoff/throttling or choose a paid provider with an SLA.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
