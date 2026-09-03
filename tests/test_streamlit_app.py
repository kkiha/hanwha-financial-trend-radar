from __future__ import annotations

import re
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")

SECTION_ORDER = (
    "What's Trending?",
    "AI Brief",
    "Business Lens",
    "Key Watchpoints",
    "주요 관련 요인",
    "Evidence",
)


def _run() -> AppTest:
    return AppTest.from_file(APP_PATH).run(timeout=20)


def _rendered(app: AppTest) -> str:
    """Page markup with the stylesheet and the inlined logo dropped.

    The <style> block names every hw-* class, and the base64 logo is a 28KB
    alphabet soup that happens to contain words like "Evidence" — either would
    make substring and ordering assertions meaningless.
    """
    body = "\n".join(item.value for item in app.markdown if "<style>" not in item.value)
    return re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "data:image/<logo>", body)


class StreamlitAppTest(unittest.TestCase):
    def test_demo_dashboard_renders_required_sections(self) -> None:
        app = _run()

        self.assertEqual(len(app.exception), 0)
        rendered = _rendered(app)
        self.assertIn("Financial Trend Radar", rendered)
        self.assertIn("업무 관점별 확인 항목을 제시합니다", rendered)
        self.assertIn("PROTOTYPE", rendered)
        self.assertIn("SNAPSHOT MODE", rendered)

        # Match the heading markup, not the bare word: "Evidence" also appears in
        # the product subtitle.
        positions = [rendered.index(f'hw-section">{title}') for title in SECTION_ORDER]
        self.assertEqual(positions, sorted(positions))

        self.assertEqual(len(app.segmented_control), 1)
        self.assertEqual(len(app.segmented_control[0].options), 3)
        self.assertGreaterEqual(len(app.warning), 1)
        self.assertIn("Representative Snapshot Dataset", app.warning[0].value)
        self.assertGreaterEqual(len(app.info), 1)
        self.assertIn("Snapshot Dataset", app.info[0].value)

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

    def test_business_lens_is_rendered_before_evidence(self) -> None:
        app = _run()
        rendered = _rendered(app)
        self.assertLess(
            rendered.index('hw-section">Business Lens'),
            rendered.index('hw-section">주요 관련 요인'),
        )
        self.assertLess(rendered.index("한화생명"), rendered.index("hw-ev-title"))

    def test_business_lens_cards_show_check_points_and_metrics(self) -> None:
        app = _run()
        # Count inside the card grid only: the same labels legitimately appear in
        # the section note and the AI-scope disclosure too.
        cards = next(item.value for item in app.markdown if 'class="hw-card"' in item.value)

        for label in ("Check Points", "Key Metrics to Watch", "AI Brief"):
            self.assertEqual(cards.count(label), 3)
        for lens in ("보험 관점", "증권 관점", "자산운용 관점"):
            self.assertIn(lens, cards)
        self.assertIn("채권 운용", cards)
        self.assertIn("운용수익률", cards)

    def test_impact_verdicts_are_not_shown_on_screen(self) -> None:
        app = _run()
        rendered = _rendered(app)

        # The prototype offers check points, not an automated impact judgement.
        for verdict in ("HIGH", "MEDIUM", "LOW", "POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"):
            self.assertNotIn(verdict, rendered)
        for phrase in ("Positive Factors", "Negative Factors", "영향 요인", "Company Impact"):
            self.assertNotIn(phrase, rendered)
        # Profile still carries those fields; they are simply not rendered.
        self.assertIn("판정하지 않습니다", rendered)

    def test_ai_and_profile_provenance_is_labelled(self) -> None:
        app = _run()
        rendered = _rendered(app)

        # Legend names all four producers.
        for label in ("AI 생성", "Profile 기준", "Snapshot", "검색 선별"):
            self.assertIn(label, rendered)
        # Each card marks its AI-written summary and Brief.
        self.assertEqual(rendered.count('hw-prov--ai">AI<'), 6)
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
        self.assertIn("Fund Flow", rendered)

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
