# BCD Independence Audit

## Executive result

BCD is now calculated only from independent breadth, leadership, diffusion, OTC/small-mid, and turnover concentration inputs. If those inputs are incomplete, the production payload sets `bcd_status = INCOMPLETE`, `bcd = null`, and records missing components rather than copying Tail Risk, an options CSV value, or any other proxy.

## Required input sources

| Required input | Production source path | Notes |
| --- | --- | --- |
| `breadth_history` | Snapshot canonical row → `BCDInput.breadth_history` | Parsed into `BreadthBar` history. |
| `main7_returns` | Snapshot canonical row → `BCDInput.main7_returns` | Leadership return map. |
| `main7_weights` | Snapshot canonical row → `BCDInput.main7_weights` | Leadership weight map. |
| `sector_diffusion` | Snapshot canonical row fields `sector_returns` and `sector_above_ma20` | Both are required for complete sector diffusion. |
| `otc_return_pct` | Snapshot canonical row → `BCDInput.otc_return_pct` | OTC / small-mid return divergence. |
| `small_mid_breadth` | Snapshot canonical row `small_mid_advancing_issues` + `small_mid_declining_issues` | Converted to a `BreadthBar`. |
| `turnover_concentration_topn` | Snapshot canonical row → `BCDInput.turnover_concentration_topn` | Top-N turnover concentration. |

## Complete lineage report

| Field written | Source file | Function / method | Line number | Upstream dependency |
| --- | --- | --- | ---: | --- |
| `BCDResult.final_score` | `src/tdt_rm/bcd.py` | `score_bcd` | 200 | Sum of component scores only when `_missing_required_inputs` is empty and dependency guard passes. |
| `bcd` | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 413-414 | `bcd_result.final_score` from `_bcd_result_from_snapshot`; never `tail_risk` or `options_csv.bcd`. |
| `payload["bcd"]` | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 481 | `_round_optional(bcd)`, preserving `null` when incomplete. |
| `payload["scores"]["BCD"]` | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 504-510 | Same `_round_optional(bcd)` value as top-level payload. |
| `traces.bcd` | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 512-519 | `BCDResult.as_dict()` audit trace. |
| `bcd_status`, `bcd_data_completeness`, `bcd_missing_components`, `bcd_source_dependencies`, `bcd_calculation_version` | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 481-486 | `BCDResult` audit fields. |
| `bcd` in price-only payload | `src/tdt_rm/daily_runner.py` | `build_daily_payload` | 234-235, 311 | `_price_only_bcd_result` returns `INCOMPLETE`, so the written BCD is `null`; no synthetic price-only BCD is emitted. |
| `bcd` in CP input | `src/tdt_rm/daily_runner.py` | `build_daily_payload_from_snapshot` | 428-434 | Passes `None` through when BCD is incomplete. |
| BCD decision thresholds | `src/tdt_rm/decision_matrix.py` | `resolve_five_light_signal` | 240, 253, 265 | Rules evaluate BCD thresholds only when `data.bcd is not None`. |
| BCD CP contribution | `src/tdt_rm/crash_probability.py` | `score_crash_probability` | 77-112 | Missing BCD is excluded with `input_status.bcd = missing_excluded_from_cp_contribution`. |
| Snapshot provider category fields | `src/tdt_rm/daily_providers.py` | module constants / assembler inputs | 44-86 | `options` and `scores` categories no longer include `bcd`; `options_csv.bcd` cannot write `snapshot.canonical_row["bcd"]`. |
| Daily report disclosure | `src/tdt_rm/daily_runner.py` | `render_user_daily_report` | 638-640 | Report prints BCD value, status, missing inputs, and BCD explanation lines. |
| Audit artifact writer | `src/tdt_rm/daily_runner.py` | `write_bcd_audit_artifacts` | 982-1029 | Writes BCD trace JSON/CSV and this independence audit Markdown. |

No production assignment path copies `tail_risk → bcd`. No production provider category accepts `options_csv.bcd → snapshot.bcd`.

## Calculation path

1. `DailySnapshotAssembler` collects only independent BCD inputs from breadth, leadership, sector/diffusion, OTC/small-mid, and margin/turnover sources. The options and scores provider categories exclude BCD.
2. `build_daily_payload_from_snapshot` calls `_bcd_result_from_snapshot`.
3. `_bcd_result_from_snapshot` maps the required independent inputs into `BCDInput`.
4. `score_bcd` runs component scoring and explicit completeness validation.
5. If any required input is missing, `score_bcd` returns `final_score=None`, `data_quality_status="INCOMPLETE"`, a completeness score, missing components, dependencies, and version.
6. Downstream CP and decision code accepts `None` without fabricating a BCD threshold or CP contribution.

## Completeness score

Completeness is calculated as:

```text
present_required_inputs / 7
```

The seven required inputs are `breadth_history`, `main7_returns`, `main7_weights`, `sector_diffusion`, `otc_return_pct`, `small_mid_breadth`, and `turnover_concentration_topn`.

## Dependency graph

```text
breadth_history ─┐
main7_returns ──┤
main7_weights ──┤
sector_diffusion ├─> BCDInput -> score_bcd -> bcd / scores.BCD / traces.bcd
otc_return_pct ─┤
small_mid_breadth ─┤
turnover_concentration_topn ─┘

tail_risk ─X forbidden as BCD dependency
options_csv.bcd ─X forbidden as snapshot or BCD dependency
```

## Comparison against tail_risk

The independence guard fails execution when `abs(bcd - tail_risk) < 0.0001` persists for more than three consecutive trading days. The daily snapshot path appends the current day to any supplied BCD/Tail Risk comparison history and calls the guard before writing the payload.

When BCD is incomplete, the comparison is not treated as a valid equality because `bcd = null`.
