# TDT-RM Daily Report — 2026-06-05

- Timestamp: `2026-06-06T00:17:14.755163Z`
- Model: `TDT-RM V5.1.4`
- Market regime: **watch**
- Signal: **Yellow**
- Equity exposure limit: **60-80%**
- Production report quality: **FAIL_FOR_OPERATOR_USE**

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

## Operator Disclosure

* Production Report Quality: `FAIL_FOR_OPERATOR_USE`
* Acceptable for Real-World Daily Use: `NO`

### Official Provider Datasets
* source_id=breadth_csv; provider_source=TWSE_OFFICIAL:twse_mi_index_breadth; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/breadth.csv
* source_id=foreign_flow_csv; provider_source=TWSE_OFFICIAL:twse_t86_foreign_flow; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/foreign_flow.csv
* source_id=futures_csv; provider_source=TAIFEX_OFFICIAL:taifex_txf_futures; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/futures.csv
* source_id=fx_csv; provider_source=TAIFEX_OFFICIAL:taifex_daily_fx; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/fx.csv
* source_id=leadership_csv; provider_source=TWSE_OFFICIAL:twse_main7_leadership; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/leadership.csv
* source_id=margin_csv; provider_source=TWSE_OFFICIAL:twse_margin; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/margin.csv
* source_id=taiex_price; provider_source=TWSE_OFFICIAL:twse_fmtqik_price; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/price.csv

### Fallback Provider Datasets
* source_id=options_csv; provider_source=FINMIND_FALLBACK:TaiwanOptionDaily:TXO; source_type=REAL_PROVIDER; notes=inputs/daily/2026-06-05/options.csv

### Fallback-Dependent Operator Fields
* source_id=options_csv; provider_source=FINMIND_FALLBACK:TaiwanOptionDaily:TXO; source_type=REAL_PROVIDER; operator_field=Tail Risk; canonical_field=tail_risk
* source_id=options_csv; provider_source=FINMIND_FALLBACK:TaiwanOptionDaily:TXO; source_type=REAL_PROVIDER; operator_field=BCD; canonical_field=bcd
* source_id=options_csv; provider_source=FINMIND_FALLBACK:TaiwanOptionDaily:TXO; source_type=REAL_PROVIDER; operator_field=Crash Probability; canonical_field=tail_risk

### Placeholder / Default-Like Fields
* field=nasdaq; reason=0.0 default-like value and no confirmed source
* field=sox; reason=0.0 default-like value and no confirmed source

### Non-Integrated Modules
* module=ETF Exit; status=not_integrated; notes=Reserved for future ETF Exit integration; no ETF exit logic applied.

### Operator Use Decision
* fallback provider data feeds top-level operator field(s): Tail Risk, BCD, Crash Probability
* default-like global-risk field(s) without confirmed source: nasdaq, sox
* required module(s) not integrated: ETF Exit

## Future ETF Exit Integration

- Enabled: `False`
- Status: `not_integrated`
- Notes: Reserved for future ETF Exit integration; no ETF exit logic applied.
