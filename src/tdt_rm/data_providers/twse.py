"""TWSE official public-data providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any, Mapping

from tdt_rm.public_data_fetchers import (
    PublicDataFetchContext,
    TWSEFMTQIKPriceSource,
    TWSEMarketBreadthSource,
    TWSEMain7LeadershipSource,
    TWSEMarginSource,
    TWSET86ForeignFlowSource,
    load_source_config,
)

from .base import DailyDataProvider, ProviderContext, ProviderFetchError, ProviderResult
from .normalizers import normalize_public_row

_SOURCE_BY_DATASET = {
    "price": ("twse_fmtqik_price", TWSEFMTQIKPriceSource),
    "foreign_flow": ("twse_t86_foreign_flow", TWSET86ForeignFlowSource),
    "breadth": ("twse_mi_index_breadth", TWSEMarketBreadthSource),
    "leadership": ("twse_main7_leadership", TWSEMain7LeadershipSource),
    "margin": ("twse_margin", TWSEMarginSource),
}


@dataclass(frozen=True)
class TWSEProvider(DailyDataProvider):
    """Provider that fetches official TWSE public endpoints before vendor fallbacks."""

    source_config: str | None = None
    name: str = "TWSE_OFFICIAL"
    datasets: tuple[str, ...] = ("price", "foreign_flow", "breadth", "leadership", "margin")

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset not in _SOURCE_BY_DATASET:
            raise ValueError(f"TWSE provider does not support {dataset}")
        source_id, source_cls = _SOURCE_BY_DATASET[dataset]
        config = _source_config(source_id, self.source_config)
        result = source_cls(config).fetch(_public_context(context))
        if not result.success:
            raise ProviderFetchError(_failure_message(result.status, result.issues), result.raw_metadata)
        raw_row = dict(result.rows[0] if result.rows else result.canonical_fields)
        provider_source = f"{self.name}:{result.source_id}"
        row = normalize_public_row(dataset, raw_row, trade_date=context.trade_date, provider_source=provider_source)
        return ProviderResult(dataset, provider_source, result.source_id, row, result.raw_metadata)


def _public_context(context: ProviderContext) -> PublicDataFetchContext:
    return PublicDataFetchContext(
        as_of=context.trade_date,
        main7_symbols=context.main7_symbols,
        timeout_seconds=context.timeout,
        retrieved_at=context.fetched_at.replace(tzinfo=UTC) if context.fetched_at.tzinfo is None else context.fetched_at,
    )


def _source_config(source_id: str, source_config: str | None) -> Mapping[str, Any]:
    payload = load_source_config(source_config)
    for item in payload.get("sources", []):
        if isinstance(item, Mapping) and item.get("source_id") == source_id:
            return item
    raise RuntimeError(f"missing public data source config: {source_id}")


def _failure_message(status: str, issues: tuple[Any, ...]) -> str:
    messages = "; ".join(str(getattr(issue, "message", issue)) for issue in issues)
    return f"status={status}" + (f"; {messages}" if messages else "")

@dataclass(frozen=True)
class TWSEBreadthHistoryAdapter:
    """Adapter facade for audit-required TWSE advancing/declining history."""

    source_config: str | None = None

    def fetch_history(self, context: ProviderContext, *, lookback_days: int = 20) -> list[dict[str, Any]]:
        """Return available official breadth rows through the provider layer.

        The adapter does not synthesize missing dates; failed or unavailable
        TWSE observations are simply omitted so downstream BCD trace can mark
        breadth_history as partial when history is insufficient.
        """

        rows: list[dict[str, Any]] = []
        provider = TWSEProvider(source_config=self.source_config)
        from datetime import timedelta

        for offset in range(lookback_days + 1):
            observed = context.trade_date - timedelta(days=offset)
            shifted = ProviderContext(
                trade_date=observed,
                fetched_at=context.fetched_at,
                timeout=context.timeout,
                lookback_days=context.lookback_days,
                main7_symbols=context.main7_symbols,
                breadth_universe_config=context.breadth_universe_config,
            )
            try:
                rows.append(provider.fetch("breadth", shifted).row)
            except Exception:  # noqa: BLE001 - history is optional; absence is audited downstream.
                continue
        return sorted(rows, key=lambda item: str(item.get("trade_date") or ""))


@dataclass(frozen=True)
class TWSESectorBreadthAdapter:
    """Placeholder-free sector breadth adapter contract for TWSE public sources."""

    source_config: str | None = None

    def fetch_sector_breadth(self, context: ProviderContext) -> dict[str, Any]:
        """Return sector breadth if a public TWSE sector source is configured.

        Current production config has no sector endpoint; returning an explicit
        unavailable payload lets BCD disclose sector_breadth as missing instead
        of inventing neutral sector participation.
        """

        return {
            "trade_date": context.trade_date.isoformat(),
            "status": "unavailable",
            "missing_component": "sector_breadth",
            "reason": "No configured TWSE public sector breadth endpoint.",
        }


@dataclass(frozen=True)
class TWSEAdvancingDecliningHistoryAdapter(TWSEBreadthHistoryAdapter):
    """Named audit integration point for advancing/declining issues history."""
