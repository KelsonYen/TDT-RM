# TDT-RM V5.1.4 Backtest Calibration Patch

Author: Dr. Yen  
Model: TDT-RM V5.1.4 Backtest Calibration Patch  
Generated at: 2026-06-02 15:27  
Version status: Backtest Calibration Version

V5.1.4 preserves the six core outputs (`MHS`, `TCWRS`, `ETI-5`, `Tail Risk`, `BCD`, and `Crash Probability`), the crash-probability formula, and the original five-light exposure bands. The patch calibrates backtests without resetting core weights or adding complex indicators.

## Calibration changes

1. **ETI-5 availability controls**
   - ETI-5 components must be marked unavailable when source data is missing.
   - Price-only backtests may proxy only ETI-1 (index below 20MA).
   - Available component count controls the ETI cap: 1-2 available components cap at 2, 3 available components cap at 3, and 4-5 available components score normally.
   - If fewer than three ETI components are available, ETI-5 cannot independently create a red light.

2. **Red-light confirmation**
   - Red remains valid for `TCWRS >= 76`.
   - ETI-driven red requires TCWRS confirmation: `ETI-5 >= 4 AND TCWRS >= 41`, or `TCWRS >= 61 AND ETI-5 >= 3`.
   - `ETI-5 >= 4 AND TCWRS < 41` is downgraded to orange.
   - Crash Probability cannot create red by itself, but `CP >= 55` is recorded as auxiliary red confirmation.

3. **Orange-light expansion**
   - Orange now absorbs the calibrated mid/high-risk cases previously over-promoted to red, including strong ETI with weak TCWRS, tail-risk/BCD confirmation with TCWRS and ETI support, and `TCWRS 61-75 AND ETI-5 >= 2`.

4. **Bear Trend Filter**
   - The filter is not included in TCWRS.
   - It floors the five-light signal at Yellow, Strengthened Yellow, or Orange when slow-bear trend conditions accumulate.

5. **Signal stability**
   - Backtest scripts apply a three-session red lock, require two non-red sessions to clear red, and prevent Red-to-Green jumps.

6. **False-positive analysis**
   - Backtest CSV output now includes forward 5D/10D/20D/40D/60D max-drawdown fields, false-positive flags for 20D/40D/60D, and delayed-valid-signal tagging.
