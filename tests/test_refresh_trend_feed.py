from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rag_finance.ingestion.rss_collector import (
    REASON_ALL_FEEDS_FAILED,
    REASON_EMPTY_FEEDS,
    REASON_MISSING_DEPENDENCY,
    REASON_OK,
)
from scripts import refresh_trend_feed
from scripts.refresh_trend_feed import (
    MISSING_GROQ_PACKAGE_MESSAGE,
    NO_API_KEY_MESSAGE,
    SKIPPED_LLM_MESSAGE,
    collection_summary,
    refresh,
)


def _articles(count: int = 6) -> list[dict]:
    return [
        {
            "article_id": f"A{index:03d}",
            "title": f"Title {index}",
            "source": f"Source {index % 3}",
            "published_at": "2026-09-03T09:00:00+00:00",
            "url": f"https://example.com/{index}",
            "summary": "요약",
            "language": "ko" if index % 2 else "en",
            "watch_area": "rates_liquidity",
        }
        for index in range(count)
    ]


def _debug(**overrides) -> dict:
    debug = {
        "feeds_total": 6,
        "feeds_ok": 6,
        "feeds_with_articles": 6,
        "feeds_empty": 0,
        "feeds_failed": 0,
        "ok_by_language": {"en": 3, "ko": 3},
        "with_articles_by_language": {"en": 3, "ko": 3},
        "raw_count": 8,
        "in_window_count": 7,
        "deduped_count": 6,
        "language_counts": {"ko": 3, "en": 3},
        "reason": REASON_OK,
        "feeds": [],
    }
    debug.update(overrides)
    return debug


def _patch_collect(articles, debug):
    return mock.patch.object(
        refresh_trend_feed, "collect_articles", return_value=(articles, debug)
    )


class SummaryTest(unittest.TestCase):
    def test_summary_reports_feeds_counts_and_languages(self) -> None:
        summary = collection_summary(
            _debug(
                feeds_ok=5,
                feeds_with_articles=5,
                in_window_count=42,
                deduped_count=31,
                language_counts={"ko": 16, "en": 15},
            )
        )
        self.assertIn("RSS 피드 5/6 응답", summary)
        self.assertIn("기사 42건 수집", summary)
        self.assertIn("중복 제거 후 31건", summary)
        self.assertIn("국내 16건 · 해외 15건", summary)
        self.assertNotIn("경고", summary)

    def test_summary_separates_responded_from_returned_articles(self) -> None:
        # A throttled provider answers 200 with an empty feed.
        summary = collection_summary(
            _debug(
                feeds_ok=6,
                feeds_with_articles=1,
                feeds_empty=5,
                language_counts={"ko": 93, "en": 0},
                with_articles_by_language={"ko": 1, "en": 0},
            )
        )
        self.assertIn("RSS 피드 6/6 응답", summary)
        self.assertIn("기사 반환 1/6", summary)
        self.assertIn("경고: 해외 피드가 기사를 반환하지 않았습니다.", summary)

    def test_empty_feeds_get_their_own_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect([], _debug(feeds_with_articles=0, feeds_empty=6, reason=REASON_EMPTY_FEEDS)):
                report = refresh(live_dir=Path(tmp))
        self.assertIn("기사를 반환하지 않았습니다", report["error"])
        self.assertIn("잠시 후 다시 시도", report["error"])


