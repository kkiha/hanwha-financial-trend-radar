from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest

from rag_finance.llm.company_brief import (
    PrerequisiteError,
    build_brief_messages,
    build_brief_response_format,
    build_monitoring_items,
    generate_company_briefs,
    select_brief_candidates,
    validate_and_combine_brief_payload,
    validate_brief_prerequisites,
)
from rag_finance.profiles.company_profiles import load_all_company_profiles


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
TREND_TIME = "2026-09-04T10:00:00+00:00"
RELEVANCE_TIME = "2026-09-04T10:05:00+00:00"


def _articles() -> list[dict]:
    return [
        {
            "article_id": f"A{trend}{article}",
            "title": f"트렌드 {trend} 근거 기사 {article}",
            "source": f"출처 {article}",
            "published_at": "2026-09-04T06:00:00+00:00",
            "summary": f"트렌드 {trend}의 확인된 변화 {article}",
        }
        for trend in range(1, 4)
        for article in range(1, 4)
    ]


def _trends() -> dict:
    return {
        "generated_at": TREND_TIME,
        "trends": [
            {
                "trend_id": f"trend_{index:02d}",
                "title_ko": f"글로벌 트렌드 {index}",
                "summary_ko": f"트렌드 {index}에서 관찰된 변화",
                "why_it_matters_ko": f"금융회사에 중요한 이유 {index}",
                "article_ids": [f"A{index}{article}" for article in range(1, 4)],
            }
            for index in range(1, 4)
        ],
    }


def _metrics(corroboration: str, count: int) -> dict:
    return {
        "article_count": count,
        "source_count": count,
        "recent_48h_count": count,
        "recent_48h_share": 1.0 if count else 0.0,
        "corroboration": corroboration,
    }


