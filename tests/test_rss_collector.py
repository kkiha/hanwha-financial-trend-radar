from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from rag_finance.ingestion.rss_collector import (
    BACKUP_FEEDS,
    REASON_ALL_FEEDS_FAILED,
    REASON_EMPTY_FEEDS,
    REASON_MISSING_DEPENDENCY,
    REASON_OK,
    WATCH_AREAS,
    build_profile_feed_specs,
    build_feed_specs,
    classify_watch_area,
    canonical_url,
    collect_articles,
    dedupe_articles,
    make_article_id,
    normalize_title,
    parse_feed,
    within_window,
)
from rag_finance.profiles.company_profiles import load_all_company_profiles

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
        specs = build_feed_specs(include_backup=False)
        self.assertEqual(len(specs), len(WATCH_AREAS) * 2)
        self.assertEqual({spec.language for spec in specs}, {"ko", "en"})
        self.assertTrue(all("when%3A7d" in spec.url or "when:7d" in spec.url for spec in specs))

    def test_backup_publisher_feeds_are_added_by_default(self) -> None:
        search_only = build_feed_specs(include_backup=False)
        with_backup = build_feed_specs()

        self.assertEqual(len(with_backup), len(search_only) + len(BACKUP_FEEDS))
        direct = [spec for spec in with_backup if spec.provider == "direct"]
        self.assertEqual(len(direct), len(BACKUP_FEEDS))
        # Direct feeds are general economy feeds, so their area is derived per item.
        self.assertTrue(all(spec.classify for spec in direct))
        self.assertTrue(all(not spec.classify for spec in search_only))

    def test_profile_feed_specs_cover_all_company_queries_and_languages(self) -> None:
        profiles = load_all_company_profiles()
        specs = build_profile_feed_specs(profiles, window_days=7)

        self.assertEqual(len(specs), 24)
        self.assertEqual(sum(spec.language == "ko" for spec in specs), 12)
        self.assertEqual(sum(spec.language == "en" for spec in specs), 12)
        self.assertEqual(
            {spec.company_id for spec in specs},
            {"hanwha_life", "hanwha_asset_management", "hanwha_investment"},
        )
        self.assertTrue(all(spec.query_id and spec.topic_ids for spec in specs))
        self.assertTrue(all(spec.provider == "profile_search" for spec in specs))

    def test_source_modes_preserve_common_and_default_profiles_have_no_backups(self) -> None:
        profiles = load_all_company_profiles()
        profile_specs = build_feed_specs(source_mode="profiles", profiles=profiles)
        common_specs = build_feed_specs(source_mode="common", include_backup=False)
        both_specs = build_feed_specs(
            source_mode="both", profiles=profiles, include_backup=False
        )

        self.assertEqual(len(profile_specs), 24)
        self.assertTrue(all(spec.provider == "profile_search" for spec in profile_specs))
        self.assertEqual(len(common_specs), 6)
        self.assertEqual(len(both_specs), 30)

    def test_profile_articles_store_candidate_metadata(self) -> None:
        profiles = load_all_company_profiles()
        xml_text = FIXTURE.read_text(encoding="utf-8")
        articles, debug = collect_articles(
            fetcher=lambda url, timeout=10: xml_text,
            now=NOW,
            retries=0,
            include_backup=False,
            source_mode="profiles",
            profiles=profiles,
        )

        self.assertTrue(articles)
        self.assertEqual(debug["source_mode"], "profiles")
        self.assertEqual(debug["profile_count"], 3)
        self.assertEqual(debug["query_count"], 24)
        article = articles[0]
        self.assertEqual(
            article["candidate_companies"],
            ["hanwha_asset_management", "hanwha_investment", "hanwha_life"],
        )
        self.assertTrue(article["matched_topic_ids"])
        self.assertEqual(len(article["matched_query_ids"]), 24)
        self.assertEqual(set(debug["company_candidate_counts"]), set(profiles))

    def test_dedupe_merges_candidate_metadata_in_stable_order(self) -> None:
        base = {
            "title": "동일한 퇴직연금 기사",
            "url": "https://example.com/retirement",
            "published_at": NOW.isoformat(),
        }
        articles = [
            {
                **base,
                "candidate_companies": ["hanwha_life"],
                "matched_topic_ids": ["life_retirement"],
                "matched_query_ids": ["life_ko_01"],
            },
            {
                **base,
                "candidate_companies": ["hanwha_investment"],
                "matched_topic_ids": ["investment_retirement"],
                "matched_query_ids": ["investment_ko_02"],
            },
        ]

        merged = dedupe_articles(articles)
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["candidate_companies"],
            ["hanwha_investment", "hanwha_life"],
        )
        self.assertEqual(
            merged[0]["matched_query_ids"], ["investment_ko_02", "life_ko_01"]
        )

    def test_profile_mode_allows_partial_feed_failure(self) -> None:
        profiles = load_all_company_profiles()
        xml_text = FIXTURE.read_text(encoding="utf-8")

        def fetcher(url: str, timeout: int = 10) -> str:
            if "hl=en-US" in url:
                raise OSError("feed unavailable")
            return xml_text

        articles, debug = collect_articles(
            fetcher=fetcher,
            now=NOW,
            retries=0,
            include_backup=False,
            source_mode="profiles",
            profiles=profiles,
        )

        self.assertTrue(articles)
        self.assertEqual(debug["feeds_ok"], 12)
        self.assertEqual(debug["feeds_failed"], 12)
        self.assertEqual(debug["reason"], REASON_OK)

    def test_direct_feed_items_are_classified_by_keyword(self) -> None:
        feed = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item><title>한국은행 기준금리 동결 결정</title><link>https://ex.test/a</link>
            <pubDate>Wed, 02 Sep 2026 09:00:00 GMT</pubDate><description>금리 관련</description></item>
          <item><title>가상자산 규제 개편 논의</title><link>https://ex.test/b</link>
            <pubDate>Wed, 02 Sep 2026 10:00:00 GMT</pubDate><description>제도 정비</description></item>
        </channel></rss>"""

        backup_urls = {item["url"] for item in BACKUP_FEEDS}

        def fetcher(url: str, timeout: int = 10) -> str:
            # Only the direct publisher feeds carry these items; the search feeds
            # return nothing so the classified copies are the ones kept.
            return feed if url in backup_urls else '<rss version="2.0"><channel/></rss>'

        articles, _ = collect_articles(fetcher=fetcher, now=NOW)
        areas = {item["title"]: item["watch_area"] for item in articles}
        self.assertEqual(areas["한국은행 기준금리 동결 결정"], "rates_liquidity")
        self.assertEqual(areas["가상자산 규제 개편 논의"], "regulation_innovation")

    def test_classify_watch_area_falls_back_to_the_feed_default(self) -> None:
        self.assertEqual(classify_watch_area("금리 인하 기대", "risk_flows"), "rates_liquidity")
        self.assertEqual(classify_watch_area("stablecoin rules", "risk_flows"), "regulation_innovation")
        self.assertEqual(classify_watch_area("무관한 문장", "risk_flows"), "risk_flows")

    def test_one_failing_feed_does_not_stop_collection(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        calls: list[str] = []

        def fetcher(url: str, timeout: int = 10) -> str:
            calls.append(url)
            if "hl=ko" in url:
                raise OSError("feed unavailable")
            return xml_text

        # retries=0 keeps the call count equal to the feed count; the retry
        # behaviour itself is covered by test_a_transient_failure_is_retried_once.
        articles, debug = collect_articles(fetcher=fetcher, now=NOW, retries=0, include_backup=False)

        self.assertEqual(len(calls), len(WATCH_AREAS) * 2)
        self.assertEqual(debug["feeds_ok"], len(WATCH_AREAS))
        self.assertTrue(any("error" in feed for feed in debug["feeds"]))
        self.assertTrue(articles)
        # Same fixture served for three areas: dedupe keeps one copy per area.
        self.assertEqual(debug["deduped_count"], len(articles))
        self.assertTrue(all(item["language"] == "en" for item in articles))

    def test_collection_survives_unparseable_feed_body(self) -> None:
        articles, debug = collect_articles(fetcher=lambda url, timeout=10: "not xml", now=NOW, include_backup=False)
        self.assertEqual(articles, [])
        self.assertEqual(debug["feeds_ok"], len(WATCH_AREAS) * 2)
        self.assertEqual(debug["reason"], REASON_EMPTY_FEEDS)

    def test_a_feed_that_responds_with_no_items_is_not_counted_as_a_success(self) -> None:
        empty_feed = (
            '<?xml version="1.0"?><rss version="2.0"><channel>'
            "<title>Throttled</title></channel></rss>"
        )
        xml_text = FIXTURE.read_text(encoding="utf-8")

        def fetcher(url: str, timeout: int = 10) -> str:
            return empty_feed if "hl=en-US" in url else xml_text

        articles, debug = collect_articles(fetcher=fetcher, now=NOW, include_backup=False)

        # HTTP-wise all six responded, but only the Korean ones returned items.
        self.assertEqual(debug["feeds_ok"], 6)
        self.assertEqual(debug["feeds_with_articles"], 3)
        self.assertEqual(debug["feeds_empty"], 3)
        self.assertEqual(debug["with_articles_by_language"], {"en": 0, "ko": 3})
        self.assertEqual(debug["language_counts"]["en"], 0)
        self.assertTrue(articles)
        self.assertEqual(debug["reason"], REASON_OK)

    def test_all_feeds_empty_is_reported_as_empty_not_success(self) -> None:
        empty_feed = '<?xml version="1.0"?><rss version="2.0"><channel/></rss>'
        articles, debug = collect_articles(fetcher=lambda url, timeout=10: empty_feed, now=NOW, include_backup=False)

        self.assertEqual(articles, [])
        self.assertEqual(debug["feeds_ok"], 6)
        self.assertEqual(debug["feeds_with_articles"], 0)
        self.assertEqual(debug["reason"], REASON_EMPTY_FEEDS)

    def test_partial_failure_records_language_level_success(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")

        def fetcher(url: str, timeout: int = 10) -> str:
            if "hl=ko" in url:
                raise OSError("feed unavailable")
            return xml_text

        articles, debug = collect_articles(fetcher=fetcher, now=NOW, retries=0, include_backup=False)

        self.assertEqual(debug["feeds_ok"], 3)
        self.assertEqual(debug["feeds_failed"], 3)
        self.assertEqual(debug["ok_by_language"], {"en": 3, "ko": 0})
        self.assertEqual(debug["reason"], REASON_OK)
        self.assertEqual(debug["language_counts"]["ko"], 0)
        self.assertEqual(debug["language_counts"]["en"], len(articles))

    def test_all_feeds_failing_reports_a_network_reason(self) -> None:
        def fetcher(url: str, timeout: int = 10) -> str:
            raise OSError("no route to host")

        articles, debug = collect_articles(fetcher=fetcher, now=NOW, retries=0, include_backup=False)

        self.assertEqual(articles, [])
        self.assertEqual(debug["feeds_ok"], 0)
        self.assertEqual(debug["feeds_failed"], len(WATCH_AREAS) * 2)
        self.assertEqual(debug["reason"], REASON_ALL_FEEDS_FAILED)

    def test_missing_dependency_is_reported_separately_and_not_retried(self) -> None:
        attempts: list[str] = []

        def fetcher(url: str, timeout: int = 10) -> str:
            attempts.append(url)
            raise ImportError("No module named 'requests'")

        articles, debug = collect_articles(fetcher=fetcher, now=NOW, retries=2, include_backup=False)

        self.assertEqual(articles, [])
        self.assertEqual(debug["reason"], REASON_MISSING_DEPENDENCY)
        # One attempt per feed: retrying a missing package is pointless.
        self.assertEqual(len(attempts), len(WATCH_AREAS) * 2)
        self.assertTrue(all(feed["attempts"] == 1 for feed in debug["feeds"]))

    def test_a_transient_failure_is_retried_once(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        seen: dict[str, int] = {}

        def fetcher(url: str, timeout: int = 10) -> str:
            seen[url] = seen.get(url, 0) + 1
            if seen[url] == 1:
                raise TimeoutError("temporary")
            return xml_text

        articles, debug = collect_articles(fetcher=fetcher, now=NOW, retries=1, include_backup=False)

        self.assertEqual(debug["feeds_ok"], len(WATCH_AREAS) * 2)
        self.assertTrue(all(feed["attempts"] == 2 for feed in debug["feeds"]))
        self.assertTrue(articles)

    def test_feeds_are_fetched_in_parallel(self) -> None:
        import threading

        xml_text = FIXTURE.read_text(encoding="utf-8")
        active = 0
        peak = 0
        lock = threading.Lock()

        def fetcher(url: str, timeout: int = 10) -> str:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                threading.Event().wait(0.05)
                return xml_text
            finally:
                with lock:
                    active -= 1

        collect_articles(fetcher=fetcher, now=NOW, include_backup=False)
        self.assertGreater(peak, 1)


if __name__ == "__main__":
    unittest.main()