class RefreshFailureTest(unittest.TestCase):
    def test_missing_dependency_tells_the_user_to_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect([], _debug(feeds_ok=0, feeds_with_articles=0, feeds_failed=6, reason=REASON_MISSING_DEPENDENCY)):
                report = refresh(live_dir=Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

        self.assertFalse(report["ok"])
        self.assertIn("pip install -r requirements.txt", report["error"])

    def test_total_feed_failure_points_at_the_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect([], _debug(feeds_ok=0, feeds_with_articles=0, feeds_failed=6, reason=REASON_ALL_FEEDS_FAILED)):
                report = refresh(live_dir=Path(tmp))

        self.assertFalse(report["ok"])
        self.assertIn("네트워크 연결", report["error"])
        self.assertIn("RSS 피드 0/6 응답", report["summary"])

    def test_partial_failure_still_saves_the_articles_it_got(self) -> None:
        articles = _articles()
        debug = _debug(
            feeds_ok=5,
            feeds_with_articles=5,
            feeds_failed=1,
            ok_by_language={"en": 3, "ko": 2},
            with_articles_by_language={"en": 3, "ko": 2},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(articles, debug), mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
                report = refresh(live_dir=Path(tmp))
            saved = json.loads((Path(tmp) / "latest_articles.json").read_text(encoding="utf-8"))

        self.assertEqual(len(saved), len(articles))
        self.assertIn("RSS 피드 5/6 응답", report["summary"])
        self.assertFalse(report["clustered"])


class RefreshGroqGateTest(unittest.TestCase):
    def test_no_api_key_saves_articles_but_writes_no_trends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"GROQ_API_KEY": ""}, clear=False
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertEqual(report["error"], NO_API_KEY_MESSAGE)
        self.assertFalse(report["clustered"])
        # Synthetic or stale trends must never be written as if they were fresh.
        self.assertIn("latest_articles.json", names)
        self.assertNotIn("latest_trends.json", names)

    def test_missing_groq_package_is_reported_as_an_install_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"GROQ_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed,
                "cluster_trends",
                side_effect=RuntimeError("Install the groq package for trend clustering"),
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertEqual(report["error"], MISSING_GROQ_PACKAGE_MESSAGE)
        self.assertNotIn("latest_trends.json", names)

    def test_skip_llm_collects_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()):
                report = refresh(live_dir=Path(tmp), skip_llm=True)
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertEqual(report["error"], SKIPPED_LLM_MESSAGE)
        self.assertIn("latest_articles.json", names)
        self.assertNotIn("latest_trends.json", names)

    def test_cluster_failure_keeps_the_previous_trends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"GROQ_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed, "cluster_trends", side_effect=ValueError("bad json")
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertFalse(report["ok"])
        self.assertIn("AI 분석에 실패", report["error"])
        self.assertNotIn("latest_trends.json", names)


class RefreshSuccessTest(unittest.TestCase):
    def test_successful_run_writes_both_files_and_reports_ok(self) -> None:
        articles = _articles()
        clustered = {
            "generated_at": "2026-09-03T10:00:00+00:00",
            "window_days": 7,
            "model": "stub-model",
            "trends": [
                {
                    "trend_id": "trend_01",
                    "title_ko": "트렌드",
                    "summary_ko": "요약",
                    "why_it_matters_ko": "이유",
                    "watch_next": ["관찰"],
                    "article_ids": [item["article_id"] for item in articles[:4]],
                    "related_business_tags": ["증권 리서치"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(articles, _debug()), mock.patch.dict(
                os.environ, {"GROQ_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed, "cluster_trends", return_value=clustered
            ):
                report = refresh(live_dir=Path(tmp))
            written = json.loads((Path(tmp) / "latest_trends.json").read_text(encoding="utf-8"))

        self.assertTrue(report["ok"])
        self.assertTrue(report["clustered"])
        self.assertEqual(report["trends"], 1)
        self.assertFalse(written["is_synthetic"])
        self.assertEqual(len(written["articles"]), len(articles))

    def test_only_collected_articles_reach_the_clusterer(self) -> None:
        articles = _articles()
        seen: dict = {}

        def fake_cluster(passed, **kwargs):
            seen["ids"] = [item["article_id"] for item in passed]
            return {
                "generated_at": "2026-09-03T10:00:00+00:00",
                "window_days": 7,
                "trends": [
                    {
                        "trend_id": "trend_01",
                        "title_ko": "t",
                        "summary_ko": "s",
                        "why_it_matters_ko": "w",
                        "article_ids": [articles[0]["article_id"]],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(articles, _debug()), mock.patch.dict(
                os.environ, {"GROQ_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(refresh_trend_feed, "cluster_trends", fake_cluster):
                refresh(live_dir=Path(tmp))

        self.assertEqual(seen["ids"], [item["article_id"] for item in articles])


if __name__ == "__main__":
    unittest.main()
