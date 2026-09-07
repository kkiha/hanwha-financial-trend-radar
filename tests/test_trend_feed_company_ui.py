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


def _view(app: AppTest) -> dict:
    return json.loads(app.get("bidi_component")[0].proto.json)


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
    """The component receives validated runtime data; browser checks cover its DOM."""

    def _run_with(self, briefs, stamp):
        previous = os.environ.get("GFR_LIVE_TRENDS_PATH")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "latest_trends.json"
                path.write_text(json.dumps(_trend_payload(stamp)), encoding="utf-8")
                if briefs is not None:
                    (Path(tmp) / "latest_company_briefs.json").write_text(json.dumps(briefs), encoding="utf-8")
                os.environ["GFR_LIVE_TRENDS_PATH"] = str(path)
                app = AppTest.from_file(APP_PATH).run(timeout=60)
                self.assertEqual(len(app.exception), 0)
                return app, _view(app)
        finally:
            if previous is None:
                os.environ.pop("GFR_LIVE_TRENDS_PATH", None)
            else:
                os.environ["GFR_LIVE_TRENDS_PATH"] = previous

    def _generated(self):
        stamp = datetime.now(timezone.utc).isoformat()
        return self._run_with(_company_briefs(stamp), stamp)

    def test_company_order_and_full_brief_fields_are_preserved(self):
        _, view = self._generated()
        companies = view["company_intelligence"]["companies"]
        self.assertEqual([c["company_name"] for c in companies], [n for _, n in COMPANIES])
        for c in companies:
            self.assertEqual(c["display_summary"], c["company_name"] + " 주간 요약")
            b = c["briefs"][0]
            self.assertEqual(b["situation_ko"], "상황 설명")
            self.assertEqual(b["company_relevance_ko"], "회사 관련성 설명")
            self.assertEqual(b["business_impact_ko"], "사업 영향 설명")
            self.assertEqual(b["watch_next"], ["후속 관찰 항목"])
            self.assertEqual(b["business_tags"], ["증권 리서치"])

    def test_corroboration_and_all_evidence_reach_the_component(self):
        _, view = self._generated()
        for c in view["company_intelligence"]["companies"]:
            self.assertEqual(c["briefs"][0]["corroboration_label"], "다수 출처로 확인")
            self.assertEqual(len(c["briefs"][0]["evidence_articles"]), 4)
            self.assertEqual(c["monitoring_items"][0]["corroboration_label"], "제한적 근거")
            self.assertEqual(len(c["monitoring_items"][0]["evidence_articles"]), 1)

    def test_runtime_headline_is_retained_without_schema_changes(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        b = briefs["companies"][0]["briefs"][0]
        b.pop("title_ko")
        b["headline_ko"] = "실제 생성 브리핑 <제목>"
        _, view = self._run_with(briefs, stamp)
        self.assertEqual(view["company_intelligence"]["companies"][0]["briefs"][0]["headline_ko"], b["headline_ko"])

    def test_main_monitoring_and_empty_summary_rules(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        life, investment, asset = briefs["companies"]
        life["weekly_summary_ko"] = " "
        life["monitoring_items"] = []
        investment["briefs"] = []
        asset["briefs"] = []
        asset["monitoring_items"] = []
        asset["weekly_summary_ko"] = "과거 요약"
        _, view = self._run_with(briefs, stamp)
        a,b,c = view["company_intelligence"]["companies"]
        self.assertEqual(a["display_summary"], "이번 주 1건의 Main Brief와 0건의 Monitoring 이슈가 확인되었습니다.")
        self.assertIn("1건의 Monitoring 이슈를 계속 관찰", b["display_summary"])
        self.assertIn("추가 브리핑이 필요한 수준의 이슈는 확인되지 않았습니다.", c["display_summary"])
        self.assertNotIn("과거 요약", c["display_summary"])
        self.assertEqual([len(x["briefs"]) for x in (a,b,c)], [1,0,0])

    def test_multiple_items_use_existing_counts(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        life = briefs["companies"][0]
        life["weekly_summary_ko"] = ""
        life["briefs"] *= 2
        life["monitoring_items"] *= 3
        _, view = self._run_with(briefs, stamp)
        self.assertIn("2건의 Main Brief와 3건의 Monitoring", view["company_intelligence"]["companies"][0]["display_summary"])

    def test_untrusted_prose_is_data_not_executable_component_markup(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        text = "<img src=x onerror=alert(1)>"
        briefs["companies"][0]["weekly_summary_ko"] = text
        app, view = self._run_with(briefs, stamp)
        self.assertEqual(view["company_intelligence"]["companies"][0]["display_summary"], text)
        self.assertNotIn(text, app.get("bidi_component")[0].proto.html_content)
        self.assertNotIn(text, app.get("bidi_component")[0].proto.js_content)

    def test_failed_generation_has_shared_reason_and_no_empty_success(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp, status="NOT_GENERATED", companies=[], error={"type":"PrerequisiteError","message":"관련성 분류 상태가 CLASSIFIED가 아닙니다."})
        _, view = self._run_with(briefs, stamp)
        ci = view["company_intelligence"]
        self.assertIn("CLASSIFIED", ci["reason"])
        for c in ci["companies"]:
            self.assertEqual(c["status"], "UNAVAILABLE")
            self.assertIn("사유는 위 안내", c["display_summary"])
            self.assertEqual(c["briefs"], [])

    def test_timestamp_mismatch_blocks_stale_briefs(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        briefs["source_trends_generated_at"] = "2020-01-01T00:00:00+00:00"
        _, view = self._run_with(briefs, stamp)
        self.assertIn("기준 시각이 일치하지 않습니다", view["company_intelligence"]["reason"])
        self.assertTrue(all(not c["briefs"] for c in view["company_intelligence"]["companies"]))

    def test_missing_brief_file_explains_recovery(self):
        _, view = self._run_with(None, datetime.now(timezone.utc).isoformat())
        self.assertIn("회사별 Brief 파일이 없습니다", view["company_intelligence"]["reason"])
        self.assertEqual(len(view["company_intelligence"]["companies"]),3)

    def test_missing_company_does_not_discard_successful_companies(self):
        stamp = datetime.now(timezone.utc).isoformat()
        briefs = _company_briefs(stamp)
        briefs["companies"] = briefs["companies"][1:]
        _, view = self._run_with(briefs, stamp)
        companies=view["company_intelligence"]["companies"]
        self.assertIn("생성 결과에 한화생명 데이터가 없습니다.",companies[0]["display_summary"])
        self.assertEqual([len(c["briefs"]) for c in companies],[0,1,1])

    def test_demo_never_exposes_real_company_briefs(self):
        app=AppTest.from_file(APP_PATH).run(timeout=60)
        view=_view(app)
        self.assertIn("DEMO 트렌드에는 실제 회사별 Intelligence Brief를 표시하지 않습니다.",view["company_intelligence"]["reason"])
        self.assertTrue(all(not c["briefs"] for c in view["company_intelligence"]["companies"]))


if __name__ == "__main__":
    unittest.main()
