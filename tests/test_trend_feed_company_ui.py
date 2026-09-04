from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "app" / "trend_feed_app.py")
COMPANIES = (
    ("hanwha_life", "한화생명"),
    ("hanwha_investment", "한화투자증권"),
    ("hanwha_asset_management", "한화자산운용"),
)


def setUpModule() -> None:
    """Point the app at a missing live file so the default run is the fallback."""
    os.environ["GFR_LIVE_TRENDS_PATH"] = str(
        Path(__file__).resolve().parent / "fixtures" / "no_such_live_file.json"
    )


def tearDownModule() -> None:
    os.environ.pop("GFR_LIVE_TRENDS_PATH", None)


def _rendered(app: AppTest) -> str:
    body = "\n".join(item.value for item in app.markdown if "<style>" not in item.value)
    return re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "data:image/<logo>", body)


def _trend_payload(stamp: str) -> dict:
    """A minimal live trend payload whose articles the briefs can cite."""
    articles = [
        {
            "article_id": f"A{index:03d}",
            "title": f"기사 제목 {index}",
            "source": f"출처 {index}",
            "published_at": stamp,
            "url": f"https://example.com/{index}",
            "summary": "요약",
            "language": "ko" if index % 2 else "en",
            "watch_area": "rates_liquidity",
        }
        for index in range(5)
    ]
    return {
        "generated_at": stamp,
        "window_days": 7,
        "model": "test-model",
        "articles": articles,
        "trends": [
            {
                "trend_id": "trend_01",
                "title_ko": "전역 트렌드",
                "summary_ko": "요약",
                "why_it_matters_ko": "이유",
                "watch_next": ["관찰"],
                "article_ids": [item["article_id"] for item in articles],
                "related_business_tags": ["증권 리서치"],
            }
        ],
    }


def _company_briefs(stamp: str, **overrides) -> dict:
    payload = {
        "generated_at": stamp,
        "source_trends_generated_at": stamp,
        "model": "test-model",
        "status": "GENERATED",
        "companies": [
            {
                "company_id": company_id,
                "company_name": name,
                "weekly_summary_ko": f"{name} 주간 요약",
                "briefs": [
                    {
                        "trend_id": "trend_01",
                        "title_ko": f"{name} 브리핑 제목",
                        "situation_ko": "상황 설명",
                        "company_relevance_ko": "회사 관련성 설명",
                        "business_impact_ko": "사업 영향 설명",
                        "watch_next": ["후속 관찰 항목"],
                        "business_tags": ["증권 리서치"],
                        "evidence_article_ids": ["A000", "A001", "A002", "A003"],
                        "evidence_metrics": {"corroboration": "strong"},
                    }
                ],
                "monitoring_items": [
                    {
                        "trend_id": "trend_01",
                        "title_ko": f"{name} 모니터링 항목",
                        "relevance": "low",
                        "reason_ko": "모니터링 사유",
                        "business_tags": ["전사 전략"],
                        "evidence_article_ids": ["A000"],
                        "evidence_metrics": {"corroboration": "limited"},
                    }
                ],
            }
            for company_id, name in COMPANIES
        ],
    }
    payload.update(overrides)
    return payload


