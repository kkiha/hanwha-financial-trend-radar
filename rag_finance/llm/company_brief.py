"""Generate grounded company briefs from trends and classified relevance.

Candidate selection, monitoring items, IDs, tags, evidence, and metrics are owned
by code. The model writes prose only for preselected main brief candidates.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Mapping, Sequence

from rag_finance.llm.grounding import (
    uses_indirect_language as _uses_indirect_language, CONDITIONAL_GUIDANCE,
)

from rag_finance.llm.openai_runtime import (
    create_client, resolve_api_key, completion_options, api_error_message, complete,
    is_permanent_api_error,
)

from rag_finance.llm.trend_clusterer import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_TEMPERATURE,
    parse_structured_json,
)
from rag_finance.profiles.company_profiles import (
    DEFAULT_PROFILES_DIR,
    load_all_company_profiles,
)


MAIN_BRIEF_LIMIT = 2
MONITORING_LIMIT = 2
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_BRIEF_MAX_TOKENS = 4000
ARTICLE_SUMMARY_MAX_CHARS = 320
MAX_LENGTHS = {
    "weekly_summary_ko": 240,
    "headline_ko": 45,
    "situation_ko": 220,
    "company_relevance_ko": 220,
    "business_impact_ko": 220,
    "watch_next": 90,
}
BRIEF_TEXT_FIELDS = (
    "headline_ko",
    "situation_ko",
    "company_relevance_ko",
    "business_impact_ko",
)
MODEL_BRIEF_FIELDS = {"trend_id", *BRIEF_TEXT_FIELDS, "watch_next"}
MODEL_COMPANY_FIELDS = {"company_id", "weekly_summary_ko", "briefs"}
CORROBORATION_ORDER = {"strong": 0, "moderate": 1, "limited": 2, "none": 3}
EXPECTED_COMPANY_IDS = {
    "hanwha_life",
    "hanwha_asset_management",
    "hanwha_investment",
}



class PrerequisiteError(ValueError):
    """Trend, relevance, article, or profile inputs cannot safely produce briefs."""


def _non_empty_string(value: Any, *, field: str, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if maximum is not None and len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if re.search(r"[가-힣]", normalized) is None:
        raise ValueError(f"{field} must contain Korean text")
    return normalized


def _unique_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise PrerequisiteError(f"{field} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise PrerequisiteError(f"{field} must contain non-empty strings")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise PrerequisiteError(f"{field} contains duplicate values")
    return result


def _count_metric(metrics: Mapping[str, Any], field: str) -> int:
    value = metrics.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PrerequisiteError(f"evidence_metrics.{field} must be a non-negative integer")
    return value


def validate_brief_prerequisites(
    trends_payload: Mapping[str, Any],
    relevance_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate generation timestamps and every relevance reference before OpenAI."""
    trends_generated_at = trends_payload.get("generated_at")
    relevance_source_at = relevance_payload.get("source_trends_generated_at")
    if not isinstance(trends_generated_at, str) or not trends_generated_at.strip():
        raise PrerequisiteError("트렌드 생성 시각이 없습니다.")
    if trends_generated_at != relevance_source_at:
        raise PrerequisiteError("관련성 결과와 트렌드 생성 시점이 일치하지 않습니다.")
    if relevance_payload.get("status") not in {"CLASSIFIED", "PARTIAL"}:
        raise PrerequisiteError("관련성 분류 상태가 CLASSIFIED 또는 PARTIAL이 아닙니다.")
    if set(profiles) != EXPECTED_COMPANY_IDS:
        missing = sorted(EXPECTED_COMPANY_IDS - set(profiles))
        extra = sorted(set(profiles) - EXPECTED_COMPANY_IDS)
        raise PrerequisiteError(
            f"필수 회사 프로파일 3개가 일치하지 않습니다: missing={missing}, extra={extra}"
        )

    raw_trends = trends_payload.get("trends")
    if not isinstance(raw_trends, list) or not raw_trends:
        raise PrerequisiteError("트렌드 목록이 비어 있습니다.")
    article_registry = {
        str(article["article_id"]): dict(article)
        for article in articles
        if isinstance(article, Mapping) and article.get("article_id")
    }
    trends: dict[str, dict[str, Any]] = {}
    trend_order: dict[str, int] = {}
    for index, raw in enumerate(raw_trends, start=1):
        if not isinstance(raw, Mapping):
            raise PrerequisiteError(f"트렌드 #{index}가 객체가 아닙니다.")
        trend_id = str(raw.get("trend_id") or "").strip()
        if not trend_id or trend_id in trends:
            raise PrerequisiteError(f"트렌드 ID가 없거나 중복되었습니다: {trend_id!r}")
        linked_ids = _unique_string_list(
            raw.get("article_ids"), field=f"{trend_id}.article_ids"
        )
        missing_articles = sorted(set(linked_ids) - set(article_registry))
        if missing_articles:
            raise PrerequisiteError(
                f"{trend_id}에 존재하지 않는 기사 ID가 있습니다: {', '.join(missing_articles)}"
            )
        trend = dict(raw)
        trend["article_ids"] = linked_ids
        trends[trend_id] = trend
        rank = raw.get("rank")
        trend_order[trend_id] = (
            int(rank) if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 else index
        )

    profile_ids = set(profiles)
    for company_id, profile in profiles.items():
        if profile.get("company_id") != company_id:
            raise PrerequisiteError(f"회사 프로파일 ID가 키와 다릅니다: {company_id}")

    raw_evaluations = relevance_payload.get("evaluations")
    if not isinstance(raw_evaluations, list):
        raise PrerequisiteError("관련성 evaluations가 배열이 아닙니다.")
    covered_company_ids = {
        str(raw.get("company_id"))
        for raw in raw_evaluations
        if isinstance(raw, Mapping) and raw.get("company_id") in profile_ids
    }
    if not covered_company_ids:
        raise PrerequisiteError("관련성 평가가 어떤 회사도 포함하지 않습니다.")
    expected_pairs = {
        (trend_id, company_id) for trend_id in trends for company_id in covered_company_ids
    }
    evaluations: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(raw_evaluations, start=1):
        if not isinstance(raw, Mapping):
            raise PrerequisiteError(f"관련성 평가 #{index}가 객체가 아닙니다.")
        trend_id = str(raw.get("trend_id") or "")
        company_id = str(raw.get("company_id") or "")
        if trend_id not in trends:
            raise PrerequisiteError(f"관련성 평가가 존재하지 않는 트렌드를 참조합니다: {trend_id}")
        if company_id not in profile_ids:
            raise PrerequisiteError(f"관련성 평가가 존재하지 않는 회사를 참조합니다: {company_id}")
        pair = (trend_id, company_id)
        if pair in evaluations:
            raise PrerequisiteError(f"관련성 평가 조합이 중복되었습니다: {pair}")

        relevance = raw.get("relevance")
        if relevance not in {"high", "medium", "low", "none"}:
            raise PrerequisiteError(f"허용되지 않은 관련성 등급입니다: {relevance!r}")
        topic_ids = _unique_string_list(
            raw.get("matched_topic_ids"), field=f"evaluation[{pair}].matched_topic_ids"
        )
        tags = _unique_string_list(
            raw.get("business_tags"), field=f"evaluation[{pair}].business_tags"
        )
        evidence_ids = _unique_string_list(
            raw.get("evidence_article_ids"), field=f"evaluation[{pair}].evidence_article_ids"
        )
        allowed_topics = {
            str(topic["id"])
            for topic in profiles[company_id].get("watch_topics", [])
            if isinstance(topic, Mapping) and topic.get("id")
        }
        if not set(topic_ids) <= allowed_topics:
            raise PrerequisiteError(f"{pair}가 다른 회사의 감시주제를 참조합니다.")
        allowed_tags = {str(tag) for tag in profiles[company_id].get("business_tags", [])}
        if not set(tags) <= allowed_tags:
            raise PrerequisiteError(f"{pair}가 허용되지 않은 업무 태그를 참조합니다.")
        if not set(evidence_ids) <= set(trends[trend_id]["article_ids"]):
            raise PrerequisiteError(f"{pair}가 다른 트렌드의 근거 기사를 참조합니다.")
        if not set(evidence_ids) <= set(article_registry):
            raise PrerequisiteError(f"{pair}가 존재하지 않는 근거 기사를 참조합니다.")

        reason = raw.get("reason_ko")
        transmission = raw.get("transmission_path_ko")
        if not isinstance(reason, str) or not reason.strip():
            raise PrerequisiteError(f"{pair}에 관련성 판단 이유가 없습니다.")
        if not isinstance(transmission, str):
            raise PrerequisiteError(f"{pair}의 전이 경로가 문자열이 아닙니다.")
        if relevance in {"high", "medium"} and (
            not transmission.strip() or not topic_ids or not tags or not evidence_ids
        ):
            raise PrerequisiteError(f"{pair}의 {relevance} 평가 근거가 불완전합니다.")
        if relevance == "none" and (transmission.strip() or topic_ids or tags or evidence_ids):
            raise PrerequisiteError(f"{pair}의 none 평가에 근거 필드가 남아 있습니다.")

        metrics = raw.get("evidence_metrics")
        if not isinstance(metrics, Mapping):
            raise PrerequisiteError(f"{pair}에 evidence_metrics가 없습니다.")
        article_count = _count_metric(metrics, "article_count")
        source_count = _count_metric(metrics, "source_count")
        recent_count = _count_metric(metrics, "recent_48h_count")
        recent_share = metrics.get("recent_48h_share")
        if (
            not isinstance(recent_share, (int, float))
            or isinstance(recent_share, bool)
            or not 0 <= float(recent_share) <= 1
        ):
            raise PrerequisiteError(
                "evidence_metrics.recent_48h_share must be between 0 and 1"
            )
        actual_sources = {
            str(article_registry[article_id].get("source") or "").strip()
            for article_id in evidence_ids
        }
        actual_sources.discard("")
        if article_count != len(evidence_ids) or source_count != len(actual_sources):
            raise PrerequisiteError(f"{pair}의 근거 기사·출처 통계가 실제 근거와 다릅니다.")
        if recent_count > article_count:
            raise PrerequisiteError(f"{pair}의 최근 기사 수가 전체 기사 수보다 큽니다.")
        expected_share = round(recent_count / article_count, 4) if article_count else 0.0
        if abs(float(recent_share) - expected_share) > 0.0001:
            raise PrerequisiteError(f"{pair}의 최근 기사 비중이 기사 수와 일치하지 않습니다.")
        corroboration = metrics.get("corroboration")
        if corroboration not in CORROBORATION_ORDER:
            raise PrerequisiteError(f"{pair}의 corroboration이 유효하지 않습니다.")
        expected_corroboration = (
            "none"
            if relevance == "none"
            else "strong"
            if article_count >= 3 and source_count >= 2
            else "moderate"
            if article_count >= 2 and source_count >= 2
            else "limited"
        )
        if corroboration != expected_corroboration:
            raise PrerequisiteError(f"{pair}의 corroboration과 근거 통계가 일치하지 않습니다.")

        evaluation = dict(raw)
        evaluation["matched_topic_ids"] = topic_ids
        evaluation["business_tags"] = tags
        evaluation["evidence_article_ids"] = evidence_ids
        evaluation["evidence_metrics"] = dict(metrics)
        evaluations[pair] = evaluation

    actual_pairs = set(evaluations)
    if actual_pairs != expected_pairs:
        missing = sorted(expected_pairs - actual_pairs)
        extra = sorted(actual_pairs - expected_pairs)
        raise PrerequisiteError(
            f"관련성 평가 조합이 완전하지 않습니다: missing={missing}, extra={extra}"
        )
    return {
        "trends": trends,
        "trend_order": trend_order,
        "articles": article_registry,
        "evaluations": evaluations,
        "covered_company_ids": covered_company_ids,
    }


