from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from rag_finance.llm.trend_clusterer import (
    ALLOWED_BUSINESS_TAGS,
    TREND_COUNT,
    build_cluster_messages,
    cluster_trends,
    normalize_business_tags,
    parse_structured_json,
    select_articles_for_llm,
    validate_trend_payload,
)


def _articles(count: int = 9) -> list[dict]:
    areas = ["rates_liquidity", "risk_flows", "regulation_innovation"]
    return [
        {
            "article_id": f"A{index:03d}",
            "title": f"Headline {index}",
            "source": f"Source {index % 4}",
            "published_at": f"2026-09-0{(index % 3) + 1}T09:00:00+00:00",
            "summary": f"Summary {index}",
            "watch_area": areas[index % 3],
            "language": "ko" if index % 2 else "en",
        }
        for index in range(count)
    ]


def _payload(articles: list[dict]) -> dict:
    ids = [item["article_id"] for item in articles]
    return {
        "generated_at": "2026-09-03T09:00:00+00:00",
        "window_days": 7,
        "trends": [
            {
                "trend_id": f"trend_{index:02d}",
                "title_ko": f"트렌드 {index}",
                "summary_ko": "요약",
                "why_it_matters_ko": "이유",
                "watch_next": ["관찰 1", "관찰 2"],
                "article_ids": ids[index - 1 :: 3],
                "related_business_tags": ["증권 리서치"],
            }
            for index in range(1, TREND_COUNT + 1)
        ],
    }


class PromptTest(unittest.TestCase):
    def test_prompt_states_the_json_and_safety_contract(self) -> None:
        messages = build_cluster_messages(_articles(), window_days=7)
        system = messages[0]["content"]
        self.assertIn("JSON 객체만", system)
        self.assertIn("투자 추천", system)
        self.assertIn("수치는 시스템이 따로 계산한다", system)
        for tag in ALLOWED_BUSINESS_TAGS[:3]:
            self.assertIn(tag, system)

    def test_prompt_sends_only_the_scoped_fields(self) -> None:
        messages = build_cluster_messages(_articles(), window_days=7)
        sent = json.loads(messages[1]["content"])
        self.assertEqual(
            set(sent["articles"][0]),
            {"article_id", "title", "source", "published_at", "summary", "watch_area"},
        )

    def test_selection_balances_areas_and_languages(self) -> None:
        selected = select_articles_for_llm(_articles(12), limit=6)
        self.assertEqual(len(selected), 6)
        self.assertEqual(len({item["watch_area"] for item in selected}), 3)
        self.assertEqual(len({item["language"] for item in selected}), 2)


class ValidationTest(unittest.TestCase):
    def test_accepts_a_well_formed_payload(self) -> None:
        articles = _articles()
        result = validate_trend_payload(_payload(articles), articles)
        self.assertEqual(len(result["trends"]), TREND_COUNT)
        self.assertTrue(all(trend["article_ids"] for trend in result["trends"]))

    def test_unknown_article_ids_are_dropped(self) -> None:
        articles = _articles()
        payload = _payload(articles)
        payload["trends"][0]["article_ids"] = ["A000", "GHOST", "A003"]
        result = validate_trend_payload(payload, articles)
        self.assertEqual(result["trends"][0]["article_ids"], ["A000", "A003"])

    def test_trend_with_only_invented_ids_is_rejected(self) -> None:
        articles = _articles()
        payload = _payload(articles)
        payload["trends"][1]["article_ids"] = ["NOPE", "ALSO_NOPE"]
        with self.assertRaises(ValueError):
            validate_trend_payload(payload, articles)

    def test_missing_text_fields_are_rejected(self) -> None:
        articles = _articles()
        payload = _payload(articles)
        payload["trends"][0]["summary_ko"] = "   "
        with self.assertRaises(ValueError):
            validate_trend_payload(payload, articles)

    def test_business_tags_are_whitelisted_and_capped(self) -> None:
        self.assertEqual(normalize_business_tags(["증권 리서치", "무단 태그"]), ["증권 리서치"])
        self.assertEqual(normalize_business_tags("증권 리서치"), [])
        self.assertEqual(len(normalize_business_tags(list(ALLOWED_BUSINESS_TAGS))), 3)

        articles = _articles()
        payload = _payload(articles)
        payload["trends"][0]["related_business_tags"] = ["증권 리서치", "우리가 만든 태그"]
        result = validate_trend_payload(payload, articles)
        self.assertEqual(result["trends"][0]["related_business_tags"], ["증권 리서치"])

    def test_parse_structured_json_strips_code_fences(self) -> None:
        parsed = parse_structured_json('```json\n{"trends": []}\n```')
        self.assertEqual(parsed, {"trends": []})
        with self.assertRaises(ValueError):
            parse_structured_json("not json")


class ClusterCallTest(unittest.TestCase):
    def test_cluster_trends_uses_the_injected_client(self) -> None:
        articles = _articles()
        body = json.dumps(_payload(articles), ensure_ascii=False)

        class FakeCompletions:
            called = False

            def create(self, **kwargs):
                self.called = True
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=body))]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = cluster_trends(articles, client=client, model="test-model")

        self.assertTrue(completions.called)
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(len(result["trends"]), TREND_COUNT)
        self.assertEqual(result["analyzed_article_count"], len(articles))

    def test_too_few_articles_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cluster_trends(_articles(2), client=object())


if __name__ == "__main__":
    unittest.main()
