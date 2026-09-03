from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from app.trend_feed_data import (
    FALLBACK_PATH,
    build_payload,
    compute_trend_metrics,
    daily_counts,
    load_trend_feed,
    rank_trends,
    save_live_payload,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _article(article_id: str, *, hours_ago: float, source: str, language: str = "en") -> dict:
    return {
        "article_id": article_id,
        "title": f"Title {article_id}",
        "source": source,
        "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "url": f"https://example.com/{article_id}",
        "summary": "요약",
        "language": language,
        "watch_area": "rates_liquidity",
    }


def _live_payload() -> dict:
    articles = [
        _article("A1", hours_ago=2, source="Wire A"),
        _article("A2", hours_ago=10, source="Wire B", language="ko"),
        _article("A3", hours_ago=90, source="Wire A"),
        _article("B1", hours_ago=5, source="Wire C"),
        _article("B2", hours_ago=6, source="Wire D"),
    ]
    return {
        "generated_at": (NOW - timedelta(hours=1)).isoformat(),
        "window_days": 7,
        "model": "test-model",
        "articles": articles,
        "trends": [
            {
                "trend_id": "trend_01",
                "title_ko": "작은 트렌드",
                "summary_ko": "요약",
                "why_it_matters_ko": "이유",
                "watch_next": ["관찰"],
                "article_ids": ["B1", "B2"],
                "related_business_tags": ["증권 리서치"],
            },
            {
                "trend_id": "trend_02",
                "title_ko": "큰 트렌드",
                "summary_ko": "요약",
                "why_it_matters_ko": "이유",
                "watch_next": ["관찰"],
                "article_ids": ["A1", "A2", "A3", "GHOST"],
                "related_business_tags": ["보험 자산운용"],
            },
        ],
    }


class MetricsTest(unittest.TestCase):
    def test_metrics_are_computed_from_linked_articles(self) -> None:
        articles = {item["article_id"]: item for item in _live_payload()["articles"]}
        trend = {"article_ids": ["A1", "A2", "A3", "GHOST"]}
        metrics = compute_trend_metrics(trend, articles, now=NOW)

        self.assertEqual(metrics["article_count"], 3)  # GHOST is not linked
        self.assertEqual(metrics["source_count"], 2)  # Wire A twice, Wire B once
        self.assertEqual(metrics["recent_48h_count"], 2)
        self.assertAlmostEqual(metrics["recent_48h_share"], 2 / 3)
        self.assertEqual(metrics["language_mix"], {"ko": 1, "en": 2})
        self.assertEqual(len(metrics["daily_counts"]), 7)

    def test_daily_counts_cover_the_whole_window(self) -> None:
        counts = daily_counts([_article("X", hours_ago=1, source="S")], now=NOW)
        self.assertEqual(len(counts), 7)
        self.assertEqual(sum(day["count"] for day in counts), 1)
        self.assertEqual(counts[-1]["count"], 1)

    def test_ranking_combines_volume_sources_and_recency(self) -> None:
        ranked = rank_trends(
            [
                {"article_count": 2, "source_count": 2, "recent_48h_share": 1.0},
                {"article_count": 8, "source_count": 5, "recent_48h_share": 0.5},
            ]
        )
        self.assertEqual(ranked[0]["article_count"], 8)
        self.assertEqual([item["rank"] for item in ranked], [1, 2])
        self.assertGreater(ranked[0]["priority_score"], ranked[1]["priority_score"])


class LoadingTest(unittest.TestCase):
    def test_live_payload_is_ranked_and_ghost_ids_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "latest_trends.json"
            live.write_text(json.dumps(_live_payload(), ensure_ascii=False), encoding="utf-8")
            payload = load_trend_feed(live_path=live, now=NOW)

        self.assertEqual(payload["status"], "LIVE")
        self.assertEqual(payload["trends"][0]["title_ko"], "큰 트렌드")
        self.assertEqual(payload["trends"][0]["article_count"], 3)
        self.assertEqual(payload["stats"]["article_count"], 5)
        self.assertEqual(payload["stats"]["source_count"], 4)
        self.assertEqual(payload["stats"]["trend_count"], 2)

    def test_stale_live_payload_is_labelled_cached(self) -> None:
        raw = _live_payload()
        raw["generated_at"] = (NOW - timedelta(days=3)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "latest_trends.json"
            live.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            payload = load_trend_feed(live_path=live, now=NOW)
        self.assertEqual(payload["status"], "CACHED")

    def test_missing_live_file_falls_back_to_demo(self) -> None:
        payload = load_trend_feed(live_path=Path("does/not/exist.json"), now=NOW)
        self.assertEqual(payload["status"], "DEMO")
        self.assertEqual(len(payload["trends"]), 3)
        self.assertTrue(payload["is_synthetic"])

    def test_corrupt_live_file_falls_back_to_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "latest_trends.json"
            live.write_text("{ this is not json", encoding="utf-8")
            payload = load_trend_feed(live_path=live, now=NOW)
        self.assertEqual(payload["status"], "DEMO")
        self.assertTrue(payload["trends"])

    def test_fallback_articles_land_inside_the_window(self) -> None:
        payload = load_trend_feed(live_path=Path("missing.json"), now=NOW)
        for trend in payload["trends"]:
            self.assertGreaterEqual(trend["article_count"], 3)
            self.assertGreaterEqual(trend["source_count"], 2)
            self.assertTrue(any(day["count"] for day in trend["daily_counts"]))
        # Synthetic articles must not pretend to be real reporting.
        for article in payload["articles"]:
            self.assertEqual(article["url"], "")


class FallbackFileTest(unittest.TestCase):
    def test_bundled_fallback_is_marked_synthetic(self) -> None:
        raw = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        self.assertTrue(raw["is_synthetic"])
        self.assertIn("합성", raw["notice"])
        self.assertEqual(len(raw["trends"]), 3)
        known = {item["article_id"] for item in raw["articles"]}
        for trend in raw["trends"]:
            self.assertTrue(set(trend["article_ids"]) <= known)


class SaveTest(unittest.TestCase):
    def test_save_writes_both_runtime_files(self) -> None:
        raw = _live_payload()
        with tempfile.TemporaryDirectory() as tmp:
            target = save_live_payload(
                {"generated_at": NOW.isoformat(), "window_days": 7, "trends": raw["trends"]},
                raw["articles"],
                collection={"feeds_ok": 6},
                live_dir=Path(tmp),
            )
            self.assertTrue(target.is_file())
            self.assertTrue((Path(tmp) / "latest_articles.json").is_file())
            written = json.loads(target.read_text(encoding="utf-8"))

        self.assertFalse(written["is_synthetic"])
        self.assertEqual(written["collection"]["feeds_ok"], 6)
        self.assertEqual(len(written["articles"]), 5)

    def test_build_payload_skips_trends_without_linked_articles(self) -> None:
        raw = _live_payload()
        raw["trends"].append(
            {
                "trend_id": "trend_03",
                "title_ko": "빈 트렌드",
                "summary_ko": "요약",
                "why_it_matters_ko": "이유",
                "article_ids": ["NOPE"],
            }
        )
        payload = build_payload(raw, status="LIVE", source_path=None, now=NOW)
        self.assertEqual(len(payload["trends"]), 2)


if __name__ == "__main__":
    unittest.main()