def _relevance(
    profiles: dict[str, dict],
    settings: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> dict:
    settings = settings or {}
    evaluations = []
    for trend_index in range(1, 4):
        trend_id = f"trend_{trend_index:02d}"
        for company_id in sorted(profiles):
            level, corroboration = settings.get((trend_id, company_id), ("low", "limited"))
            profile = profiles[company_id]
            if level in {"high", "medium"}:
                count = {"strong": 3, "moderate": 2, "limited": 1}[corroboration]
                topics = [profile["watch_topics"][0]["id"]]
                tags = [profile["business_tags"][0]]
                evidence = [f"A{trend_index}{index}" for index in range(1, count + 1)]
                path = "시장 변화 → 사업 지표 → 회사 영향 가능성"
            else:
                count = 0
                topics = []
                tags = []
                evidence = []
                path = ""
                corroboration = "none" if level == "none" else "limited"
            evaluations.append(
                {
                    "trend_id": trend_id,
                    "company_id": company_id,
                    "relevance": level,
                    "reason_ko": f"{profile['company_name']}의 사업 특성을 반영한 {trend_id} 판단이다.",
                    "transmission_path_ko": path,
                    "matched_topic_ids": topics,
                    "business_tags": tags,
                    "evidence_article_ids": evidence,
                    "evidence_metrics": _metrics(corroboration, count),
                }
            )
    return {
        "generated_at": RELEVANCE_TIME,
        "source_trends_generated_at": TREND_TIME,
        "status": "CLASSIFIED",
        "evaluations": evaluations,
    }


def _partial_relevance(
    profiles: dict[str, dict],
    covered_company_ids: set[str],
    settings: dict[tuple[str, str], tuple[str, str]] | None = None,
) -> dict:
    """A relevance payload as if classify_company_relevance() left out some
    companies (e.g. one failed OpenAI validation twice)."""
    full = _relevance(profiles, settings)
    full["status"] = "PARTIAL"
    full["evaluations"] = [
        item for item in full["evaluations"] if item["company_id"] in covered_company_ids
    ]
    return full


def _prepared(profiles: dict[str, dict], settings):
    trends = _trends()
    articles = _articles()
    relevance = _relevance(profiles, settings)
    context = validate_brief_prerequisites(trends, relevance, articles, profiles)
    selected = select_brief_candidates(context, profiles)
    monitoring = build_monitoring_items(selected, context)
    return trends, articles, relevance, context, selected, monitoring


def _model_payload(selected, profiles) -> dict:
    companies = []
    for company_id, groups in selected.items():
        if not groups["main"]:
            continue
        company_name = profiles[company_id]["company_name"]
        companies.append(
            {
                "company_id": company_id,
                "weekly_summary_ko": f"{company_name} 관점의 핵심 변화로 추가 검토가 필요하다.",
                "briefs": [
                    {
                        "trend_id": item["trend_id"],
                        "headline_ko": f"{item['trend_id']} 사업환경 변화",
                        "situation_ko": f"{item['trend_id']}에서 공통 변화가 확인됐다.",
                        "company_relevance_ko": (
                            f"{item['trend_id']}은 {company_name}의 "
                            f"{item['business_tags'][0]} 업무와 연결될 가능성이 있다."
                        ),
                        "business_impact_ko": (
                            f"{item['trend_id']} 변화가 {company_name}의 관련 지표에 "
                            "미칠 가능성을 살펴볼 수 있다."
                        ),
                        "watch_next": [
                            f"{item['trend_id']} 관련 후속 공시를 확인한다.",
                            f"{item['trend_id']} 관련 시장 반응을 관찰한다.",
                        ],
                    }
                    for item in groups["main"]
                ],
            }
        )
    return {"companies": companies}


def _client_with_payloads(*payloads: dict):
    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.payloads = iter(payloads)

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(next(self.payloads), ensure_ascii=False)
                        ),
                        finish_reason="stop",
                    )
                ]
            )

    completions = FakeCompletions()
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class PrerequisiteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()

    def test_valid_inputs_require_all_nine_evaluations(self) -> None:
        context = validate_brief_prerequisites(
            _trends(), _relevance(self.profiles), _articles(), self.profiles
        )
        self.assertEqual(len(context["evaluations"]), 9)

    def test_all_three_company_profiles_are_required(self) -> None:
        profiles = dict(self.profiles)
        profiles.pop(next(iter(profiles)))
        with self.assertRaisesRegex(PrerequisiteError, "프로파일 3개"):
            validate_brief_prerequisites(
                _trends(), _relevance(self.profiles), _articles(), profiles
            )

    def test_unclassified_and_timestamp_mismatch_stop_before_generation(self) -> None:
        for mutation in ("status", "timestamp"):
            with self.subTest(mutation=mutation):
                relevance = _relevance(self.profiles)
                if mutation == "status":
                    relevance["status"] = "UNCLASSIFIED"
                else:
                    relevance["source_trends_generated_at"] = "2026-09-03T00:00:00Z"
                result = generate_company_briefs(
                    _trends(),
                    relevance,
                    _articles(),
                    profiles=self.profiles,
                    client=object(),
                    now=NOW,
                )
                self.assertEqual(result["status"], "NOT_GENERATED")
                self.assertEqual(result["companies"], [])
                self.assertEqual(result["error"]["type"], "PrerequisiteError")

    def test_unknown_article_trend_and_company_are_rejected(self) -> None:
        mutations = []
        missing_article = _relevance(self.profiles)
        missing_article["evaluations"][0]["evidence_article_ids"] = ["GHOST"]
        mutations.append(missing_article)
        missing_trend = _relevance(self.profiles)
        missing_trend["evaluations"][0]["trend_id"] = "trend_99"
        mutations.append(missing_trend)
        missing_company = _relevance(self.profiles)
        missing_company["evaluations"][0]["company_id"] = "ghost_company"
        mutations.append(missing_company)

        for relevance in mutations:
            with self.assertRaises(PrerequisiteError):
                validate_brief_prerequisites(
                    _trends(), relevance, _articles(), self.profiles
                )

    def test_inconsistent_evidence_metrics_are_rejected(self) -> None:
        company_id = sorted(self.profiles)[0]
        relevance = _relevance(
            self.profiles,
            {("trend_01", company_id): ("high", "moderate")},
        )
        item = next(
            value
            for value in relevance["evaluations"]
            if value["trend_id"] == "trend_01" and value["company_id"] == company_id
        )
        item["evidence_metrics"]["article_count"] = 99
        with self.assertRaisesRegex(PrerequisiteError, "통계"):
            validate_brief_prerequisites(
                _trends(), relevance, _articles(), self.profiles
            )

    def test_partial_relevance_scopes_completeness_to_covered_companies(self) -> None:
        # One company's relevance classification failed upstream and was left
        # out entirely; the other two must still validate as complete.
        covered = set(sorted(self.profiles)[:2])
        relevance = _partial_relevance(self.profiles, covered)

        context = validate_brief_prerequisites(
            _trends(), relevance, _articles(), self.profiles
        )

        self.assertEqual(context["covered_company_ids"], covered)
        self.assertEqual(len(context["evaluations"]), 3 * len(covered))
        self.assertTrue(
            all(company_id in covered for _, company_id in context["evaluations"])
        )

    def test_relevance_covering_no_company_is_rejected(self) -> None:
        relevance = _partial_relevance(self.profiles, set())
        with self.assertRaisesRegex(PrerequisiteError, "어떤 회사도"):
            validate_brief_prerequisites(
                _trends(), relevance, _articles(), self.profiles
            )


class CandidateSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()
        self.company_id = sorted(self.profiles)[0]

    def test_high_strong_and_moderate_become_main_with_max_two(self) -> None:
        settings = {
            ("trend_01", self.company_id): ("high", "moderate"),
            ("trend_02", self.company_id): ("high", "strong"),
            ("trend_03", self.company_id): ("high", "strong"),
        }
        _, _, _, _, selected, _ = _prepared(self.profiles, settings)
        main = selected[self.company_id]["main"]
        self.assertEqual(len(main), 2)
        self.assertEqual([item["trend_id"] for item in main], ["trend_02", "trend_03"])

        moderate_only = {
            ("trend_01", self.company_id): ("high", "moderate"),
        }
        _, _, _, _, selected_moderate, _ = _prepared(
            self.profiles, moderate_only
        )
        self.assertEqual(
            [item["trend_id"] for item in selected_moderate[self.company_id]["main"]],
            ["trend_01"],
        )

    def test_medium_and_high_limited_become_monitoring_low_none_are_excluded(self) -> None:
        settings = {
            ("trend_01", self.company_id): ("high", "limited"),
            ("trend_02", self.company_id): ("medium", "limited"),
            ("trend_03", self.company_id): ("none", "none"),
        }
        _, _, _, _, selected, monitoring = _prepared(self.profiles, settings)
        self.assertEqual(selected[self.company_id]["main"], [])
        self.assertEqual(
            [item["trend_id"] for item in selected[self.company_id]["monitoring"]],
            ["trend_02", "trend_01"],
        )
        self.assertEqual(len(monitoring[self.company_id]), 2)
        self.assertNotIn("trend_03", {item["trend_id"] for item in monitoring[self.company_id]})

    def test_monitoring_is_capped_at_two_and_selection_is_deterministic(self) -> None:
        settings = {
            (f"trend_{index:02d}", self.company_id): ("medium", "limited")
            for index in range(1, 4)
        }
        _, _, _, context, first, _ = _prepared(self.profiles, settings)
        second = select_brief_candidates(context, self.profiles)
        self.assertEqual(first, second)
        self.assertEqual(len(first[self.company_id]["monitoring"]), 2)

    def test_no_main_candidate_does_not_force_a_brief_or_call_openai(self) -> None:
        settings = {
            ("trend_01", self.company_id): ("medium", "limited"),
        }
        result = generate_company_briefs(
            _trends(),
            _relevance(self.profiles, settings),
            _articles(),
            profiles=self.profiles,
            client=object(),
            now=NOW,
        )
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(len(result["companies"]), 3)
        self.assertTrue(all(not company["briefs"] for company in result["companies"]))
        self.assertTrue(all(company["weekly_summary_ko"] == "" for company in result["companies"]))


class PromptAndValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()
        self.company_id = sorted(self.profiles)[0]
        self.settings = {("trend_01", self.company_id): ("high", "strong")}
        (
            self.trends,
            self.articles,
            self.relevance,
            self.context,
            self.selected,
            self.monitoring,
        ) = _prepared(self.profiles, self.settings)
        self.payload = _model_payload(self.selected, self.profiles)

    def test_prompt_contains_only_selected_main_candidates_and_scoped_profile(self) -> None:
        messages = build_brief_messages(
            self.selected, self.context, self.profiles
        )
        sent = json.loads(messages[1]["content"])
        self.assertEqual(len(sent["brief_candidates"]), 1)
        candidate = sent["brief_candidates"][0]
        self.assertEqual(candidate["trend"]["trend_id"], "trend_01")
        self.assertEqual(len(candidate["articles"]), 3)
        self.assertNotIn("sources", candidate["company_profile"])
        self.assertNotIn("rss_queries", candidate["company_profile"])
        self.assertTrue(
            all("source_ids" not in topic for topic in candidate["company_profile"]["watch_topics"])
        )
        self.assertFalse(candidate["company_mentioned_in_articles"])
        self.assertIn("행동 주체를 바꾸지 마라", messages[0]["content"])
        self.assertIn("조건부로만 표현", messages[0]["content"])

    def test_strict_schema_contains_no_model_owned_tags_or_evidence(self) -> None:
        response_format = build_brief_response_format(self.selected)
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        brief = schema["properties"]["companies"]["items"]["properties"]["briefs"]["items"]
        self.assertFalse(brief["additionalProperties"])
        self.assertNotIn("business_tags", brief["properties"])
        self.assertNotIn("evidence_article_ids", brief["properties"])
        self.assertNotIn("relevance", brief["properties"])

    def test_model_prose_is_combined_with_exact_relevance_fields(self) -> None:
        companies = validate_and_combine_brief_payload(
            self.payload,
            self.selected,
            self.context,
            self.profiles,
            self.monitoring,
        )
        company = next(item for item in companies if item["company_id"] == self.company_id)
        brief = company["briefs"][0]
        evaluation = self.selected[self.company_id]["main"][0]
        self.assertEqual(brief["brief_id"], f"{self.company_id}__trend_01")
        self.assertEqual(brief["business_tags"], evaluation["business_tags"])
        self.assertEqual(brief["evidence_article_ids"], evaluation["evidence_article_ids"])
        self.assertEqual(brief["evidence_metrics"], evaluation["evidence_metrics"])

    def test_unselected_missing_and_duplicate_briefs_are_rejected(self) -> None:
        unselected = deepcopy(self.payload)
        unselected["companies"][0]["briefs"][0]["trend_id"] = "trend_02"
        with self.assertRaisesRegex(ValueError, "unselected"):
            validate_and_combine_brief_payload(
                unselected, self.selected, self.context, self.profiles, self.monitoring
            )

        missing = deepcopy(self.payload)
        missing["companies"][0]["briefs"] = []
        with self.assertRaisesRegex(ValueError, "every selected"):
            validate_and_combine_brief_payload(
                missing, self.selected, self.context, self.profiles, self.monitoring
            )

        duplicate = deepcopy(self.payload)
        duplicate["companies"][0]["briefs"].append(
            deepcopy(duplicate["companies"][0]["briefs"][0])
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_and_combine_brief_payload(
                duplicate, self.selected, self.context, self.profiles, self.monitoring
            )

    def test_lengths_watch_count_and_extra_fields_are_rejected(self) -> None:
        cases = []
        too_long = deepcopy(self.payload)
        too_long["companies"][0]["briefs"][0]["headline_ko"] = "가" * 46
        cases.append(too_long)
        one_watch = deepcopy(self.payload)
        one_watch["companies"][0]["briefs"][0]["watch_next"] = ["한 가지 관찰사항"]
        cases.append(one_watch)
        extra = deepcopy(self.payload)
        extra["companies"][0]["briefs"][0]["business_tags"] = ["임의 태그"]
        cases.append(extra)
        for payload in cases:
            with self.assertRaises(ValueError):
                validate_and_combine_brief_payload(
                    payload, self.selected, self.context, self.profiles, self.monitoring
                )

    def test_repeated_prose_within_and_across_companies_is_rejected(self) -> None:
        two_trends = {
            ("trend_01", self.company_id): ("high", "strong"),
            ("trend_02", self.company_id): ("high", "moderate"),
        }
        _, _, _, context, selected, monitoring = _prepared(self.profiles, two_trends)
        same_company = _model_payload(selected, self.profiles)
        briefs = same_company["companies"][0]["briefs"]
        briefs[1]["situation_ko"] = briefs[0]["situation_ko"]
        with self.assertRaisesRegex(ValueError, "Repeated situation"):
            validate_and_combine_brief_payload(
                same_company, selected, context, self.profiles, monitoring
            )

        second_company = sorted(self.profiles)[1]
        cross_settings = {
            ("trend_01", self.company_id): ("high", "strong"),
            ("trend_01", second_company): ("high", "strong"),
        }
        _, _, _, context, selected, monitoring = _prepared(self.profiles, cross_settings)
        cross_company = _model_payload(selected, self.profiles)
        first = cross_company["companies"][0]["briefs"][0]
        second = cross_company["companies"][1]["briefs"][0]
        second["company_relevance_ko"] = first["company_relevance_ko"]
        with self.assertRaisesRegex(ValueError, "copied across companies"):
            validate_and_combine_brief_payload(
                cross_company, selected, context, self.profiles, monitoring
            )

    def test_external_actor_action_is_not_rewritten_as_company_action(self) -> None:
        unsupported = deepcopy(self.payload)
        company_name = self.profiles[self.company_id]["company_name"]
        unsupported["companies"][0]["weekly_summary_ko"] = (
            f"{company_name}가 외부 기업의 라이선스를 취득하고 협력을 추진 중이다."
        )
        unsupported["companies"][0]["briefs"][0]["situation_ko"] = (
            f"{company_name}가 외부 기업의 라이선스를 취득했다."
        )

        with self.assertRaisesRegex(ValueError, "unsupported direct action"):
            validate_and_combine_brief_payload(
                unsupported,
                self.selected,
                self.context,
                self.profiles,
                self.monitoring,
            )

    def test_same_company_shared_evidence_and_metrics_are_preserved(self) -> None:
        trends = _trends()
        trends["trends"][1]["article_ids"].append("A11")
        settings = {
            ("trend_01", self.company_id): ("high", "strong"),
            ("trend_02", self.company_id): ("high", "moderate"),
        }
        relevance = _relevance(self.profiles, settings)
        second = next(
            item
            for item in relevance["evaluations"]
            if item["trend_id"] == "trend_02" and item["company_id"] == self.company_id
        )
        second["evidence_article_ids"] = ["A11", "A22"]
        context = validate_brief_prerequisites(
            trends, relevance, _articles(), self.profiles
        )
        selected = select_brief_candidates(context, self.profiles)
        monitoring = build_monitoring_items(selected, context)
        payload = _model_payload(selected, self.profiles)
        companies = validate_and_combine_brief_payload(
            payload, selected, context, self.profiles, monitoring
        )
        company = next(item for item in companies if item["company_id"] == self.company_id)
        by_trend = {item["trend_id"]: item for item in company["briefs"]}
        evaluation_by_trend = {
            item["trend_id"]: item for item in selected[self.company_id]["main"]
        }
        self.assertIn("A11", by_trend["trend_01"]["evidence_article_ids"])
        self.assertIn("A11", by_trend["trend_02"]["evidence_article_ids"])
        for trend_id, brief in by_trend.items():
            evaluation = evaluation_by_trend[trend_id]
            self.assertEqual(
                brief["evidence_article_ids"], evaluation["evidence_article_ids"]
            )
            self.assertEqual(brief["evidence_metrics"], evaluation["evidence_metrics"])
            self.assertEqual(
                brief["evidence_metrics"]["article_count"],
                len(brief["evidence_article_ids"]),
            )
            sources = {
                self.context["articles"][article_id]["source"]
                for article_id in brief["evidence_article_ids"]
            }
            self.assertEqual(brief["evidence_metrics"]["source_count"], len(sources))


class GenerationCallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = load_all_company_profiles()
        self.company_id = sorted(self.profiles)[0]
        self.settings = {("trend_01", self.company_id): ("high", "strong")}
        _, _, _, context, selected, _ = _prepared(self.profiles, self.settings)
        self.good_payload = _model_payload(selected, self.profiles)

    def test_first_invalid_response_then_second_succeeds(self) -> None:
        client, completions = _client_with_payloads(
            {"companies": []}, self.good_payload
        )
        result = generate_company_briefs(
            _trends(),
            _relevance(self.profiles, self.settings),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(len(completions.calls), 2)
        self.assertIn("이전 응답", completions.calls[1]["messages"][-1]["content"])
        self.assertEqual(completions.calls[0]["max_completion_tokens"], 4000)

    def test_two_failures_preserve_company_states_without_raw_response(self) -> None:
        client, completions = _client_with_payloads(
            {"companies": []}, {"companies": []}
        )
        result = generate_company_briefs(
            _trends(),
            _relevance(self.profiles, self.settings),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )
        self.assertEqual(len(completions.calls), 2)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(len(result["companies"]), 3)
        failed = next(c for c in result["companies"] if c["company_id"] == self.company_id)
        self.assertEqual(failed["generation_status"], "PARTIAL")
        self.assertEqual(failed["briefs"], [])
        self.assertEqual(failed["failed_briefs"], ["trend_01"])
        self.assertNotIn("raw_response", result)

    def test_api_failure_is_retried_once(self) -> None:
        body = json.dumps(self.good_payload, ensure_ascii=False)

        class FakeCompletions:
            def __init__(self) -> None:
                self.calls = 0

            def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary API failure")
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=body), finish_reason="stop"
                        )
                    ]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = generate_company_briefs(
            _trends(),
            _relevance(self.profiles, self.settings),
            _articles(),
            profiles=self.profiles,
            client=client,
            retry_base_delay=0,
            now=NOW,
        )
        self.assertEqual(completions.calls, 2)
        self.assertEqual(result["status"], "GENERATED")

    def test_partial_relevance_produces_briefs_only_for_covered_companies(self) -> None:
        # Mirrors classify_company_relevance() returning status="PARTIAL" after
        # one company failed twice: briefs must still be generated for the
        # companies that did classify, and the missing company must simply be
        # absent from the result (the UI renders that as "no data"), not an
        # error that blocks its siblings.
        covered = set(sorted(self.profiles)[:2])
        settings = {(f"trend_{i:02d}", cid): ("high", "strong") for i in range(1, 4) for cid in covered}
        relevance = _partial_relevance(self.profiles, covered, settings)
        context = validate_brief_prerequisites(_trends(), relevance, _articles(), self.profiles)
        scoped_profiles = {cid: self.profiles[cid] for cid in covered}
        selected = select_brief_candidates(context, scoped_profiles)
        payload = _model_payload(selected, self.profiles)

        client, completions = _client_with_payloads(payload)
        result = generate_company_briefs(
            _trends(),
            relevance,
            _articles(),
            profiles=self.profiles,
            client=client,
            now=NOW,
        )

        self.assertEqual(result["status"], "GENERATED")
        returned_ids = {company["company_id"] for company in result["companies"]}
        self.assertEqual(returned_ids, covered)
        for company in result["companies"]:
            self.assertTrue(company["briefs"])


if __name__ == "__main__":
    unittest.main()
