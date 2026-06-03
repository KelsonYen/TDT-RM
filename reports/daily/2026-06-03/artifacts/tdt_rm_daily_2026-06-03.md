# TDT-RM Daily Report — 2026-06-03

- Timestamp: `2026-06-03T13:33:38.991527Z`
- Model: `TDT-RM V5.1.4`
- Market regime: **risk-on**
- Signal: **Green**
- Equity exposure limit: **80-100%**

## Scores

| Metric | Value |
| --- | ---: |
| TCWRS | 0 |
| MHS | 5.0 |
| ETI-5 | 0 |
| Tail Risk | 12.5 |
| BCD | 8.0 |
| CP | 3.3 |

## Market Inputs

| Input | Value |
| --- | ---: |
| Close | 21550.25 |
| MA5 | 21480.1 |
| MA20 | 21320.4 |
| MA60 | 20780.55 |
| MA20 slope | 18.75 |
| 1D return % | 0.42 |
| 2D return % | 0.85 |
| 5D return % | 1.25 |
| 60D return % | 3.7 |
| Consecutive down days | 0 |
| Consecutive closes below MA20 | 0 |

## Data Notes

- Source: Daily enriched market snapshot
- Latest bar date: 2026-06-03
- Bar count: 61
- Data status: `enriched_snapshot`
- MHS uses snapshot field mhs when supplied; no formal MHS scorer is implemented.

## Source Coverage and Fallbacks

- Available ETI components: `ETI-1, ETI-2, ETI-3, ETI-4, ETI-5`
- Missing fields: `none reported`
- Fallback proxies: `{}`
- Field source count: `46`

## Future ETF Exit Integration

- Enabled: `False`
- Status: `not_integrated`
- Notes: Reserved for future ETF Exit integration; no ETF exit logic applied.
