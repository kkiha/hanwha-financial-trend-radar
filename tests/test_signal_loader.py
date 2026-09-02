from __future__ import annotations

import unittest

from rag_finance.signal.loader import load_signal


class SignalLoaderTest(unittest.TestCase):
    def test_loads_snapshot_signal_with_explicit_notice(self) -> None:
        signal = load_signal("data/sample_signals/us10y_drop.json")
        self.assertEqual(signal.signal_id, "US10Y_SAMPLE")
        self.assertEqual(signal.category, "interest_rate")
        self.assertEqual(signal.data_mode, "demo_snapshot")
        self.assertTrue(signal.snapshot_notice)


if __name__ == "__main__":
    unittest.main()
