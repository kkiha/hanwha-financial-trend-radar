from __future__ import annotations

import re
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "app" / "trend_feed_app.py")


def _run() -> AppTest:
    return AppTest.from_file(APP_PATH).run(timeout=30)


def _rendered(app: AppTest) -> str:
    body = "\n".join(item.value for item in app.markdown if "<style>" not in item.value)
    return re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "data:image/<logo>", body)


class TrendFeedAppTest(unittest.TestCase):
    def test_app_renders_without_exceptions(self) -> None:
        app = _run()
        self.assertEqual(len(app.exception), 0)

        rendered = _rendered(app)
        self.assertIn("Hanwha Global Finance Radar", rendered)
        self.assertIn("글로벌 금융 흐름을 압축하는 AI 트렌드 브리핑", rendered)
        self.assertIn("최신 데이터 불러오기", [button.label for button in app.button])

    def test_summary_strip_reports_counts_from_the_payload(self) -> None:
        rendered = _rendered(_run())
        self.assertIn("최근 7일", rendered)
        self.assertIn("수집 기사", rendered)
        self.assertIn("고유 출처", rendered)
        self.assertIn("Emerging Trends", rendered)
        self.assertIn("18건", rendered)  # fallback article count

    def test_hero_and_two_cards_are_rendered_with_ranks(self) -> None:
        rendered = _rendered(_run())
        self.assertEqual(rendered.count('class="gf-hero"'), 1)
        self.assertEqual(rendered.count('class="gf-card"'), 2)
        for rank in ("01", "02", "03"):
            self.assertIn(f'class="gf-rank">{rank}<', rendered)

    def test_every_trend_shows_computed_metrics_and_a_chart(self) -> None:
        rendered = _rendered(_run())
        self.assertEqual(rendered.count("48시간 집중도"), 3)
        # Match the metric label markup: "관련 기사 타임라인" also uses the phrase.
        self.assertEqual(rendered.count('class="gf-metric-label">관련 기사<'), 3)
        self.assertGreaterEqual(rendered.count('class="gf-chart"'), 3)

    def test_demo_status_and_synthetic_evidence_are_labelled(self) -> None:
        rendered = _rendered(_run())
        self.assertIn("gf-status--demo", rendered)
        self.assertIn(">DEMO<", rendered)
        # Fallback articles carry no URL, so they must be badged, not linked.
        self.assertIn("합성", rendered)
        self.assertNotIn("<a href=\"\"", rendered)

    def test_detail_selector_and_methodology_are_present(self) -> None:
        app = _run()
        self.assertEqual(len(app.radio), 1)
        self.assertEqual(len(app.radio[0].options), 3)

        rendered = _rendered(app)
        self.assertIn("Trend Detail", rendered)
        self.assertIn("관련 기사 타임라인", rendered)
        self.assertIn("Watch Next", rendered)
        self.assertIn("기사 본문은 크롤링하지 않습니다", rendered)
        self.assertIn("투자 추천", rendered)

    def test_switching_trend_detail_changes_the_timeline(self) -> None:
        app = _run()
        first = _rendered(app)
        app.radio[0].set_value(app.radio[0].options[1]).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(first, _rendered(app))

    def test_icon_font_and_header_chrome_are_handled(self) -> None:
        app = _run()
        style = next(item.value for item in app.markdown if "<style>" in item.value)
        self.assertNotIn('[class*="st-"]', style)
        self.assertIn('"Material Symbols Rounded" !important', style)
        self.assertIn('[data-testid="stHeader"]', style)


if __name__ == "__main__":
    unittest.main()
