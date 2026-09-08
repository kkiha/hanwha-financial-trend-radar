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
    AI_VALIDATION_MESSAGE,
    MISSING_OPENAI_PACKAGE_MESSAGE,
    NO_API_KEY_MESSAGE,
    SKIPPED_LLM_MESSAGE,
    _load_llm_settings,
    _load_rss_settings,
    collection_summary,
    refresh,
)
from rag_finance.llm.trend_clusterer import TrendClusteringError


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
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertFalse(report["ok"])
        self.assertIn("pip install -r requirements.txt", report["error"])
        self.assertEqual(names, {"latest_refresh.json"})

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
            with _patch_collect(articles, debug), mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                report = refresh(live_dir=Path(tmp))
            saved = json.loads((Path(tmp) / "latest_articles.json").read_text(encoding="utf-8"))

        self.assertEqual(len(saved), len(articles))
        self.assertIn("RSS 피드 5/6 응답", report["summary"])
        self.assertFalse(report["clustered"])


class RefreshOpenAIGateTest(unittest.TestCase):
    def test_no_api_key_saves_articles_but_writes_no_trends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"OPENAI_API_KEY": ""}, clear=False
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertEqual(report["error"], NO_API_KEY_MESSAGE)
        self.assertFalse(report["clustered"])
        # Synthetic or stale trends must never be written as if they were fresh.
        self.assertIn("latest_articles.json", names)
        self.assertNotIn("latest_trends.json", names)
        self.assertIn("latest_refresh.json", names)

    def test_missing_openai_package_is_reported_as_an_install_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed,
                "cluster_trends",
                side_effect=RuntimeError("Install the openai package for trend clustering"),
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}

        self.assertEqual(report["error"], MISSING_OPENAI_PACKAGE_MESSAGE)
        self.assertNotIn("latest_trends.json", names)

    def test_skip_llm_collects_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.object(
                refresh_trend_feed, "classify_company_relevance"
            ) as classify:
                report = refresh(live_dir=Path(tmp), skip_llm=True)
            names = {path.name for path in Path(tmp).iterdir()}

        classify.assert_not_called()
        self.assertEqual(report["error"], SKIPPED_LLM_MESSAGE)
        self.assertIn("latest_articles.json", names)
        self.assertNotIn("latest_trends.json", names)
        self.assertNotIn("latest_company_relevance.json", names)

    def test_cluster_failure_keeps_the_previous_trends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_collect(_articles(), _debug()), mock.patch.dict(
                os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed,
                "cluster_trends",
                side_effect=TrendClusteringError(
                    "invalid response",
                    {
                        "attempts": [
                            {"attempt": 1, "outcome": "validation_error"},
                            {"attempt": 2, "outcome": "validation_error"},
                        ]
                    },
                ),
            ):
                report = refresh(live_dir=Path(tmp))
            names = {path.name for path in Path(tmp).iterdir()}
            status = json.loads(
                (Path(tmp) / "latest_refresh.json").read_text(encoding="utf-8")
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], AI_VALIDATION_MESSAGE)
        self.assertEqual(report["error_code"], "llm_invalid_response")
        self.assertNotIn("latest_trends.json", names)
        self.assertEqual(status["outcome"], "failed")
        self.assertEqual(status["llm_diagnostics"]["attempts"][-1]["attempt"], 2)


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
                os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(
                refresh_trend_feed, "cluster_trends", return_value=clustered
            ):
                report = refresh(live_dir=Path(tmp), skip_relevance=True)
            written = json.loads((Path(tmp) / "latest_trends.json").read_text(encoding="utf-8"))
            status = json.loads(
                (Path(tmp) / "latest_refresh.json").read_text(encoding="utf-8")
            )

        self.assertTrue(report["ok"])
        self.assertTrue(report["clustered"])
        self.assertEqual(report["trends"], 1)
        self.assertFalse(written["is_synthetic"])
        self.assertEqual(len(written["articles"]), len(articles))
        self.assertEqual(status["outcome"], "success")

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
                os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(refresh_trend_feed, "cluster_trends", fake_cluster), mock.patch.object(
                refresh_trend_feed, "runtime_setting", return_value=""
            ):
                refresh(live_dir=Path(tmp), skip_relevance=True)

        self.assertEqual(seen["ids"], [item["article_id"] for item in articles])

    def test_all_llm_config_values_reach_the_clusterer(self) -> None:
        articles = _articles()
        seen: dict = {}
        config = {
            "llm": {
                "model": "configured-model",
                "temperature": 0.33,
                "max_tokens": 1777,
                "max_articles": 5,
                "reasoning_effort": "medium",
                "max_attempts": 3,
                "retry_base_delay_seconds": 0.25,
            }
        }

        def fake_cluster(passed, **kwargs):
            seen.update(kwargs)
            return {
                "generated_at": "2026-09-03T10:00:00+00:00",
                "window_days": 7,
                "model": kwargs["model"],
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
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with _patch_collect(articles, _debug()), mock.patch.dict(
                os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False
            ), mock.patch.object(refresh_trend_feed, "cluster_trends", fake_cluster), mock.patch.object(
                refresh_trend_feed, "runtime_setting", return_value=""
            ):
                refresh(
                    live_dir=Path(tmp),
                    config_path=config_path,
                    skip_relevance=True,
                )

        self.assertEqual(seen["model"], "configured-model")
        self.assertEqual(seen["temperature"], 0.33)
        self.assertEqual(seen["max_tokens"], 1777)
        self.assertEqual(seen["max_articles"], 5)
        self.assertEqual(seen["reasoning_effort"], "medium")
        self.assertEqual(seen["max_attempts"], 3)
        self.assertEqual(seen["retry_base_delay"], 0.25)


class RefreshRelevanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.articles = _articles()
        self.clustered = {
            "generated_at": "2026-09-03T10:00:00+00:00",
            "window_days": 7,
            "model": "stub-model",
            "trends": [
                {
                    "trend_id": "trend_01",
                    "title_ko": "트렌드",
                    "summary_ko": "요약",
                    "why_it_matters_ko": "이유",
                    "article_ids": [self.articles[0]["article_id"]],
                }
            ],
        }

    def _run(self, relevance: dict, *, skip_relevance: bool = False):
        stack = [
            _patch_collect(self.articles, _debug()),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False),
            mock.patch.object(
                refresh_trend_feed, "cluster_trends", return_value=self.clustered
            ),
            mock.patch.object(
                refresh_trend_feed,
                "classify_company_relevance",
                return_value=relevance,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with stack[0], stack[1], stack[2], stack[3] as classify:
                report = refresh(
                    live_dir=Path(tmp), skip_relevance=skip_relevance
                )
            files = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in Path(tmp).iterdir()
                if path.suffix == ".json"
            }
        return report, files, classify

    def test_success_saves_separate_relevance_and_reports_count(self) -> None:
        relevance = {
            "generated_at": "2026-09-03T10:01:00+00:00",
            "source_trends_generated_at": self.clustered["generated_at"],
            "model": "stub-model",
            "status": "CLASSIFIED",
            "evaluations": [{"index": index} for index in range(9)],
            "relevance_calls": {
                "hanwha_life": {
                    "status": "success",
                    "attempts": 1,
                    "input_chars": 3000,
                }
            },
        }
        report, files, classify = self._run(relevance)

        self.assertTrue(report["ok"])
        self.assertTrue(report["relevance_classified"])
        self.assertEqual(report["relevance_evaluations"], 9)
        self.assertEqual(
            files["latest_company_relevance.json"]["status"], "CLASSIFIED"
        )
        self.assertEqual(files["latest_refresh.json"]["relevance_evaluations"], 9)
        self.assertEqual(classify.call_args.kwargs["max_attempts"], 2)
        self.assertEqual(classify.call_args.kwargs["max_tokens"], 1200)
        self.assertEqual(classify.call_args.kwargs["reasoning_effort"], "none")
        self.assertEqual(
            files["latest_refresh.json"]["relevance_calls"],
            relevance["relevance_calls"],
        )

    def test_relevance_failure_preserves_successful_trends(self) -> None:
        relevance = {
            "generated_at": "2026-09-03T10:01:00+00:00",
            "source_trends_generated_at": self.clustered["generated_at"],
            "model": "stub-model",
            "status": "UNCLASSIFIED",
            "evaluations": [],
            "error": {"type": "ValueError", "message": "안전한 오류"},
        }
        report, files, _ = self._run(relevance)

        self.assertTrue(report["ok"])
        self.assertTrue(report["clustered"])
        self.assertFalse(report["relevance_classified"])
        self.assertEqual(report["outcome"], "partial")
        self.assertEqual(files["latest_trends.json"]["trends"], self.clustered["trends"])
        self.assertEqual(
            files["latest_company_relevance.json"]["status"], "UNCLASSIFIED"
        )

    def test_skip_relevance_keeps_trends_and_does_not_call_classifier(self) -> None:
        report, files, classify = self._run({}, skip_relevance=True)

        classify.assert_not_called()
        self.assertTrue(report["clustered"])
        self.assertEqual(report["relevance_status"], "SKIPPED")
        self.assertIn("latest_trends.json", files)
        self.assertNotIn("latest_company_relevance.json", files)
        self.assertNotIn("latest_company_briefs.json", files)


class RefreshBriefTest(unittest.TestCase):
    def setUp(self) -> None:
        self.articles = _articles()
        self.clustered = {
            "generated_at": "2026-09-03T10:00:00+00:00",
            "window_days": 7,
            "model": "stub-model",
            "trends": [
                {
                    "trend_id": "trend_01",
                    "title_ko": "트렌드",
                    "summary_ko": "요약",
                    "why_it_matters_ko": "이유",
                    "article_ids": [self.articles[0]["article_id"]],
                }
            ],
        }
        self.relevance = {
            "generated_at": "2026-09-03T10:01:00+00:00",
            "source_trends_generated_at": self.clustered["generated_at"],
            "model": "stub-model",
            "status": "CLASSIFIED",
            "evaluations": [],
        }

    def _run(self, briefs: dict, *, skip_briefs: bool = False):
        patches = [
            _patch_collect(self.articles, _debug()),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False),
            mock.patch.object(
                refresh_trend_feed, "cluster_trends", return_value=self.clustered
            ),
            mock.patch.object(
                refresh_trend_feed,
                "classify_company_relevance",
                return_value=self.relevance,
            ),
            mock.patch.object(
                refresh_trend_feed, "generate_company_briefs", return_value=briefs
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patches[0], patches[1], patches[2], patches[3], patches[4] as generator:
                report = refresh(live_dir=Path(tmp), skip_briefs=skip_briefs)
            files = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in Path(tmp).iterdir()
                if path.suffix == ".json"
            }
        return report, files, generator

    def test_success_reports_main_and_monitoring_counts(self) -> None:
        briefs = {
            "generated_at": "2026-09-03T10:02:00+00:00",
            "source_trends_generated_at": self.clustered["generated_at"],
            "source_relevance_generated_at": self.relevance["generated_at"],
            "model": "stub-model",
            "status": "GENERATED",
            "companies": [
                {"briefs": [{"brief_id": "one"}], "monitoring_items": []},
                {"briefs": [], "monitoring_items": [{"trend_id": "two"}]},
                {"briefs": [], "monitoring_items": [{"trend_id": "three"}]},
            ],
        }
        report, files, generator = self._run(briefs)

        self.assertTrue(report["ok"])
        self.assertEqual(report["outcome"], "success")
        self.assertTrue(report["briefs_generated"])
        self.assertEqual(report["main_briefs"], 1)
        self.assertEqual(report["monitoring_items"], 2)
        self.assertEqual(files["latest_company_briefs.json"]["status"], "GENERATED")
        self.assertEqual(files["latest_refresh.json"]["main_briefs"], 1)
        self.assertEqual(generator.call_args.kwargs["max_attempts"], 2)
        self.assertEqual(generator.call_args.kwargs["max_tokens"], 4000)

    def test_brief_failure_preserves_trends_and_relevance(self) -> None:
        briefs = {
            "generated_at": "2026-09-03T10:02:00+00:00",
            "source_trends_generated_at": self.clustered["generated_at"],
            "source_relevance_generated_at": self.relevance["generated_at"],
            "model": "stub-model",
            "status": "UNGENERATED",
            "companies": [],
            "error": {"type": "ValueError", "message": "안전한 오류"},
        }
        report, files, _ = self._run(briefs)

        self.assertTrue(report["ok"])
        self.assertTrue(report["relevance_classified"])
        self.assertFalse(report["briefs_generated"])
        self.assertEqual(report["outcome"], "partial")
        self.assertEqual(report["stage"], "briefs")
        self.assertIn("latest_trends.json", files)
        self.assertEqual(files["latest_company_relevance.json"]["status"], "CLASSIFIED")
        self.assertEqual(files["latest_company_briefs.json"]["status"], "UNGENERATED")

    def test_skip_briefs_preserves_relevance_and_does_not_call_generator(self) -> None:
        report, files, generator = self._run({}, skip_briefs=True)

        generator.assert_not_called()
        self.assertEqual(report["brief_status"], "SKIPPED")
        self.assertIn("latest_trends.json", files)
        self.assertIn("latest_company_relevance.json", files)
        self.assertNotIn("latest_company_briefs.json", files)


class LlmConfigTest(unittest.TestCase):
    def test_invalid_values_fall_back_to_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "llm": {
                            "model": "",
                            "max_tokens": -1,
                            "relevance_max_tokens_per_company": -1,
                            "relevance_reasoning_effort": "extreme",
                            "max_articles": True,
                            "reasoning_effort": "extreme",
                            "max_attempts": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = _load_llm_settings(path)

        self.assertGreater(settings["max_tokens"], 0)
        self.assertEqual(settings["relevance_max_tokens_per_company"], 1200)
        self.assertEqual(settings["relevance_reasoning_effort"], "none")
        self.assertEqual(settings["brief_max_tokens"], 4000)
        self.assertGreater(settings["max_articles"], 0)
        self.assertIn(settings["reasoning_effort"], {"none", "low", "medium", "high", None})
        self.assertGreaterEqual(settings["max_attempts"], 1)

    def test_brief_token_limit_is_loaded_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {"llm": {"max_tokens": 2600, "brief_max_tokens": 4321}}
                ),
                encoding="utf-8",
            )
            settings = _load_llm_settings(path)

        self.assertEqual(settings["max_tokens"], 2600)
        self.assertEqual(settings["brief_max_tokens"], 4321)

    def test_relevance_company_limit_is_loaded_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "llm": {
                            "max_tokens": 2600,
                            "relevance_max_tokens_per_company": 987,
                            "brief_max_tokens": 4000,
                            "reasoning_effort": "medium",
                            "relevance_reasoning_effort": "low",
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = _load_llm_settings(path)

        self.assertEqual(settings["max_tokens"], 2600)
        self.assertEqual(settings["relevance_max_tokens_per_company"], 987)
        self.assertEqual(settings["brief_max_tokens"], 4000)
        self.assertEqual(settings["reasoning_effort"], "medium")
        self.assertEqual(settings["relevance_reasoning_effort"], "low")


class RssConfigTest(unittest.TestCase):
    def test_new_app_defaults_to_profile_queries(self) -> None:
        settings = _load_rss_settings()
        self.assertEqual(settings["source_mode"], "profiles")
        self.assertEqual(settings["profiles_dir"], "configs/company_profiles")

    def test_refresh_passes_config_mode_and_allows_cli_override(self) -> None:
        seen: list[dict] = []

        def fake_collect(**kwargs):
            seen.append(kwargs)
            return [], _debug(
                feeds_ok=0,
                feeds_with_articles=0,
                feeds_failed=24,
                reason=REASON_ALL_FEEDS_FAILED,
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            refresh_trend_feed, "collect_articles", fake_collect
        ):
            refresh(live_dir=Path(tmp))
            refresh(live_dir=Path(tmp), source_mode="common")

        self.assertEqual(seen[0]["source_mode"], "profiles")
        self.assertEqual(seen[1]["source_mode"], "common")


if __name__ == "__main__":
    unittest.main()
