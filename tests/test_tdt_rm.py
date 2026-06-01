import unittest

from tdt_rm import ModelInput, backtest, determine_bcd_state, evaluate


class TdtRmDecisionTests(unittest.TestCase):
    def test_red_light_from_tcwrs(self):
        output = evaluate(ModelInput(date="2026/05/01", tcwrs=76, mhs=20, eti5_total=0, tail_risk=20, bcd=10))
        self.assertEqual(output.signal, "紅燈")
        self.assertEqual(output.regime_state, "Crash")

    def test_bcd_restricted_caps_score_and_blocks_orange_upgrade(self):
        item = ModelInput(
            date="2026/05/02",
            tcwrs=41,
            mhs=50,
            eti5_total=2,
            tail_risk=30,
            bcd=80,
            taiex=19_900,
            ma20=20_000,
            ma60=19_000,
        )
        state, score, can_upgrade = determine_bcd_state(item)
        output = evaluate(item)
        self.assertEqual(state, "restricted")
        self.assertEqual(score, 50)
        self.assertFalse(can_upgrade)
        self.assertEqual(output.signal, "黃燈強化")

    def test_backtest_reports_drawdown(self):
        inputs = [
            ModelInput(date="2026/05/01", tcwrs=10, mhs=20, eti5_total=0, tail_risk=10, bcd=10, close=100),
            ModelInput(date="2026/05/02", tcwrs=45, mhs=20, eti5_total=2, tail_risk=20, bcd=20, close=90),
            ModelInput(date="2026/05/03", tcwrs=80, mhs=20, eti5_total=4, tail_risk=20, bcd=20, close=81),
        ]
        summary = backtest(inputs)
        self.assertLess(summary.max_drawdown, 0)
        self.assertEqual(summary.worst_drawdown_date, "2026/05/03")
        self.assertEqual(summary.signal_counts["紅燈"], 1)


if __name__ == "__main__":
    unittest.main()
