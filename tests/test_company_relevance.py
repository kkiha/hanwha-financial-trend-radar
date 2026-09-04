from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest

from rag_finance.llm.company_relevance import (
    ARTICLE_SUMMARY_MAX_CHARS,
    build_relevance_messages,
    build_relevance_response_format,
    classify_company_relevance,
    compute_evidence_metrics,
    select_representative_articles,
    validate_relevance_payload,
)
from rag_finance.profiles.company_profiles import load_all_company_profiles


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _articles() -> list[dict]:
    return [
        {
            "article_id": f"A{index:02d}",
            "title": f"기사 {index}",
            "source": f"출처 {index % 3}",
            "published_at": (
                "2026-09-04T06:00:00+00:00"
                if index <= 3
                else "2026-08-30T06:00:00+00:00"
            ),
            "summary": f"기사 {index} 요약",
            "candidate_companies": ["hanwha_life"],
            "matched_topic_ids": ["life_alm_kics"],
            "matched_query_ids": ["query_not_sent"],
        }
        for index in range(1, 7)
    ]


def _trends() -> dict:
    return {
        "generated_at": "2026-09-04T10:00:00+00:00",
        "trends": [
            {
                "trend_id": f"trend_{index:02d}",
                "title_ko": f"트렌드 {index}",
                "summary_ko": f"트렌드 {index} 요약",
                "why_it_matters_ko": f"트렌드 {index} 중요성",
                "article_ids": [f"A{index * 2 - 1:02d}", f"A{index * 2:02d}"],
            }
            for index in range(1, 4)
        ],
    }


def _payload(profiles: dict[str, dict]) -> dict:
    evaluations = []
    for trend_index in range(1, 4):
        trend_id = f"trend_{trend_index:02d}"
        evidence_id = f"A{trend_index * 2 - 1:02d}"
        for company_index, company_id in enumerate(sorted(profiles), start=1):
            profile = profiles[company_id]
            evaluations.append(
                {
                    "trend_id": trend_id,
                    "company_id": company_id,
                    "relevance": "high",
                    "reason_ko": (
                        f"트렌드 {trend_index}은 {profile['company_name']}의 "
                        f"사업 경로 {company_index}에 영향을 줄 가능성이 있다."
                    ),
                    "transmission_path_ko": "시장 변화 → 사업 영향 가능성 → 관리 지표 검토",
                    "matched_topic_ids": [profile["watch_topics"][0]["id"]],
                    "business_tags": [profile["business_tags"][0]],
                    "evidence_article_ids": [evidence_id],
                }
            )
    return {"evaluations": evaluations}


def _company_payload(profiles: dict[str, dict], company_id: str) -> dict:
    return {
        "evaluations": [
            item
            for item in _payload(profiles)["evaluations"]
            if item["company_id"] == company_id
        ]
    }


