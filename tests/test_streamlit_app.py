from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")

SECTION_ORDER = (
    "What's Trending?",
    "AI Trend Summary",
    "Company Impact",
    "What to Watch",
    "Why Did It Move?",
    "Evidence",
)


def _run() -> AppTest:
    return AppTest.from_file(APP_PATH).run(timeout=20)


def _rendered(app: AppTest) -> str:
    """Page markup with the stylesheet block dropped.

    The <style> block names every hw-* class, so leaving it in would make
    substring and ordering assertions meaningless.
    """
    return "\n".join(item.value for item in app.markdown if "<style>" not in item.value)


class StreamlitAppTest(unittest.TestCase):
    def test_demo_dashboard_renders_required_sections(self) -> None:
        app = _run()

        self.assertEqual(len(app.exception), 0)
        rendered = _rendered(app)
        self.assertIn("Financial Trend Radar", rendered)
        self.assertIn("글로벌 금융 시그널을 한화 금융계열사의 시각으로 해석합니다", rendered)
        self.assertIn("PROTOTYPE", rendered)
        self.assertIn("SNAPSHOT MODE", rendered)

        positions = [rendered.index(title) for title in SECTION_ORDER]
        self.assertEqual(positions, sorted(positions))

        self.assertEqual(len(app.segmented_control), 1)
        self.assertEqual(len(app.segmented_control[0].options), 3)
        self.assertGreaterEqual(len(app.warning), 1)
        self.assertIn("SNAPSHOT DATA", app.warning[0].value)
        self.assertGreaterEqual(len(app.info), 1)
        self.assertIn("Snapshot Evidence", app.info[0].value)

        for company in ("한화생명", "한화투자증권", "한화자산운용"):
            self.assertIn(company, rendered)

    def test_stat_tiles_show_one_hero_and_full_metric_name(self) -> None:
        app = _run()
        rendered = _rendered(app)

        # The metric name is an eyebrow chip, not a value — so it is never truncated.
        self.assertIn("US Treasury 10Y", rendered)
        self.assertIn("미국 장기금리 급락", rendered)
        self.assertIn("-23 bp", rendered)
        self.assertIn("-2.2", rendered)
        self.assertIn("↓ DOWN", rendered)
        # Exactly one hero figure on the page.
        self.assertEqual(rendered.count("hw-tile--hero"), 1)

    def test_company_impact_is_rendered_before_evidence(self) -> None:
        app = _run()
        rendered = _rendered(app)
        self.assertLess(rendered.index("Company Impact"), rendered.index("Why Did It Move?"))
        self.assertLess(rendered.index("한화생명"), rendered.index("hw-ev-title"))

    def test_company_cards_expose_profile_factors(self) -> None:
        app = _run()
        # Count inside the card grid only: the same labels legitimately appear in
        # the section note and the AI-scope disclosure too.
        cards = next(item.value for item in app.markdown if 'class="hw-card"' in item.value)

        for label in ("영향 요인", "Transmission Paths", "Key Metrics to Watch", "Insight"):
            self.assertEqual(cards.count(label), 3)
        # Positive and negative factors share one list, separated by sign markers.
        self.assertEqual(cards.count("hw-sign--pos"), 4)
        self.assertEqual(cards.count("hw-sign--neg"), 6)
        self.assertIn("보유 채권 평가환경 개선", cards)
        self.assertIn("신규 재투자수익률 하락", cards)
        self.assertIn("HIGH", cards)
        self.assertIn("MIXED", cards)

    def test_ai_and_profile_provenance_is_labelled(self) -> None:
        app = _run()
        rendered = _rendered(app)

        # Legend names all four producers.
        for label in ("AI 생성", "Profile 기준", "Snapshot", "검색 선별"):
            self.assertIn(label, rendered)
        # Each card marks its AI-written and Profile-driven zones.
        self.assertEqual(rendered.count('hw-prov--ai">AI<'), 6)
        self.assertEqual(rendered.count('hw-prov--profile">PROFILE<'), 3)
        # The disclosure block states the analysis mode actually in use.
        self.assertIn("cached_llm_output", rendered)
        self.assertIn("AI가 생성하지 않는 것", rendered)
        self.assertIn("investment_advice: false", rendered)

    def test_icon_font_is_not_overridden_by_our_typography(self) -> None:
        app = _run()
        style = next(item.value for item in app.markdown if "<style>" in item.value)

        # A blanket [class*="st-"] font rule breaks Streamlit's Material Symbols
        # ligatures, which then render as literal text such as "arrow_down".
        self.assertNotIn('[class*="st-"]', style)
        self.assertIn('[data-testid="stIconMaterial"]', style)
        self.assertIn('"Material Symbols Rounded" !important', style)

    def test_streamlit_header_bar_is_hidden(self) -> None:
        app = _run()
        style = next(item.value for item in app.markdown if "<style>" in item.value)
        self.assertIn('[data-testid="stHeader"]', style)

    def test_switching_signals_updates_metrics_and_impacts(self) -> None:
        app = _run()

        app.segmented_control[0].set_value("VIX_SPIKE").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        rendered = _rendered(app)
        self.assertIn("CBOE Volatility Index (VIX)", rendered)
        self.assertIn("+10.8 pts", rendered)
        self.assertIn("투자자산 변동성", rendered)
        self.assertIn("NEGATIVE", rendered)

        app.segmented_control[0].set_value("USDKRW_MOVE").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        rendered = _rendered(app)
        self.assertIn("USD/KRW", rendered)
        self.assertIn("+32.4 KRW", rendered)
        self.assertIn("환헤지", rendered)

    def test_deselecting_the_segment_falls_back_to_the_first_signal(self) -> None:
        app = _run()

        # segmented_control is de-selectable; a None value must not blank the page.
        app.segmented_control[0].set_value(None).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        rendered = _rendered(app)
        self.assertIn("US Treasury 10Y", rendered)
        self.assertIn("한화생명", rendered)


if __name__ == "__main__":
    unittest.main()
