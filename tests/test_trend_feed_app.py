from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from app.briefing_view import prepare_view, refresh_feedback, safe_url

ROOT=Path(__file__).resolve().parents[1]
APP_PATH=str(ROOT / "app/trend_feed_app.py")


def _run():
    return AppTest.from_file(APP_PATH).run(timeout=30)


def _view(app):
    return json.loads(app.get("bidi_component")[0].proto.json)


class TrendFeedAppTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"GFR_LIVE_TRENDS_PATH":str(ROOT/"tests/fixtures/no_such_live_file.json")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_app_mounts_live_component_without_exceptions(self):
        app=_run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.get("bidi_component")),1)
        self.assertIn("최신 데이터 불러오기",app.get("bidi_component")[0].proto.html_content)

    def test_summary_counts_come_from_loader(self):
        view=_view(_run())
        self.assertEqual(view["window_days"],7)
        self.assertEqual(view["stats"]["article_count"],18)
        self.assertEqual(len(view["trends"]),3)
        self.assertEqual([t["rank"] for t in view["trends"]],[1,2,3])

    def test_detail_metrics_and_all_articles_are_available(self):
        view=_view(_run())
        for trend in view["trends"]:
            self.assertEqual(trend["article_count"],len(trend["articles"]))
            self.assertIn("recent_48h_share",trend)
            self.assertTrue(trend["daily_counts"])
            self.assertTrue(trend["watch_next"])
            self.assertTrue(trend["why_it_matters_ko"])

    def test_demo_does_not_invent_source_links(self):
        view=_view(_run())
        self.assertEqual(view["status"],"DEMO")
        self.assertTrue(view["notice"])
        self.assertTrue(all(not a["url"] for t in view["trends"] for a in t["articles"]))

    def test_live_cached_and_failed_refresh_are_independent(self):
        fallback=json.loads((ROOT/"data/demo_outputs/trend_feed_fallback.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"latest_trends.json"
            refresh={"attempted_at":datetime.now(timezone.utc).isoformat(),"outcome":"failed","message":"AI 분석 요청 실패"}
            (path.parent/"latest_refresh.json").write_text(json.dumps(refresh),encoding="utf-8")
            for age,status in [(0,"LIVE"),(48,"CACHED")]:
                fallback.update(generated_at=(datetime.now(timezone.utc)-timedelta(hours=age)).isoformat(),is_synthetic=False,notice="")
                path.write_text(json.dumps(fallback),encoding="utf-8")
                with patch.dict(os.environ,{"GFR_LIVE_TRENDS_PATH":str(path)}):
                    view=_view(_run())
                self.assertEqual(view["status"],status)
                self.assertEqual(view["refresh"]["outcome"],"failed")
                self.assertEqual(view["refresh_message"],"AI 분석 요청 실패")
                self.assertNotEqual(view["generated_at"],view["refresh"]["attempted_at"])

    def test_view_is_a_copy_without_paths_or_diagnostics(self):
        payload={"status":"LIVE","trends":[],"stats":{},"company_intelligence":{"companies":[]},"source_path":"private/path","refresh":{"technical_error":"private","outcome":"partial"}}
        before=deepcopy(payload)
        view=prepare_view(payload)
        view["stats"]["article_count"]=999
        self.assertEqual(payload,before)
        self.assertNotIn("source_path",view)
        self.assertNotIn("technical_error",view["refresh"])

    def test_unsafe_urls_are_removed_in_trends_and_company_evidence(self):
        for url in ["javascript:alert(1)","data:text/html,x","//example.com","https://", "https://[bad"]:
            self.assertEqual(safe_url(url),"")
        self.assertEqual(safe_url("https://example.com/news?a=1&b=2"),"https://example.com/news?a=1&b=2")
        view=prepare_view({"trends":[{"articles":[{"url":"javascript:alert(1)"}]}],"company_intelligence":{"companies":[{"status":"AVAILABLE","briefs":[{"evidence_articles":[{"url":"data:text/html,x"}]}]}]}})
        self.assertEqual(view["trends"][0]["articles"][0]["url"],"")
        self.assertEqual(view["company_intelligence"]["companies"][0]["briefs"][0]["evidence_articles"][0]["url"],"")

    def test_partial_success_explains_failed_company_even_with_new_trends(self):
        feedback=refresh_feedback({"clustered":True,"trends":3,"outcome":"partial","error":"회사 분석 일부 실패","relevance_calls":{"hanwha_asset_management":{"status":"failed"}}})
        self.assertEqual(feedback["outcome"],"partial")
        self.assertIn("트렌드 3건 갱신",feedback["message"])
        self.assertIn("회사 분석 일부 실패",feedback["message"])
        self.assertIn("한화자산운용",feedback["message"])

    def test_refresh_callback_reports_exception_and_keeps_loaded_trends(self):
        from app.trend_feed_app import _refresh_now
        state={}
        with patch("app.trend_feed_app.st.session_state",state),patch("scripts.refresh_trend_feed.refresh",side_effect=RuntimeError("error")) as refresh:
            _refresh_now()
        self.assertEqual(refresh.call_count,1)
        self.assertEqual(state["gf_feedback"]["outcome"],"failed")
        self.assertIn("기존 결과를 유지",state["gf_feedback"]["message"])

    def test_refresh_callback_success_and_partial(self):
        from app.trend_feed_app import _refresh_now
        for outcome in ["success","partial"]:
            state={}
            with patch("app.trend_feed_app.st.session_state",state),patch("scripts.refresh_trend_feed.refresh",return_value={"clustered":True,"trends":3,"outcome":outcome,"error":"후속 단계 미완료"}):
                _refresh_now()
            self.assertEqual(state["gf_feedback"]["outcome"],outcome)
            self.assertIn("트렌드 3건",state["gf_feedback"]["message"])

    def test_all_company_failure_without_cluster_retains_previous_result_message(self):
        feedback=refresh_feedback({"clustered":False,"outcome":"failed","error":"수집 실패"})
        self.assertIn("기존 결과를 유지",feedback["message"])


if __name__ == "__main__":
    unittest.main()
