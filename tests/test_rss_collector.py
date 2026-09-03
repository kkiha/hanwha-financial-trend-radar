from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from rag_finance.ingestion.rss_collector import (
    WATCH_AREAS,
    build_feed_specs,
    canonical_url,
    collect_articles,
    dedupe_articles,
    make_article_id,
    normalize_title,
    parse_feed,
    within_window,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_rss.xml"
# The fixture is anchored around this instant.
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _fixture_articles() -> list[dict]:
    return parse_feed(
        FIXTURE.read_text(encoding="utf-8"),
        watch_area="rates_liquidity",
        language="en",
        fetched_at=NOW,
    )


class RssParsingTest(unittest.TestCase):
    def test_parses_items_and_skips_undated_entries(self) -> None:
        articles = _fixture_articles()

        # Six items, one of which has no pubDate.
        self.assertEqual(len(articles), 5)
        first = articles[0]
        self.assertEqual(first["title"], "Central bank keeps rate path open")
        self.assertEqual(first["source"], "Example Wire")
        self.assertEqual(first["language"], "en")
        self.assertEqual(first["watch_area"], "rates_liquidity")
        self.assertEqual(first["fetched_at"], NOW.isoformat())
        self.assertNotIn("<p>", first["summary"])
        self.assertIn("Policymakers left several scenarios", first["summary"])

    def test_titles_drop_the_publisher_suffix(self) -> None:
        titles = [item["title"] for item in _fixture_articles()]
        self.assertNotIn("Central bank keeps rate path open - Example Wire", titles)
        self.assertIn("Bond yields drift lower on softer inflation print", titles)

    def test_article_id_is_stable_and_ignores_tracking_params(self) -> None:
        clean = "https://example.com/news/rate-path"
        tracked = "https://example.com/news/rate-path?utm_source=rss&utm_medium=feed"
        self.assertEqual(canonical_url(tracked), canonical_url(clean))
        self.assertEqual(make_article_id(tracked, "t"), make_article_id(clean, "t"))
        self.assertEqual(make_article_id(clean, "t"), make_article_id(clean, "t"))
        self.assertTrue(make_article_id(clean, "t").startswith("A"))


class WindowAndDedupeTest(unittest.TestCase):
    def test_window_drops_old_and_future_dated_items(self) -> None:
        recent = within_window(_fixture_articles(), window_days=7, now=NOW)
        titles = {item["title"] for item in recent}
        self.assertNotIn("Stale story from well before the window", titles)
        self.assertEqual(len(recent), 4)

        skewed = [
            {"published_at": (NOW + timedelta(days=2)).isoformat(), "title": "future"}
        ]
        self.assertEqual(within_window(skewed, window_days=7, now=NOW), [])

    def test_dedupe_removes_same_url_and_syndicated_titles(self) -> None:
        recent = within_window(_fixture_articles(), window_days=7, now=NOW)
        deduped = dedupe_articles(recent)
        titles = [item["title"] for item in deduped]

        # Trailing-slash duplicate of the bond yields URL is gone.
        self.assertEqual(len(titles), 2)
        # The syndicated repeat of the same headline is gone too.
        self.assertEqual(sum(1 for t in titles if t.startswith("Central bank keeps")), 1)

    def test_normalize_title_ignores_punctuation_and_case(self) -> None:
        self.assertEqual(
            normalize_title("Central bank keeps rate path open - Example Wire"),
            normalize_title("Central Bank Keeps Rate Path Open!"),
        )


class CollectionTest(unittest.TestCase):
    def test_feed_specs_cover_every_area_and_language(self) -> None:
        specs = build_feed_specs()
        self.assertEqual(len(specs), len(WATCH_AREAS) * 2)
        self.assertEqual({spec.language for spec in specs}, {"ko", "en"})
        self.assertTrue(all("when%3A7d" in spec.url or "when:7d" in spec.url for spec in specs))

    def test_one_failing_feed_does_not_stop_collection(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        calls: list[str] = []

        def fetcher(url: str, timeout: int = 10) -> str:
            calls.append(url)
            if "hl=ko" in url:
                raise OSError("feed unavailable")
            return xml_text

        articles, debug = collect_articles(fetcher=fetcher, now=NOW)

        self.assertEqual(len(calls), len(WATCH_AREAS) * 2)
        self.assertEqual(debug["feeds_ok"], len(WATCH_AREAS))
        self.assertTrue(any("error" in feed for feed in debug["feeds"]))
        self.assertTrue(articles)
        # Same fixture served for three areas: dedupe keeps one copy per area.
        self.assertEqual(debug["deduped_count"], len(articles))
        self.assertTrue(all(item["language"] == "en" for item in articles))

    def test_collection_survives_unparseable_feed_body(self) -> None:
        articles, debug = collect_articles(fetcher=lambda url, timeout=10: "not xml", now=NOW)
        self.assertEqual(articles, [])
        self.assertEqual(debug["feeds_ok"], len(WATCH_AREAS) * 2)


if __name__ == "__main__":
    unittest.main()
