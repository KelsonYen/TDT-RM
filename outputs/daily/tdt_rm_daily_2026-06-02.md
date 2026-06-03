# TDT-RM Daily Report — 2026-06-02

- Timestamp: `2026-06-03T12:14:24.280144Z`
- Model: `TDT-RM V5.1.4`
- Market regime: **watch**
- Signal: **Green**
- Equity exposure limit: **80-100%**

## Scores

| Metric | Value |
| --- | ---: |
| TCWRS | 0 |
| MHS | 0.0 |
| ETI-5 | 0 |
| Tail Risk | 1.08 |
| BCD | 0.0 |
| CP | 0.22 |

## Market Inputs

| Input | Value |
| --- | ---: |
| Close | 42120.0 |
| MA5 | 42040.0 |
| MA20 | 41780.0 |
| MA60 | 40530.0 |
| MA20 slope | 36.0 |
| 1D return % | 0.12 |
| 2D return % | 0.31 |
| 5D return % | 0.0 |
| 60D return % | 0.0 |
| Consecutive down days | 0 |
| Consecutive closes below MA20 | 0 |

## Data Notes

- Source: Daily enriched market snapshot
- Latest bar date: 2026-06-02
- Bar count: 61
- Data status: `enriched_snapshot`
- MHS uses snapshot field mhs when supplied; no formal MHS scorer is implemented.
- Tail Risk and/or BCD use documented price-only fallback proxies because formal snapshot values are absent.

## Source Coverage and Fallbacks

- Available ETI components: `ETI-1`
- Missing fields: `none reported`
- Fallback proxies: `{"bcd": {"reason": "formal bcd absent from daily snapshot", "status": "price_only_proxy"}, "tail_risk": {"reason": "formal tail_risk absent from daily snapshot", "status": "price_only_proxy"}}`
- Field source count: `10`

## Future ETF Exit Integration

- Enabled: `False`
- Status: `not_integrated`
- Notes: Reserved for future ETF Exit integration; no ETF exit logic applied.
