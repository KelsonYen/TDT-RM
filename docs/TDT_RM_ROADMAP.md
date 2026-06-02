# TDT-RM Roadmap

This roadmap reflects the repository's current implementation state and the requested staged path toward a formal candidate release. It is documentation only and does not alter model logic.

## Phase 1 — Current completed components

### Completed

- TCWRS core scorer with eight auditable factors and aggregate score.
- ETI-5 scorer with component traces and V5.1.4 data-availability caps.
- Crash Probability auxiliary score using TCWRS, ETI-5, Tail Risk, and BCD inputs.
- Five-light decision matrix with exposure limits and trace output.
- Bear Trend Filter as a non-downgrading slow-bear signal floor.
- CAL core scorer as an acute-crash signal floor.
- Generic dependency-free historical backtest framework.
- 2022 bear-market scenario backtest script and validation script.
- 2020 COVID crash stress-test script and comparison report tooling.
- Market Data Ingestion Layer for rows/CSVs, aliases, validation, completeness, schema output, and backtest bridging.
- Performance reporting module and script.
- Unit and scenario-support tests covering current implemented modules.

### Phase 1 gaps to track

- Tail Risk, BCD, and MHS are not standalone scorer modules.
- Market Data Downloader is not implemented.
- CAL is not wired into current scenario scripts.
- ETF Exit integration is not implemented.
- Daily production workflow is not packaged as a single runnable command.

## Phase 2 — Daily production workflow

### Goals

- Convert existing scoring modules into a repeatable daily operating flow.
- Produce a single auditable daily signal packet.
- Preserve model traceability and data-completeness status.

### Proposed work items

1. Add a daily runner entry point that:
   - loads a daily canonical row or CSV;
   - validates market data;
   - scores TCWRS, ETI-5, Crash Probability, Bear Trend, and CAL when inputs exist;
   - resolves the five-light signal;
   - writes a JSON/Markdown daily report.
2. Define a daily run manifest containing:
   - run date/time;
   - data source identifier;
   - data status;
   - package version or commit SHA;
   - scoring config;
   - output artifact paths.
3. Move script-level stability/red-lock logic into a documented reusable module if it is production policy.
4. Add daily workflow tests using deterministic fixture data.
5. Document operational handling for missing fields, holidays, partial sessions, and delayed data.

### Exit criteria

- One command can generate a complete daily signal report from canonical input.
- The report includes model scores, final signal, exposure limit, matched rule, and trace output.
- Missing data behavior is deterministic and documented.

## Phase 3 — Real market data integration

### Goals

- Replace embedded/provisional data paths with real data adapters.
- Keep downloader/provider code separated from scoring logic.
- Preserve the current vendor-neutral ingestion boundary.

### Proposed work items

1. Define provider interfaces for:
   - TAIEX OHLCV and turnover;
   - market breadth;
   - foreign investor spot/futures/options activity;
   - USD/TWD FX;
   - margin balance and retail leverage;
   - SOX, Nasdaq, VIX, and other external risk inputs;
   - ETF-specific price/holding data if needed later.
2. Implement a Market Data Downloader layer that writes canonical rows consumable by `market_data.py`.
3. Create source-to-canonical field mapping documentation.
4. Add downloader fixture tests with mocked responses or static files.
5. Add data-quality checks for freshness, monotonic dates, duplicate rows, nulls, and stale market holidays.
6. Re-run 2022 and COVID validations with real-data enriched fields rather than close-only proxies.

### Exit criteria

- Real-data snapshots can be downloaded or loaded into the ingestion layer without modifying model scorers.
- Each required model field has a documented source and transformation rule.
- Data-quality failures stop or downgrade production output according to documented policy.

## Phase 4 — ETF Exit integration

### Goals

- Convert model signals into ETF-specific exit and risk-management decisions.
- Keep portfolio policy separate from core model scoring.

### Proposed work items

1. Define ETF Exit inputs:
   - ETF identifier;
   - current position/exposure;
   - ETF price and liquidity data;
   - benchmark/TAIEX signal packet;
   - optional ETF-specific trend or tracking-error fields.
2. Define ETF Exit outputs:
   - action (`hold`, `reduce`, `exit`, `re-enter`, or equivalent);
   - target exposure;
   - execution urgency;
   - rationale and trace;
   - constraints or warnings.
3. Map five-light signals to ETF exposure policies.
4. Decide whether ETI-5, CAL, or Red lock can force immediate ETF actions.
5. Add ETF Exit backtest hooks and scenario fixtures.
6. Document user-facing ETF Exit reports.

### Exit criteria

- ETF Exit decisions are generated from model signal packets without changing core scorers.
- ETF-specific policy is tested independently from TCWRS/ETI-5/CP scoring.
- Reports explain both the market-risk signal and ETF action rationale.

## Phase 5 — Formal Candidate release

### Goals

- Stabilize interfaces, documentation, tests, and acceptance gates for a candidate release.
- Ensure all implemented components are auditable and reproducible.

### Proposed work items

1. Freeze public API boundaries for:
   - TCWRS;
   - ETI-5;
   - Crash Probability;
   - decision matrix;
   - Bear Trend Filter;
   - CAL;
   - ingestion;
   - backtest/stress-test/reporting;
   - ETF Exit if included.
2. Produce formal documentation:
   - architecture;
   - daily runbook;
   - data-source mapping;
   - output schemas;
   - model limitations;
   - validation protocol.
3. Consolidate duplicate script helpers into reusable package modules.
4. Add acceptance-test bundles for:
   - unit tests;
   - 2022 bear-market validation;
   - 2020 COVID stress validation;
   - real-data ingestion smoke test;
   - daily report generation;
   - ETF Exit policy if included.
5. Generate a release manifest containing:
   - version;
   - commit SHA;
   - test results;
   - generated validation artifacts;
   - known limitations.
6. Review and retire stale generated artifacts or clearly mark them as historical outputs.

### Exit criteria

- A clean checkout can run documented tests and regenerate candidate validation artifacts.
- Documentation matches current public APIs and scripts.
- Known limitations are explicit and accepted for candidate release.
- No model-logic changes are required during release packaging.