def _client_with_payloads(*payloads: dict):
    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.payloads = iter(payloads)

        def create(self, **kwargs):
            self.calls.append(kwargs)
            body = json.dumps(next(self.payloads), ensure_ascii=False)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=body), finish_reason="stop"
                    )
                ]
            )

    completions = FakeCompletions()
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class PromptContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = load_all_company_profiles()

    def test_prompt_contains_only_runtime_relevance_fields(self) -> None:
        company_id = sorted(self.profiles)[0]
        messages = build_relevance_messages(
            _trends(), _articles(), {company_id: self.profiles[company_id]}
        )
        sent = json.loads(messages[1]["content"])

        self.assertEqual(len(sent["trends"]), 3)
        self.assertNotIn("company_profiles", sent)
        self.assertEqual(sent["company_profile"]["company_id"], company_id)
        self.assertEqual(
            set(sent["trends"][0]["articles"][0]),
            {
                "article_id",
                "title",
                "source",
                "published_at",
                "summary",
                "candidate_companies",
                "matched_topic_ids",
            },
        )
        profile = sent["company_profile"]
        self.assertEqual(
            set(profile),
            {
                "company_id",
                "company_name",
                "profile_summary",
                "business_areas",
                "watch_topics",
                "business_tags",
                "excluded_rules",
            },
        )
        self.assertEqual(set(profile["business_areas"][0]), {"id", "name"})
        self.assertEqual(
            set(profile["watch_topics"][0]), {"id", "name", "transmission"}
        )
        self.assertNotIn("sources", profile)
        self.assertNotIn("rss_queries", profile)
        self.assertNotIn("revenue_drivers", profile)
        self.assertNotIn("matched_query_ids", sent["trends"][0]["articles"][0])
        self.assertFalse(sent["trends"][0]["company_mentioned_in_articles"])
        self.assertIn("회사명이 없다는 이유만으로 none", messages[0]["content"])
        self.assertIn("행동은 기사에 적힌 실제 주체의 행동", messages[0]["content"])

    def test_strict_schema_uses_only_known_ids_and_enum(self) -> None:
        company_id = sorted(self.profiles)[0]
        response_format = build_relevance_response_format(
            _trends(), _articles(), {company_id: self.profiles[company_id]}
        )
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        item = schema["properties"]["evaluations"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(
            item["properties"]["relevance"]["enum"],
            ["high", "medium", "low", "none"],
        )
        self.assertEqual(len(item["properties"]["trend_id"]["enum"]), 3)
        self.assertEqual(item["properties"]["company_id"]["enum"], [company_id])
        self.assertEqual(schema["required"], ["evaluations"])

    def test_summary_is_normalized_and_truncated(self) -> None:
        articles = _articles()
        articles[0]["summary"] = "  긴   요약\n" + ("가" * 300)
        company_id = sorted(self.profiles)[0]
        messages = build_relevance_messages(
            _trends(), articles, {company_id: self.profiles[company_id]}
        )
        sent = json.loads(messages[1]["content"])
        summary = sent["trends"][0]["articles"][0]["summary"]
        self.assertLessEqual(len(summary), ARTICLE_SUMMARY_MAX_CHARS)
        self.assertNotIn("\n", summary)
        self.assertNotIn("  ", summary)

    def test_prompt_sends_at_most_three_articles_per_trend(self) -> None:
        articles = _articles()[:5]
        trends = _trends()
        trends["trends"] = [
            {
                "trend_id": "trend_01",
                "title_ko": "트렌드",
                "summary_ko": "요약",
                "why_it_matters_ko": "중요성",
                "article_ids": [article["article_id"] for article in articles],
            }
        ]
        company_id = sorted(self.profiles)[0]
        messages = build_relevance_messages(
            trends, articles, {company_id: self.profiles[company_id]}
        )
        sent = json.loads(messages[1]["content"])
        self.assertEqual(len(sent["trends"][0]["articles"]), 3)


class RepresentativeArticleTest(unittest.TestCase):
    def test_prefers_source_diversity_then_recency_summary_and_id(self) -> None:
        articles = [
            {"article_id": "A04", "source": "S1", "published_at": "2026-09-04T10:00:00Z", "summary": ""},
            {"article_id": "A01", "source": "S1", "published_at": "2026-09-03T10:00:00Z", "summary": "요약"},
            {"article_id": "A03", "source": "S2", "published_at": "2026-09-04T09:00:00Z", "summary": "요약"},
            {"article_id": "A02", "source": "S3", "published_at": "2026-09-04T09:00:00Z", "summary": "요약"},
            {"article_id": "A05", "source": "S4", "published_at": "2026-09-01T09:00:00Z", "summary": "요약"},
        ]
        selected = select_representative_articles(articles)

        self.assertEqual([item["article_id"] for item in selected], ["A04", "A02", "A03"])
        self.assertEqual(len({item["source"] for item in selected}), 3)

    def test_fills_from_same_source_when_fewer_than_three_sources(self) -> None:
        articles = [
            {"article_id": f"A0{i}", "source": "same", "published_at": f"2026-09-0{i}T09:00:00Z", "summary": "요약"}
            for i in range(1, 6)
        ]
        selected = select_representative_articles(articles)
        self.assertEqual([item["article_id"] for item in selected], ["A05", "A04", "A03"])


class ValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()
        self.payload = _payload(self.profiles)

    def _evaluation(self, trend_id="trend_01", company_id=None):
        company_id = company_id or sorted(self.profiles)[0]
        return next(
            item
            for item in self.payload["evaluations"]
            if item["trend_id"] == trend_id and item["company_id"] == company_id
        )

    def test_three_trends_by_three_companies_produce_nine_evaluations(self) -> None:
        result = validate_relevance_payload(
            self.payload, _trends(), _articles(), self.profiles, now=NOW
        )
        self.assertEqual(len(result), 9)
        self.assertEqual(len({(item["trend_id"], item["company_id"]) for item in result}), 9)
        self.assertTrue(all("evidence_metrics" in item for item in result))

    def test_high_and_medium_require_path_topic_tag_and_evidence(self) -> None:
        for relevance in ("high", "medium"):
            with self.subTest(relevance=relevance):
                payload = deepcopy(self.payload)
                item = payload["evaluations"][0]
                item["relevance"] = relevance
                item["evidence_article_ids"] = []
                with self.assertRaisesRegex(ValueError, "requires"):
                    validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_none_requires_empty_path_topics_tags_and_evidence(self) -> None:
        item = self.payload["evaluations"][0]
        item.update(
            relevance="none",
            reason_ko="회사 사업과 구체적인 연결이 없어 제외한다.",
            transmission_path_ko="",
            matched_topic_ids=[],
            business_tags=[],
            evidence_article_ids=[],
        )
        result = validate_relevance_payload(
            self.payload, _trends(), _articles(), self.profiles, now=NOW
        )
        none = next(
            value
            for value in result
            if value["trend_id"] == item["trend_id"]
            and value["company_id"] == item["company_id"]
        )
        self.assertEqual(none["evidence_metrics"]["corroboration"], "none")
        self.assertEqual(none["evidence_metrics"]["article_count"], 0)

        invalid = deepcopy(self.payload)
        invalid["evaluations"][0]["transmission_path_ko"] = "남은 경로"
        with self.assertRaisesRegex(ValueError, "none must"):
            validate_relevance_payload(invalid, _trends(), _articles(), self.profiles)

    def test_unknown_trend_and_company_are_rejected(self) -> None:
        for field, value in (("trend_id", "trend_99"), ("company_id", "ghost_company")):
            with self.subTest(field=field):
                payload = deepcopy(self.payload)
                payload["evaluations"][0][field] = value
                with self.assertRaisesRegex(ValueError, "unknown"):
                    validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_invalid_enum_and_extra_output_fields_are_rejected(self) -> None:
        invalid_enum = deepcopy(self.payload)
        invalid_enum["evaluations"][0]["relevance"] = "critical"
        with self.assertRaisesRegex(ValueError, "invalid relevance"):
            validate_relevance_payload(
                invalid_enum, _trends(), _articles(), self.profiles
            )

        extra = deepcopy(self.payload)
        extra["confidence"] = 0.95
        with self.assertRaisesRegex(ValueError, "only the evaluations"):
            validate_relevance_payload(extra, _trends(), _articles(), self.profiles)

    def test_other_company_topic_is_rejected(self) -> None:
        payload = deepcopy(self.payload)
        item = payload["evaluations"][0]
        other_company = next(cid for cid in self.profiles if cid != item["company_id"])
        item["matched_topic_ids"] = [self.profiles[other_company]["watch_topics"][0]["id"]]
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_unapproved_business_tag_is_rejected(self) -> None:
        payload = deepcopy(self.payload)
        payload["evaluations"][0]["business_tags"] = ["임의 생성 태그"]
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_article_from_another_trend_is_rejected(self) -> None:
        payload = deepcopy(self.payload)
        payload["evaluations"][0]["evidence_article_ids"] = ["A03"]
        with self.assertRaisesRegex(ValueError, "outside trend_01"):
            validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_duplicate_and_missing_combinations_are_rejected(self) -> None:
        duplicate = deepcopy(self.payload)
        duplicate["evaluations"].append(deepcopy(duplicate["evaluations"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_relevance_payload(duplicate, _trends(), _articles(), self.profiles)

        missing = deepcopy(self.payload)
        missing["evaluations"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate_relevance_payload(missing, _trends(), _articles(), self.profiles)

    def test_copied_company_reasons_are_rejected(self) -> None:
        payload = deepcopy(self.payload)
        repeated = "이 트렌드는 세 회사에 모두 같은 영향을 줄 가능성이 있다."
        for item in payload["evaluations"]:
            if item["trend_id"] == "trend_01":
                item["reason_ko"] = repeated
        with self.assertRaisesRegex(ValueError, "Copied"):
            validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_external_actor_action_cannot_be_attributed_directly_to_hanwha(self) -> None:
        payload = deepcopy(self.payload)
        item = payload["evaluations"][0]
        company_name = self.profiles[item["company_id"]]["company_name"]
        item["reason_ko"] = f"{company_name}가 외부 기업의 라이선스를 취득했다."
        item["transmission_path_ko"] = "라이선스 취득 → 사업 진입 확대"

        with self.assertRaisesRegex(ValueError, "conditionally"):
            validate_relevance_payload(payload, _trends(), _articles(), self.profiles)

    def test_absent_company_can_still_be_profile_grounded_indirectly(self) -> None:
        payload = deepcopy(self.payload)
        company_id = "hanwha_asset_management"
        item = next(
            evaluation
            for evaluation in payload["evaluations"]
            if evaluation["trend_id"] == "trend_02"
            and evaluation["company_id"] == company_id
        )
        item.update(
            relevance="medium",
            reason_ko=(
                "기사에 회사명은 없지만 RWA 제도 변화가 토큰증권 상품화 범위에 "
                "영향을 줄 가능성이 있어 검토가 필요하다."
            ),
            transmission_path_ko=(
                "RWA 제도 변화 → 디지털 투자 인프라의 상품화 기회 검토"
            ),
            matched_topic_ids=["fund_digital_investment"],
            business_tags=[self.profiles[company_id]["business_tags"][0]],
            evidence_article_ids=["A03"],
        )

        result = validate_relevance_payload(
            payload, _trends(), _articles(), self.profiles, now=NOW
        )
        validated = next(
            evaluation
            for evaluation in result
            if evaluation["trend_id"] == "trend_02"
            and evaluation["company_id"] == company_id
        )
        self.assertEqual(validated["relevance"], "medium")
        self.assertEqual(validated["matched_topic_ids"], ["fund_digital_investment"])

    def test_metrics_are_computed_from_articles(self) -> None:
        registry = {item["article_id"]: item for item in _articles()}
        metrics = compute_evidence_metrics(["A01", "A02"], registry, now=NOW)
        self.assertEqual(metrics["article_count"], 2)
        self.assertEqual(metrics["source_count"], 2)
        self.assertEqual(metrics["recent_48h_count"], 2)
        self.assertEqual(metrics["recent_48h_share"], 1.0)
        self.assertEqual(metrics["corroboration"], "moderate")


class RelevanceCallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()
        self.company_ids = sorted(self.profiles)

    def test_valid_responses_are_classified_in_three_company_requests(self) -> None:
        client, completions = _client_with_payloads(
            *(_company_payload(self.profiles, company_id) for company_id in self.company_ids)
        )
        result = classify_company_relevance(
            _trends(), _articles(), profiles=self.profiles, client=client, now=NOW
        )

        self.assertEqual(result["status"], "CLASSIFIED")
        self.assertEqual(len(result["evaluations"]), 9)
        self.assertEqual(result["source_trends_generated_at"], _trends()["generated_at"])
        self.assertEqual(len(completions.calls), 3)
        self.assertEqual(set(result["relevance_calls"]), set(self.company_ids))
        for company_id, call in zip(self.company_ids, completions.calls):
            sent = json.loads(call["messages"][1]["content"])
            self.assertEqual(sent["company_profile"]["company_id"], company_id)
            self.assertEqual(len(sent["trends"]), 3)
            self.assertEqual(call["max_tokens"], 1200)
            self.assertEqual(call["reasoning_effort"], "low")
            self.assertEqual(call["response_format"]["type"], "json_schema")
            self.assertTrue(call["response_format"]["json_schema"]["strict"])

    def test_first_invalid_response_then_second_succeeds(self) -> None:
        client, completions = _client_with_payloads(
            {"evaluations": []},
            _company_payload(self.profiles, self.company_ids[0]),
            _company_payload(self.profiles, self.company_ids[1]),
            _company_payload(self.profiles, self.company_ids[2]),
        )
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )

        self.assertEqual(result["status"], "CLASSIFIED")
        self.assertEqual(len(completions.calls), 4)
        self.assertIn("이전 응답", completions.calls[1]["messages"][-1]["content"])

    def test_api_failure_is_retried_once(self) -> None:
        class FakeCompletions:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    raise RuntimeError("temporary API failure")
                call_company = json.loads(kwargs["messages"][1]["content"])[
                    "company_profile"
                ]["company_id"]
                body = json.dumps(
                    _company_payload(self_outer.profiles, call_company),
                    ensure_ascii=False,
                )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=body), finish_reason="stop"
                        )
                    ]
                )

        completions = FakeCompletions()
        self_outer = self
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )

        self.assertEqual(len(completions.calls), 4)
        self.assertEqual(result["status"], "CLASSIFIED")

    def test_one_company_failing_twice_yields_partial_not_unclassified(self) -> None:
        # The first company exhausts both attempts with an invalid payload; the
        # other two succeed. Their results must survive, not be discarded.
        client, completions = _client_with_payloads(
            {"evaluations": []},
            {"evaluations": []},
            _company_payload(self.profiles, self.company_ids[1]),
            _company_payload(self.profiles, self.company_ids[2]),
        )
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )

        self.assertEqual(len(completions.calls), 4)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(result["evaluations"])
        evaluated_companies = {item["company_id"] for item in result["evaluations"]}
        self.assertEqual(evaluated_companies, {self.company_ids[1], self.company_ids[2]})
        self.assertNotIn(self.company_ids[0], evaluated_companies)
        self.assertEqual(result["error"]["type"], "PartialClassification")
        self.assertIn(self.company_ids[0], result["error"]["message"])
        self.assertEqual(result["relevance_calls"][self.company_ids[0]]["status"], "failed")

    def test_all_companies_failing_still_returns_unclassified(self) -> None:
        client, completions = _client_with_payloads(
            {"evaluations": []},
            {"evaluations": []},
            {"evaluations": []},
            {"evaluations": []},
            {"evaluations": []},
            {"evaluations": []},
        )
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )

        self.assertEqual(result["status"], "UNCLASSIFIED")
        self.assertEqual(result["evaluations"], [])
        self.assertEqual(result["error"]["type"], "ValueError")
        self.assertNotIn("evaluations", result["error"]["message"])

    def test_failed_company_only_is_retried_and_successes_are_not_recalled(self) -> None:
        client, completions = _client_with_payloads(
            _company_payload(self.profiles, self.company_ids[0]),
            {"evaluations": []},
            {"evaluations": []},
            _company_payload(self.profiles, self.company_ids[2]),
        )
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )

        called_companies = [
            json.loads(call["messages"][1]["content"])["company_profile"]["company_id"]
            for call in completions.calls
        ]
        self.assertEqual(
            called_companies,
            [self.company_ids[0], self.company_ids[1], self.company_ids[1], self.company_ids[2]],
        )
        self.assertEqual(result["status"], "PARTIAL")
        evaluated_companies = {item["company_id"] for item in result["evaluations"]}
        self.assertEqual(evaluated_companies, {self.company_ids[0], self.company_ids[2]})
        self.assertEqual(result["relevance_calls"][self.company_ids[0]]["status"], "success")
        self.assertEqual(result["relevance_calls"][self.company_ids[1]]["attempts"], 2)
        self.assertEqual(result["relevance_calls"][self.company_ids[1]]["status"], "failed")
        self.assertEqual(result["relevance_calls"][self.company_ids[2]]["status"], "success")
        self.assertIn(self.company_ids[1], result["error"]["message"])

    def test_429_uses_retry_after_for_failed_company_only(self) -> None:
        sleeps: list[float] = []

        class RateLimitError(Exception):
            status_code = 429
            headers = {"retry-after": "2.5"}
            code = "rate_limit_exceeded"

        class FakeCompletions:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def create(fake_self, **kwargs):
                fake_self.calls.append(kwargs)
                if len(fake_self.calls) == 2:
                    raise RateLimitError("limited")
                company_id = json.loads(kwargs["messages"][1]["content"])[
                    "company_profile"
                ]["company_id"]
                body = json.dumps(
                    _company_payload(self.profiles, company_id), ensure_ascii=False
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=body))]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = classify_company_relevance(
            _trends(),
            _articles(),
            profiles=self.profiles,
            client=client,
            sleep_fn=sleeps.append,
            now=NOW,
        )

        self.assertEqual(result["status"], "CLASSIFIED")
        self.assertEqual(sleeps, [2.5])
        second = result["relevance_calls"][self.company_ids[1]]
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(second["wait_seconds"], [2.5])

    def test_413_is_not_retried_and_records_safe_request_diagnostics(self) -> None:
        class PayloadTooLargeError(Exception):
            status_code = 413
            code = "rate_limit_exceeded"

        class FakeCompletions:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def create(fake_self, **kwargs):
                fake_self.calls.append(kwargs)
                company_id = json.loads(kwargs["messages"][1]["content"])[
                    "company_profile"
                ]["company_id"]
                if company_id == self.company_ids[0]:
                    raise PayloadTooLargeError("too large")
                body = json.dumps(
                    _company_payload(self.profiles, company_id), ensure_ascii=False
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=body))]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = classify_company_relevance(
            _trends(), _articles(), profiles=self.profiles, client=client, now=NOW
        )

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(completions.calls), 3)
        failed = result["relevance_calls"][self.company_ids[0]]
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(failed["http_status"], 413)
        evaluated_companies = {item["company_id"] for item in result["evaluations"]}
        self.assertEqual(evaluated_companies, {self.company_ids[1], self.company_ids[2]})
        self.assertEqual(failed["error_code"], "rate_limit_exceeded")
        self.assertGreater(failed["input_chars"], 0)
        self.assertEqual(failed["article_count"], 6)
        self.assertEqual(failed["max_tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
