#!/usr/bin/env python3
"""Audit GitHub Actions connectivity to production market-data providers.

This script is intentionally limited to network diagnostics. It does not fetch,
normalize, score, backtest, or alter any TDT-RM model inputs.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

USER_AGENT = "TDT-RM production data connectivity audit/1.0"
RATE_LIMIT_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")
AUTH_STATUSES = {401, 403}

PROVIDERS = (
    {
        "provider": "TWSE",
        "priority": 1,
        "official": True,
        "url": "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date=20260603&response=json",
        "auth_required": False,
        "notes": "Official TWSE report endpoint used for TAIEX price features and related TWSE official reports.",
    },
    {
        "provider": "TAIFEX",
        "priority": 2,
        "official": True,
        "url": "https://openapi.taifex.com.tw/v1/DailyMarketReportFut",
        "auth_required": False,
        "notes": "Official TAIFEX OpenAPI endpoint used for futures/options and TAIFEX FX data.",
    },
    {
        "provider": "CBC",
        "priority": 3,
        "official": True,
        "url": "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=BP01D01en",
        "auth_required": False,
        "notes": "Official CBC Statistical Database API for daily NTD/USD exchange rates.",
    },
    {
        "provider": "FinMind",
        "priority": 4,
        "official": False,
        "url": "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo",
        "auth_required": "token optional for some datasets; production fallback requires FINMIND_TOKEN secret",
        "notes": "Vendor fallback only; not an official source and remains opt-in/token-gated.",
    },
    {
        "provider": "MOF",
        "priority": None,
        "official": True,
        "url": "https://www.mof.gov.tw/eng",
        "auth_required": False,
        "notes": "Official Ministry of Finance web presence audited for connectivity; not currently a canonical TDT-RM market-data provider.",
    },
)


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    priority: int | None
    official: bool
    host: str
    url: str
    dns_ok: bool
    dns_error: str = ""
    resolved_addresses: tuple[str, ...] = ()
    https_ok: bool = False
    response_status: int | None = None
    response_error: str = ""
    elapsed_ms: int | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)
    rate_limited: bool = False
    authentication_requirement: str | bool = False
    authentication_observed: bool = False
    suitability: str = "unknown"
    notes: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production market-data endpoint connectivity.")
    parser.add_argument("--output-dir", default="outputs/market_data_connectivity_audit", help="Directory for JSON/Markdown reports.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP/DNS timeout seconds.")
    parser.add_argument("--repeat", type=int, default=2, help="HTTPS attempts per provider for lightweight rate-limit observation.")
    args = parser.parse_args()

    results = [probe_provider(provider, timeout=args.timeout, repeat=max(1, args.repeat)) for provider in PROVIDERS]
    payload = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runtime": "GitHub Actions compatible Python stdlib connectivity audit",
        "fail_closed": True,
        "providers": [asdict(result) for result in results],
        "summary": {
            "all_official_required_reachable": all(r.dns_ok and r.https_ok and not r.authentication_observed for r in results if r.provider in {"TWSE", "TAIFEX", "CBC"}),
            "blocked_providers": [r.provider for r in results if not (r.dns_ok and r.https_ok)],
        },
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "connectivity_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = render_markdown(payload)
    (output_dir / "connectivity_audit.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if not payload["summary"]["blocked_providers"] else 1


def probe_provider(provider: dict[str, object], *, timeout: float, repeat: int) -> ProbeResult:
    url = str(provider["url"])
    host = urlparse(url).hostname or ""
    dns_ok, addresses, dns_error = resolve_host(host, timeout=timeout)
    status = None
    error = ""
    elapsed_ms = None
    headers: dict[str, str] = {}
    rate_limited = False
    https_ok = False
    for attempt in range(repeat):
        started = time.monotonic()
        status, error, headers = https_get(url, timeout=timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        rate_limited = rate_limited or status == 429 or bool(headers.get("retry-after"))
        https_ok = status is not None and 200 <= status < 400
        if rate_limited or not https_ok:
            break
        if attempt + 1 < repeat:
            time.sleep(0.5)
    authentication_observed = status in AUTH_STATUSES
    suitability = classify_suitability(dns_ok, https_ok, rate_limited, authentication_observed, provider)
    return ProbeResult(
        provider=str(provider["provider"]),
        priority=provider.get("priority") if isinstance(provider.get("priority"), int) else None,
        official=bool(provider.get("official")),
        host=host,
        url=url,
        dns_ok=dns_ok,
        dns_error=dns_error,
        resolved_addresses=tuple(addresses),
        https_ok=https_ok,
        response_status=status,
        response_error=error,
        elapsed_ms=elapsed_ms,
        rate_limit_headers=headers,
        rate_limited=rate_limited,
        authentication_requirement=provider.get("auth_required", False),
        authentication_observed=authentication_observed,
        suitability=suitability,
        notes=str(provider.get("notes", "")),
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


def https_get(url: str, *, timeout: float) -> tuple[int | None, str, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:  # noqa: S310 - configured public endpoints only.
            response.read(2048)
            headers = {name.lower(): value for name, value in response.headers.items() if name.lower() in RATE_LIMIT_HEADERS}
            return int(response.status), "", headers
    except urllib.error.HTTPError as exc:
        headers = {name.lower(): value for name, value in exc.headers.items() if name.lower() in RATE_LIMIT_HEADERS}
        return int(exc.code), f"HTTP {exc.code}", headers
    except Exception as exc:  # noqa: BLE001 - diagnostics must capture exact environment failure.
        return None, f"{exc.__class__.__name__}: {exc}", {}


def classify_suitability(dns_ok: bool, https_ok: bool, rate_limited: bool, auth_observed: bool, provider: dict[str, object]) -> str:
    if not dns_ok:
        return "blocked: DNS resolution failed"
    if auth_observed:
        return "blocked: authentication or WAF denial observed"
    if not https_ok:
        return "blocked: HTTPS request failed"
    if rate_limited:
        return "usable with throttling/backoff"
    if provider.get("provider") == "FinMind":
        return "vendor fallback only; token-gated in production"
    if provider.get("provider") == "MOF":
        return "connectivity-only; no current canonical TDT-RM dataset"
    return "suitable for official automated production fetch"


def render_markdown(payload: dict[str, object]) -> str:
    providers = payload.get("providers", [])
    lines = ["# Production Market Data Connectivity Audit", "", f"- Generated at: `{payload.get('generated_at')}`", f"- Runtime: {payload.get('runtime')}", f"- Fail closed: `{payload.get('fail_closed')}`", "", "| Source | DNS | HTTPS | Status | Rate-limit | Auth | Suitability |", "|---|---:|---:|---:|---:|---:|---|"]
    for row in providers if isinstance(providers, list) else []:
        if not isinstance(row, dict):
            continue
        dns = "PASS" if row.get("dns_ok") else f"FAIL ({row.get('dns_error')})"
        https = "PASS" if row.get("https_ok") else f"FAIL ({row.get('response_error')})"
        auth = "OBSERVED" if row.get("authentication_observed") else str(row.get("authentication_requirement"))
        lines.append(f"| {row.get('provider')} | {dns} | {https} | `{row.get('response_status')}` | `{row.get('rate_limited')}` | `{auth}` | {row.get('suitability')} |")
    lines.extend(["", "## Provider ranking", "", "1. TWSE official source: first choice for cash-market price, foreign-flow, breadth, and leadership data when reachable.", "2. TAIFEX official source: first choice for derivatives data and first official FX source currently wired into the pipeline.", "3. CBC official FX source: official exchange-rate fallback after TAIFEX for USD/TWD continuity.", "4. FinMind fallback: vendor fallback only, opt-in/token-gated, never a silent replacement for official data.", "", "## Architecture", "", "- Tier 1 official sources: TWSE, TAIFEX, CBC; select by dataset and validate strict schemas.", "- Tier 2 vendor fallback: FinMind only when explicitly enabled and authenticated.", "- Tier 3 local emergency fallback: only pre-existing cached/provider artifacts for incident replay; no manual CSV fabrication.", "- Any missing, stale, unauthenticated, synthetic, or schema-invalid provider output blocks the production run."])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