class CompanyIntelligenceUiTest(unittest.TestCase):
    """The section renders runtime briefs only; it never invents content."""

    def _run_with(self, briefs: dict | None, stamp: str) -> tuple[AppTest, str]:
        # The same stamp must reach both files: the loader treats any difference
        # between trends and briefs as stale.
        previous = os.environ.get("GFR_LIVE_TRENDS_PATH")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                live_path = Path(tmp) / "latest_trends.json"
                live_path.write_text(
                    json.dumps(_trend_payload(stamp), ensure_ascii=False), encoding="utf-8"
                )
                if briefs is not None:
                    (Path(tmp) / "latest_company_briefs.json").write_text(
                        json.dumps(briefs, ensure_ascii=False), encoding="utf-8"
                    )
                os.environ["GFR_LIVE_TRENDS_PATH"] = str(live_path)
                app = AppTest.from_file(APP_PATH).run(timeout=60)
                return app, _rendered(app)
        finally:
            if previous is None:
                os.environ.pop("GFR_LIVE_TRENDS_PATH", None)
            else:
                os.environ["GFR_LIVE_TRENDS_PATH"] = previous

    def _generated(self) -> tuple[AppTest, str]:
        stamp = datetime.now(timezone.utc).isoformat()
        return self._run_with(_company_briefs(stamp), stamp)

    def test_tabs_follow_the_required_company_order(self) -> None:
        app, rendered = self._generated()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual([tab.label for tab in app.tabs], [name for _, name in COMPANIES])
        self.assertIn("Company Intelligence", rendered)

    def test_each_tab_shows_the_weekly_summary_and_brief_fields(self) -> None:
        _, rendered = self._generated()

        self.assertEqual(rendered.count("gf-ci-summary"), 3)
        self.assertEqual(rendered.count("gf-brief-card"), 3)
        for _, name in COMPANIES:
            self.assertIn(f"{name} 주간 요약", rendered)
            self.assertIn(f"{name} 브리핑 제목", rendered)
        # Match the label markup: the fixture body text repeats these words.
        for label in ("회사 관련성", "사업 영향", "WATCH NEXT", "근거 기사"):
            self.assertEqual(rendered.count(f">{label}<"), 3)
        self.assertIn("상황 설명", rendered)
        self.assertIn("후속 관찰 항목", rendered)
        self.assertIn("증권 리서치", rendered)

    def test_corroboration_is_shown_as_a_natural_language_label(self) -> None:
        _, rendered = self._generated()

        self.assertIn("다수 출처로 확인", rendered)
        self.assertIn("제한적 근거", rendered)
        # The raw enum value must not reach the reader.
        self.assertNotIn(">strong<", rendered)
        self.assertNotIn(">limited<", rendered)

    def test_only_two_evidence_articles_show_before_expanding(self) -> None:
        app, rendered = self._generated()

        labels = [item.label for item in app.expander]
        self.assertEqual(labels.count("근거 기사 2건 더 보기"), 3)
        # Count inside the Company Intelligence section only; the trend hero
        # above renders its own evidence rows.
        section = rendered[rendered.index("gf-ci-head") :]
        # Per tab: two inline rows plus the two revealed by the expander.
        self.assertEqual(section.count("gf-ev-meta"), 3 * 4)

    def test_monitoring_items_are_separated_from_main_briefs(self) -> None:
        _, rendered = self._generated()

        self.assertEqual(rendered.count("Main Brief"), 3)
        self.assertEqual(rendered.count("gf-monitor-title"), 3)
        self.assertIn("모니터링 사유", rendered)
        for _, name in COMPANIES:
            self.assertIn(f"{name} 모니터링 항목", rendered)

    def test_failed_generation_states_the_cause_once(self) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(
            stamp,
            status="NOT_GENERATED",
            companies=[],
            error={
                "type": "PrerequisiteError",
                "message": "관련성 분류 상태가 CLASSIFIED가 아닙니다.",
            },
        )
        app, rendered = self._run_with(briefs, stamp)

        self.assertEqual(len(app.exception), 0)
        # Stated once at section level rather than repeated in all three tabs.
        self.assertEqual(rendered.count("관련성 분류 상태가 CLASSIFIED가 아닙니다."), 1)
        self.assertEqual(rendered.count("사유는 위 안내를 확인해 주세요."), 3)
        self.assertEqual(rendered.count("gf-brief-card"), 0)

    def test_timestamp_mismatch_is_reported_and_blocks_briefs(self) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        briefs["source_trends_generated_at"] = "2020-01-01T00:00:00+00:00"
        app, rendered = self._run_with(briefs, stamp)

        self.assertEqual(len(app.exception), 0)
        self.assertIn("기준 시각이 일치하지 않습니다", rendered)
        self.assertEqual(rendered.count("gf-brief-card"), 0)

    def test_missing_brief_file_explains_how_to_recover(self) -> None:
        app, rendered = self._run_with(None, datetime.now(timezone.utc).isoformat())

        self.assertEqual(len(app.exception), 0)
        self.assertIn("회사별 Brief 파일이 없습니다", rendered)
        self.assertEqual(len(app.tabs), 3)
        self.assertEqual(rendered.count("gf-brief-card"), 0)

    def test_a_company_missing_from_the_result_says_so_in_its_own_tab(self) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        briefs["companies"] = [
            company for company in briefs["companies"] if company["company_id"] != "hanwha_life"
        ]
        app, rendered = self._run_with(briefs, stamp)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.tabs), 3)
        self.assertIn("생성 결과에 한화생명 데이터가 없습니다.", rendered)
        # The other two still render their briefs.
        self.assertEqual(rendered.count("gf-brief-card"), 2)

    def test_demo_data_never_shows_company_briefs(self) -> None:
        app = AppTest.from_file(APP_PATH).run(timeout=60)
        rendered = _rendered(app)

        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "DEMO 트렌드에는 실제 회사별 Intelligence Brief를 표시하지 않습니다.", rendered
        )
        self.assertEqual(rendered.count("gf-brief-card"), 0)


if __name__ == "__main__":
    unittest.main()
