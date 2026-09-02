from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class StreamlitAppTest(unittest.TestCase):
    def test_demo_dashboard_renders_required_sections(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
        app = AppTest.from_file(str(app_path)).run(timeout=20)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual([item.value for item in app.title], ["Hanwha Financial Trend Radar"])
        self.assertEqual(
            [item.value for item in app.subheader],
            ["What's Trending?", "Why Did It Move?", "Company Impact"],
        )
        self.assertEqual(len(app.metric), 4)
        self.assertEqual(app.metric[0].value, "US Treasury 10Y")
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(len(app.selectbox[0].options), 3)
        self.assertGreaterEqual(len(app.warning), 1)
        self.assertIn("SNAPSHOT DATA", app.warning[0].value)
        self.assertGreaterEqual(len(app.info), 1)
        self.assertIn("Snapshot Evidence", app.info[0].value)

        markdown_values = [item.value for item in app.markdown]
        self.assertEqual(markdown_values.count("[Snapshot Evidence URL](demo://interest_rate/IR_DEMO_001)"), 1)
        for company in ("한화생명", "한화투자증권", "한화자산운용"):
            self.assertIn(f"### {company}", markdown_values)

        app.selectbox[0].select("VIX_SPIKE").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, "CBOE Volatility Index (VIX)")
        self.assertEqual(app.metric[1].value, "+10.8 pts")
        self.assertIn(
            "[Snapshot Evidence URL](demo://volatility/VOL_DEMO_001)",
            [item.value for item in app.markdown],
        )

        app.selectbox[0].select("USDKRW_MOVE").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, "USD/KRW")
        self.assertEqual(app.metric[1].value, "+32.4 KRW")
        self.assertIn(
            "[Snapshot Evidence URL](demo://fx/FX_DEMO_001)",
            [item.value for item in app.markdown],
        )


if __name__ == "__main__":
    unittest.main()