def _candidate_sort_key(
    evaluation: Mapping[str, Any], trend_order: Mapping[str, int]
) -> tuple[Any, ...]:
    metrics = evaluation["evidence_metrics"]
    return (
        CORROBORATION_ORDER[str(metrics["corroboration"])],
        -float(metrics["source_count"]),
        -float(metrics["article_count"]),
        -float(metrics["recent_48h_share"]),
        trend_order[str(evaluation["trend_id"])],
        str(evaluation["trend_id"]),
    )


def select_brief_candidates(
    context: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Select main and monitoring candidates deterministically, without an LLM."""
    trend_order = context["trend_order"]
    evaluations = context["evaluations"]
    selected: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for company_id in sorted(profiles):
        company_evaluations = [
            dict(evaluation)
            for (trend_id, evaluated_company), evaluation in evaluations.items()
            if evaluated_company == company_id
        ]
        main = [
            item
            for item in company_evaluations
            if item["relevance"] == "high"
            and item["evidence_metrics"]["corroboration"] in {"strong", "moderate"}
            and item["evidence_article_ids"]
            and item["matched_topic_ids"]
            and item["business_tags"]
        ]
        main.sort(key=lambda item: _candidate_sort_key(item, trend_order))

        monitoring = [
            item
            for item in company_evaluations
            if item["relevance"] == "medium"
            or (
                item["relevance"] == "high"
                and item["evidence_metrics"]["corroboration"] == "limited"
            )
        ]
        monitoring.sort(
            key=lambda item: (
                0 if item["relevance"] == "medium" else 1,
                *_candidate_sort_key(item, trend_order),
            )
        )
        selected[company_id] = {
            "main": main[:MAIN_BRIEF_LIMIT],
            "monitoring": monitoring[:MONITORING_LIMIT],
        }
    return selected


def build_monitoring_items(
    selected: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    context: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build monitoring items only from existing trend and relevance wording."""
    trends = context["trends"]
    result: dict[str, list[dict[str, Any]]] = {}
    for company_id, groups in selected.items():
        result[company_id] = [
            {
                "trend_id": evaluation["trend_id"],
                "title_ko": trends[evaluation["trend_id"]].get("title_ko", ""),
                "relevance": evaluation["relevance"],
                "reason_ko": evaluation.get("reason_ko", ""),
                "business_tags": list(evaluation["business_tags"]),
                "evidence_article_ids": list(evaluation["evidence_article_ids"]),
                "evidence_metrics": dict(evaluation["evidence_metrics"]),
            }
            for evaluation in groups["monitoring"]
        ]
    return result


def _scoped_candidate(
    evaluation: Mapping[str, Any],
    context: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    trend = context["trends"][evaluation["trend_id"]]
    matched_topic_ids = set(evaluation["matched_topic_ids"])
    topics = [
        {
            key: topic.get(key)
            for key in (
                "id",
                "name",
                "why_it_matters",
                "related_business_ids",
                "transmission",
                "importance_criteria",
            )
        }
        for topic in profile.get("watch_topics", [])
        if isinstance(topic, Mapping) and topic.get("id") in matched_topic_ids
    ]
    related_business_ids = {
        str(business_id)
        for topic in topics
        for business_id in topic.get("related_business_ids", [])
    }
    business_areas = [
        {key: area.get(key) for key in ("id", "name", "description")}
        for area in profile.get("business_areas", [])
        if isinstance(area, Mapping) and area.get("id") in related_business_ids
    ]
    evidence_articles = [
        context["articles"][article_id]
        for article_id in evaluation["evidence_article_ids"]
    ]
    company_name = str(profile.get("company_name") or "").strip()
    company_mentioned = any(
        company_name.casefold()
        in " ".join(
            str(article.get(field) or "") for field in ("title", "summary")
        ).casefold()
        for article in evidence_articles
    ) if company_name else False
    return {
        "trend": {
            key: trend.get(key)
            for key in ("trend_id", "title_ko", "summary_ko", "why_it_matters_ko")
        },
        "relevance": {
            key: evaluation.get(key)
            for key in (
                "company_id",
                "relevance",
                "reason_ko",
                "transmission_path_ko",
                "matched_topic_ids",
                "business_tags",
                "evidence_article_ids",
                "evidence_metrics",
            )
        },
        "company_profile": {
            "company_id": profile.get("company_id"),
            "company_name": profile.get("company_name"),
            "profile_summary": list(profile.get("profile_summary") or []),
            "watch_topics": topics,
            "business_areas": business_areas,
        },
        "company_mentioned_in_articles": company_mentioned,
        "articles": [
            {
                "article_id": article.get("article_id"),
                "title": article.get("title"),
                "source": article.get("source"),
                "published_at": article.get("published_at"),
                "summary": str(article.get("summary") or "")[:ARTICLE_SUMMARY_MAX_CHARS],
            }
            for article in evidence_articles
        ],
    }


def build_brief_messages(
    selected: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    context: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    requested = {
        company_id: groups["main"]
        for company_id, groups in selected.items()
        if groups["main"]
    }
    if not requested:
        raise ValueError("No main brief candidates require model prose")
    payload = {
        "output_contract": {
            "companies": [
                {
                    "company_id": company_id,
                    "weekly_summary_ko": "선정된 Main Brief 전체를 요약한 2~3문장",
                    "briefs": [
                        {
                            "trend_id": evaluation["trend_id"],
                            "headline_ko": "45자 이내 제목",
                            "situation_ko": "현재 상황 1~2문장",
                            "company_relevance_ko": "회사 관련성 1~2문장",
                            "business_impact_ko": "사업 영향 가능성 1~2문장",
                            "watch_next": ["관찰사항 1", "관찰사항 2"],
                        }
                        for evaluation in groups
                    ],
                }
                for company_id, groups in requested.items()
            ]
        },
        "brief_candidates": [
            _scoped_candidate(evaluation, context, profiles[company_id])
            for company_id, groups in requested.items()
            for evaluation in groups
        ],
    }
    system_prompt = """너는 금융계열사 내부 주간 브리핑 작성자다.
반드시 JSON 객체만 출력하고 Markdown이나 JSON 밖의 설명을 쓰지 마라.
코드가 선정한 회사와 트렌드만 정확히 한 번씩 작성하고 후보를 추가·삭제·재평가하지 마라.
weekly_summary_ko는 회사별 Main Brief를 2~3문장, 약 100~150자로 요약하되 240자를 넘지 마라.
headline_ko는 약 20~35자, 최대 45자로 쓰고 기사 제목을 그대로 복사하거나 회사명을 반복하지 마라.
situation_ko, company_relevance_ko, business_impact_ko는 각각 1~2문장, 약 100~150자로 작성하되 220자를 넘지 마라.
company_relevance_ko는 구체적인 사업 또는 감시주제에 연결하고 일반적인 리스크 관리 문구를 피하라.
business_impact_ko는 입력 전이 경로를 업무 언어로 풀되 긍정·부정 방향을 단정하지 마라.
watch_next는 서로 다른 후속 관찰사항을 정확히 2개 작성하고 각 약 40~70자, 최대 90자로 제한하라.
기사의 라이선스 취득·협력·투자·출시 등 행동 주체를 바꾸지 마라. 외부 기업의 행동을 한화 계열사가 수행한 것처럼 쓰지 마라.
company_mentioned_in_articles가 false이면 situation_ko에는 실제 외부 주체를 쓰고, 해당 회사의 relevance·impact·weekly summary는 영향 가능성, 검토 필요, 기회·위험 요인처럼 조건부로만 표현하라.
입력 기사에 없는 사건·수치·인과관계·임계값을 만들지 마라.
투자추천, 매수·매도 의견, 확정적인 미래 예측, 단정적인 전략 지시를 쓰지 마라.
trend_id와 company_id만 그대로 반환하라. 관련성 등급, 태그, 근거 ID, 통계는 출력하지 마라."""
    return [
        {"role": "system", "content": system_prompt + "\n" + CONDITIONAL_GUIDANCE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def build_brief_response_format(
    selected: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
) -> dict[str, Any]:
    company_ids = sorted(
        company_id for company_id, groups in selected.items() if groups["main"]
    )
    trend_ids = sorted(
        {
            str(evaluation["trend_id"])
            for groups in selected.values()
            for evaluation in groups["main"]
        }
    )
    brief_schema = {
        "type": "object",
        "properties": {
            "trend_id": {"type": "string", "enum": trend_ids},
            "headline_ko": {"type": "string"},
            "situation_ko": {"type": "string"},
            "company_relevance_ko": {"type": "string"},
            "business_impact_ko": {"type": "string"},
            "watch_next": {"type": "array", "items": {"type": "string"}},
        },
        "required": sorted(MODEL_BRIEF_FIELDS),
        "additionalProperties": False,
    }
    company_schema = {
        "type": "object",
        "properties": {
            "company_id": {"type": "string", "enum": company_ids},
            "weekly_summary_ko": {"type": "string"},
            "briefs": {"type": "array", "items": brief_schema},
        },
        "required": sorted(MODEL_COMPANY_FIELDS),
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "company_brief_payload",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"companies": {"type": "array", "items": company_schema}},
                "required": ["companies"],
                "additionalProperties": False,
            },
        },
    }


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()




def _evidence_mentions_company(
    company_name: str,
    evidence_article_ids: Sequence[str],
    context: Mapping[str, Any],
) -> bool:
    normalized_name = _normalize_text(company_name)
    if not normalized_name:
        return False
    return any(
        normalized_name
        in _normalize_text(
            f"{context['articles'][article_id].get('title') or ''} "
            f"{context['articles'][article_id].get('summary') or ''}"
        )
        for article_id in evidence_article_ids
    )


def validate_and_combine_brief_payload(
    payload: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    context: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    monitoring_items: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Validate prose-only model output and attach code-owned fields."""
    if set(payload) != {"companies"} or not isinstance(payload.get("companies"), list):
        raise ValueError("Brief payload must contain only a companies array")
    expected = {
        company_id: {str(item["trend_id"]): item for item in groups["main"]}
        for company_id, groups in selected.items()
        if groups["main"]
    }
    raw_by_company: dict[str, Mapping[str, Any]] = {}
    cross_company_relevance: set[str] = set()
    cross_company_impact: set[str] = set()

    for company_index, raw_company in enumerate(payload["companies"], start=1):
        label = f"Company output #{company_index}"
        if not isinstance(raw_company, Mapping):
            raise ValueError(f"{label} must be an object")
        if set(raw_company) != MODEL_COMPANY_FIELDS:
            raise ValueError(f"{label} has missing or unexpected fields")
        company_id = raw_company["company_id"]
        if not isinstance(company_id, str) or company_id not in expected:
            raise ValueError(f"{label} references an unrequested company: {company_id!r}")
        if company_id in raw_by_company:
            raise ValueError(f"Duplicate company output: {company_id}")
        summary = _non_empty_string(
            raw_company["weekly_summary_ko"],
            field=f"{company_id}.weekly_summary_ko",
            maximum=MAX_LENGTHS["weekly_summary_ko"],
        )
        company_name = str(profiles[company_id].get("company_name") or "")
        all_company_evidence_absent = all(
            not _evidence_mentions_company(
                company_name, evaluation["evidence_article_ids"], context
            )
            for evaluation in expected[company_id].values()
        )
        if (
            all_company_evidence_absent
            and _normalize_text(company_name) in _normalize_text(summary)
            and not _uses_indirect_language(summary)
        ):
            raise ValueError(
                f"{company_id}.weekly_summary_ko attributes unsupported direct action"
            )
        raw_briefs = raw_company["briefs"]
        if not isinstance(raw_briefs, list) or len(raw_briefs) > MAIN_BRIEF_LIMIT:
            raise ValueError(f"{company_id}.briefs must be an array of at most 2 items")

        briefs_by_trend: dict[str, dict[str, Any]] = {}
        field_texts = {field: set() for field in BRIEF_TEXT_FIELDS}
        watch_texts: set[str] = set()
        for brief_index, raw_brief in enumerate(raw_briefs, start=1):
            brief_label = f"{company_id}.briefs[{brief_index}]"
            if not isinstance(raw_brief, Mapping) or set(raw_brief) != MODEL_BRIEF_FIELDS:
                raise ValueError(f"{brief_label} has missing or unexpected fields")
            trend_id = raw_brief["trend_id"]
            if not isinstance(trend_id, str) or trend_id not in expected[company_id]:
                raise ValueError(f"{brief_label} references an unselected trend: {trend_id!r}")
            if trend_id in briefs_by_trend:
                raise ValueError(f"Duplicate brief output: {company_id}/{trend_id}")

            clean: dict[str, Any] = {"trend_id": trend_id}
            for field in BRIEF_TEXT_FIELDS:
                value = _non_empty_string(
                    raw_brief[field],
                    field=f"{brief_label}.{field}",
                    maximum=MAX_LENGTHS[field],
                )
                normalized = _normalize_text(value)
                if normalized in field_texts[field]:
                    raise ValueError(f"Repeated {field} within {company_id}")
                field_texts[field].add(normalized)
                clean[field] = value

            evidence_titles = {
                _normalize_text(str(context["articles"][article_id].get("title") or ""))
                for article_id in expected[company_id][trend_id]["evidence_article_ids"]
            }
            if _normalize_text(clean["headline_ko"]) in evidence_titles:
                raise ValueError(f"{brief_label}.headline_ko copies an article title")

            company_mentioned = _evidence_mentions_company(
                company_name,
                expected[company_id][trend_id]["evidence_article_ids"],
                context,
            )
            if not company_mentioned:
                if (
                    _normalize_text(company_name)
                    in _normalize_text(clean["situation_ko"])
                    and not _uses_indirect_language(clean["situation_ko"])
                ):
                    raise ValueError(
                        f"{brief_label}.situation_ko attributes unsupported direct action"
                    )
                for field in ("company_relevance_ko", "business_impact_ko"):
                    if not _uses_indirect_language(clean[field]):
                        raise ValueError(
                            f"{brief_label}.{field} must use conditional language when "
                            "the company is absent from evidence"
                        )

            watch_next = raw_brief["watch_next"]
            if not isinstance(watch_next, list) or len(watch_next) != 2:
                raise ValueError(f"{brief_label}.watch_next must contain exactly 2 items")
            clean_watch = [
                _non_empty_string(
                    item,
                    field=f"{brief_label}.watch_next",
                    maximum=MAX_LENGTHS["watch_next"],
                )
                for item in watch_next
            ]
            normalized_watch = [_normalize_text(item) for item in clean_watch]
            if len(set(normalized_watch)) != 2:
                raise ValueError(f"{brief_label}.watch_next repeats the same item")
            if any(item in watch_texts for item in normalized_watch):
                raise ValueError(f"Repeated watch_next within {company_id}")
            watch_texts.update(normalized_watch)
            clean["watch_next"] = clean_watch

            relevance_text = _normalize_text(clean["company_relevance_ko"])
            impact_text = _normalize_text(clean["business_impact_ko"])
            if relevance_text in cross_company_relevance:
                raise ValueError("company_relevance_ko is copied across companies")
            if impact_text in cross_company_impact:
                raise ValueError("business_impact_ko is copied across companies")
            briefs_by_trend[trend_id] = clean

        if set(briefs_by_trend) != set(expected[company_id]):
            raise ValueError(f"{company_id} did not return every selected brief exactly once")
        cross_company_relevance.update(
            _normalize_text(item["company_relevance_ko"])
            for item in briefs_by_trend.values()
        )
        cross_company_impact.update(
            _normalize_text(item["business_impact_ko"])
            for item in briefs_by_trend.values()
        )
        raw_by_company[company_id] = {
            "weekly_summary_ko": summary,
            "briefs": briefs_by_trend,
        }

    if set(raw_by_company) != set(expected):
        raise ValueError("Model omitted or added a requested company")

    companies: list[dict[str, Any]] = []
    for company_id in sorted(profiles):
        main = list(selected[company_id]["main"])
        model_company = raw_by_company.get(company_id)
        briefs: list[dict[str, Any]] = []
        for evaluation in main:
            trend_id = str(evaluation["trend_id"])
            prose = model_company["briefs"][trend_id]
            briefs.append(
                {
                    "brief_id": f"{company_id}__{trend_id}",
                    "company_id": company_id,
                    **prose,
                    "business_tags": list(evaluation["business_tags"]),
                    "evidence_article_ids": list(evaluation["evidence_article_ids"]),
                    "evidence_metrics": dict(evaluation["evidence_metrics"]),
                }
            )
        companies.append(
            {
                "company_id": company_id,
                "company_name": profiles[company_id]["company_name"],
                "weekly_summary_ko": model_company["weekly_summary_ko"] if model_company else "",
                "briefs": briefs,
                "monitoring_items": [dict(item) for item in monitoring_items[company_id]],
            }
        )
    return companies


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _failure_payload(
    trends_payload: Mapping[str, Any],
    relevance_payload: Mapping[str, Any],
    *,
    model: str,
    now: datetime,
    status: str,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    return {
        "generated_at": now.isoformat(),
        "source_trends_generated_at": trends_payload.get("generated_at"),
        "source_relevance_generated_at": relevance_payload.get("generated_at"),
        "model": model,
        "status": status,
        "companies": [],
        "error": {"type": error_type, "message": message},
    }


def generate_company_briefs(
    trends_payload: Mapping[str, Any],
    relevance_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]] | None = None,
    *,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
    profiles_dir: str | os.PathLike[str] = DEFAULT_PROFILES_DIR,
    client: Any = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_BRIEF_MAX_TOKENS,
    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    sleep_fn: Any = time.sleep,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate each candidate independently; retry only failed candidates."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not 1 <= max_attempts <= DEFAULT_MAX_ATTEMPTS:
        raise ValueError("max_attempts must be 1 or 2")
    article_input = list(articles if articles is not None else trends_payload.get("articles", []))
    try:
        loaded_profiles = dict(
            profiles if profiles is not None else load_all_company_profiles(profiles_dir)
        )
        context = validate_brief_prerequisites(
            trends_payload, relevance_payload, article_input, loaded_profiles
        )
        # Scope every downstream step to companies relevance actually covered.
        # A company relevance classification failed for must not block briefs
        # for its siblings; it simply will not appear in the returned array,
        # which the UI already renders as "no data for this company."
        scoped_profiles = {
            company_id: loaded_profiles[company_id]
            for company_id in context["covered_company_ids"]
        }
        selected = select_brief_candidates(context, scoped_profiles)
        monitoring_items = build_monitoring_items(selected, context)
    except Exception as exc:
        return _failure_payload(
            trends_payload,
            relevance_payload,
            model=model,
            now=reference,
            status="NOT_GENERATED",
            error_type="PrerequisiteError",
            message=str(exc) if isinstance(exc, PrerequisiteError) else "Brief 입력이 유효하지 않습니다.",
        )

    companies = {
        cid: {"company_id": cid, "company_name": scoped_profiles[cid]["company_name"],
              "weekly_summary_ko": "", "briefs": [],
              "monitoring_items": [dict(item) for item in monitoring_items[cid]],
              "generation_status": "GENERATED", "failed_briefs": []}
        for cid in sorted(scoped_profiles)
    }
    candidates = [(cid, item) for cid, groups in selected.items() for item in groups["main"]]
    diagnostics: dict[str, Any] = {}
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    summaries: dict[str, str] = {}

    def result() -> dict[str, Any]:
        failed = False
        for cid, company in companies.items():
            company["briefs"] = [accepted[(cid, str(item["trend_id"]))]
                                 for item in selected[cid]["main"] if (cid, str(item["trend_id"])) in accepted]
            company["failed_briefs"] = [str(item["trend_id"]) for item in selected[cid]["main"]
                                        if (cid, str(item["trend_id"])) not in accepted]
            if company["failed_briefs"]:
                failed = True
                company["generation_status"] = "PARTIAL"
                company["generation_note"] = f"Main Brief {len(company['failed_briefs'])}건 생성 미완료. 성공한 항목과 Monitoring은 표시합니다."
            # Partial prose must not become a summary of failed/absent items.
            if not company["failed_briefs"]:
                company["weekly_summary_ko"] = summaries.get(cid, "") if len(company["briefs"]) == 1 else ""
        return {"generated_at": reference.isoformat(),
                "source_trends_generated_at": trends_payload.get("generated_at"),
                "source_relevance_generated_at": relevance_payload.get("generated_at"),
                "model": model, "status": "PARTIAL" if failed else "GENERATED",
                "companies": list(companies.values()), "brief_calls": diagnostics}

    if not candidates:
        return result()
    if client is None:
        key = resolve_api_key(api_key)
        setup_error = ""
        if not key:
            setup_error = "OPENAI_API_KEY가 없어 생성 요청을 실행하지 못했습니다."
        else:
            try:
                client = create_client(key)
            except ImportError:
                setup_error = "openai 패키지가 없어 생성 요청을 실행하지 못했습니다."
        if setup_error:
            for cid, item in candidates:
                diagnostics[f"{cid}__{item['trend_id']}"] = {
                    "company_id": cid, "trend_id": item["trend_id"], "status": "failed",
                    "attempts": [], "error_message": setup_error}
            return result()

    def explain(exc: Exception, finish: str) -> tuple[str, str]:
        if finish == "length":
            return "output_truncated", "출력 토큰 한도에 도달해 응답이 잘렸습니다."
        msg = str(exc)
        field = next((f for f in ("weekly_summary_ko", *BRIEF_TEXT_FIELDS, "watch_next") if f in msg), "응답")
        rules = (
            ("exceeds", "length_limit", "길이 제한을 초과했습니다."),
            ("conditional", "unsupported_assertion", "근거에 회사가 없는데 조건부 표현으로 설명하지 않았습니다."),
            ("unsupported direct action", "unsupported_assertion", "근거에 없는 회사 행동을 단정했습니다."),
            ("copies an article title", "copied_headline", "기사 제목을 그대로 복사했습니다."),
            ("copied across", "repeated_prose", "다른 회사의 문장과 동일합니다."),
            ("Repeated", "repeated_prose", "이미 채택한 항목의 문장을 반복했습니다."),
            ("repeats", "repeated_prose", "관찰 항목이 중복됐습니다."),
            ("exactly 2", "watch_count", "후속 관찰은 정확히 2개여야 합니다."),
            ("Korean", "missing_korean", "한국어 문장이 필요합니다."),
            ("non-empty", "empty_field", "필수 문장이 비어 있습니다."),
            ("no content", "empty_response", "모델이 빈 응답을 반환했습니다."),
            ("not valid JSON", "invalid_json", "JSON을 해석할 수 없습니다."),
            ("missing", "missing_fields", "필수 항목이 빠졌거나 형식이 다릅니다."),
            ("omitted", "missing_item", "요청한 회사 또는 Brief가 누락됐습니다."),
            ("Duplicate", "duplicate_item", "회사 또는 Brief가 중복됐습니다."),
        )
        for marker, code, text in rules:
            if marker in msg:
                return code, f"{field}: {text}"
        if isinstance(exc, (TypeError, ValueError)):
            return "invalid_structure", "요청한 회사·트렌드 또는 응답 자료형이 검증 기준과 다릅니다."
        status = getattr(exc, "status_code", None)
        return "api_error", api_error_message(exc)

    def consume(parsed: Any, cid: str, item: Mapping[str, Any]) -> None:
        if not isinstance(parsed, Mapping) or set(parsed) != {"companies"} or not isinstance(parsed["companies"], list):
            raise ValueError("missing companies array")
        matches = [c for c in parsed["companies"] if isinstance(c, Mapping) and c.get("company_id") == cid]
        if len(matches) != 1:
            raise ValueError("Model omitted or Duplicate company")
        raw = dict(matches[0])
        if not isinstance(raw.get("briefs"), list):
            raise ValueError("missing briefs array")
        matches = [b for b in raw["briefs"] if isinstance(b, Mapping) and b.get("trend_id") == item["trend_id"]]
        if len(matches) != 1:
            raise ValueError("Model omitted or Duplicate brief")
        raw["briefs"] = matches
        scope = {cid: {"main": [dict(item)], "monitoring": []}}
        validated = validate_and_combine_brief_payload(
            {"companies": [raw]}, scope, context, {cid: scoped_profiles[cid]}, {cid: []})[0]
        brief = validated["briefs"][0]
        # Preserve the original cross-item safeguards when validating in isolation.
        for (other_cid, _), other in accepted.items():
            fields = BRIEF_TEXT_FIELDS if other_cid == cid else ("company_relevance_ko", "business_impact_ko")
            for field in fields:
                if _normalize_text(brief[field]) == _normalize_text(other[field]):
                    raise ValueError(f"Repeated {field}")
            if other_cid == cid and set(map(_normalize_text, brief["watch_next"])) & set(map(_normalize_text, other["watch_next"])):
                raise ValueError("Repeated watch_next")
        accepted[(cid, str(item["trend_id"]))] = brief
        summaries[cid] = validated["weekly_summary_ko"]

    def request(scope, targets, attempt, budget, correction=""):
        finish = ""
        parsed = None
        error = None
        try:
            messages = build_brief_messages(scope, context, {cid: scoped_profiles[cid] for cid in scope})
            if correction:
                messages.append({"role": "user", "content": "이전 응답 검증 오류: " + correction + " 실패한 이 항목만 수정하세요. 근거 없는 사실은 추가하지 마세요."})
            kwargs = dict(**completion_options(model=model, max_tokens=budget,
                          reasoning_effort=reasoning_effort, temperature=temperature),
                          messages=messages, response_format=build_brief_response_format(scope))
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            response = complete(client, stage="briefs", **kwargs)
            choices = _attribute(response, "choices", []) or []
            choice = choices[0] if choices else None
            finish = _attribute(choice, "finish_reason", "") or ""
            content = _attribute(_attribute(choice, "message"), "content", "") or ""
            if finish == "length" or not str(content).strip():
                raise ValueError("Model returned no content or truncated output")
            parsed = parse_structured_json(str(content))
        except Exception as exc:
            error = exc
        for cid, item in targets:
            key = f"{cid}__{item['trend_id']}"
            record = diagnostics.setdefault(key, {"company_id": cid, "trend_id": item["trend_id"], "attempts": []})
            detail = {"attempt": attempt, "max_tokens": budget,
                      "finish_reason": finish if finish in {"stop", "length", "content_filter"} else ""}
            try:
                if error is not None:
                    raise error
                consume(parsed, cid, item)
            except Exception as exc:
                code, message = explain(exc, finish)
                detail.update(outcome="validation_error" if isinstance(exc, (TypeError, ValueError)) else "api_error",
                              error_code=code, message=message, error_type=type(exc).__name__)
                status = getattr(exc, "status_code", None)
                if isinstance(status, int):
                    detail["http_status"] = status
                if is_permanent_api_error(exc):
                    detail["retryable"] = False
                if status == 429:
                    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
                    try:
                        detail["retry_after_seconds"] = min(60.0, max(0.0, float(headers.get("retry-after", retry_base_delay))))
                    except (TypeError, ValueError):
                        pass
                record.update(status="failed", error_message=message)
            else:
                detail["outcome"] = "success"
                record.update(status="success")
                record.pop("error_message", None)
            record["attempts"].append(detail)

    request(selected, candidates, 1, max_tokens)
    if max_attempts > 1:
        for cid, item in candidates:
            if (cid, str(item["trend_id"])) in accepted:
                continue
            record = diagnostics[f"{cid}__{item['trend_id']}"]
            last = record["attempts"][-1]
            if last.get("retryable") is False:
                continue
            budget = max(max_tokens, min(max_tokens * 2, 16000)) if last.get("error_code") == "output_truncated" else max_tokens
            sleep_fn(last.get("retry_after_seconds", retry_base_delay))
            request({cid: {"main": [item], "monitoring": []}}, [(cid, item)], 2, budget, record["error_message"])
    return result()
