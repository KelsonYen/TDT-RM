# TDT-RM Daily Report — 2026-06-05

- Timestamp: `2026-06-05T23:42:40.820327Z`
- Model: `TDT-RM V5.1.4`
- Market regime: **watch**
- Signal: **Yellow**
- Equity exposure limit: **60-80%**

## Scores

| Metric | Value |
| --- | ---: |
| TCWRS | 12 |
| MHS | 100.0 |
| ETI-5 | 1 |
| Tail Risk | 53.95 |
| BCD | 53.95 |
| CP | 26.98 |

## Market Inputs

| Input | Value |
| --- | ---: |
| Close | 45070.94 |
| MA5 | 45620.56 |
| MA20 | 43030.51 |
| MA60 | 38316.18 |
| MA20 slope | 173.35 |
| 1D return % | -1.3278 |
| 2D return % | -2.988 |
| 5D return % | 0.7556 |
| 60D return % | 37.5294 |
| Consecutive down days | 1 |
| Consecutive closes below MA20 | 0 |

## Data Notes

- Source: Daily enriched market snapshot
- Latest bar date: 2026-06-05
- Bar count: 61
- Data status: `enriched_snapshot`
- MHS uses snapshot field mhs when supplied; no formal MHS scorer is implemented.

## Source Coverage and Fallbacks

- Available ETI components: `ETI-1, ETI-2, ETI-3, ETI-4, ETI-5`
- Missing fields: `none reported`
- Fallback proxies: `{}`
- Field source count: `50`

## Future ETF Exit Integration

- Enabled: `False`
- Status: `not_integrated`
- Notes: Reserved for future ETF Exit integration; no ETF exit logic applied.
