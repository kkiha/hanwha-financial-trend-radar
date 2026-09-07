"""Classify each generated trend against every runtime company profile.

The model supplies qualitative judgements and references only. Pair completeness,
profile whitelists, evidence ownership, and evidence statistics are enforced in
code so search candidates never become ground truth by accident.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import time
from typing import Any, Mapping, Sequence

from rag_finance.ingestion.rss_collector import parse_datetime
from rag_finance.llm.trend_clusterer import parse_structured_json
from rag_finance.profiles.company_profiles import (
    DEFAULT_PROFILES_DIR,
    load_all_company_profiles,
)


RELEVANCE_LEVELS = ("high", "medium", "low", "none")
BRIEF_CANDIDATE_LEVELS = ("high", "medium")
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS_PER_COMPANY = 1200
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_RETRY_BASE_DELAY = 1.0
MAX_RETRY_WAIT_SECONDS = 30.0
RECENT_HOURS = 48
MAX_ARTICLES_PER_TREND = 3
ARTICLE_SUMMARY_MAX_CHARS = 160

EVALUATION_FIELDS = {
    "trend_id",
    "company_id",
    "relevance",
    "reason_ko",
    "transmission_path_ko",
    "matched_topic_ids",
    "business_tags",
    "evidence_article_ids",
}
INDIRECT_LANGUAGE_MARKERS = (
    "가능성",
    "수 있다",
    "수 있음",
    "검토",
    "기회",
    "위험",
    "요인",
    "관찰",
    "점검",
    "영향을 받을",
    "연결될",
    "전이될",
    "간접",
)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _unique_strings(value: Any, *, field: str) -> list[str]:
    raw = _as_list(value, field=field)
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"{field} must contain non-empty strings")
    normalized = [item.strip() for item in raw]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} contains duplicate values")
    return normalized


def _trend_context(
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_trends = trends_payload.get("trends")
    if not isinstance(raw_trends, list) or not raw_trends:
        raise ValueError("Trend payload requires a non-empty trends list")

    article_registry = {
        str(article["article_id"]): dict(article)
        for article in articles
        if isinstance(article, Mapping) and article.get("article_id")
    }
    trends: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_trends, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Trend #{index} must be an object")
        trend_id = str(raw.get("trend_id") or "").strip()
        if not trend_id:
            raise ValueError(f"Trend #{index} has no trend_id")
        if trend_id in seen:
            raise ValueError(f"Duplicate trend_id: {trend_id}")
        seen.add(trend_id)
        linked_ids = _unique_strings(raw.get("article_ids"), field=f"{trend_id}.article_ids")
        unknown = [article_id for article_id in linked_ids if article_id not in article_registry]
        if unknown:
            raise ValueError(f"{trend_id} references unknown article IDs: {', '.join(unknown)}")
        if not linked_ids:
            raise ValueError(f"{trend_id} has no evidence articles")
        trend = dict(raw)
        trend["trend_id"] = trend_id
        trend["article_ids"] = linked_ids
        trends.append(trend)
    return trends, article_registry


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _mentions_company(company_name: Any, articles: Sequence[Mapping[str, Any]]) -> bool:
    name = _normalized_text(company_name).casefold()
    if not name:
        return False
    return any(
        name
        in _normalized_text(
            f"{article.get('title') or ''} {article.get('summary') or ''}"
        ).casefold()
        for article in articles
    )


def _uses_indirect_language(value: str) -> bool:
    normalized = _normalized_text(value).casefold()
    return any(marker in normalized for marker in INDIRECT_LANGUAGE_MARKERS)


def _article_priority(article: Mapping[str, Any]) -> tuple[float, int, str]:
    published = parse_datetime(article.get("published_at"))
    timestamp = published.timestamp() if published is not None else float("-inf")
    has_summary = bool(_normalized_text(article.get("summary")))
    return (-timestamp, -int(has_summary), str(article.get("article_id") or ""))


def select_representative_articles(
    articles: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_ARTICLES_PER_TREND,
) -> list[dict[str, Any]]:
    """Select a stable, source-diverse set before sending anything to Groq."""
    if limit < 1:
        raise ValueError("Representative article limit must be positive")
    ordered = sorted((dict(article) for article in articles), key=_article_priority)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    seen_sources: set[str] = set()

    for article in ordered:
        source = _normalized_text(article.get("source")).casefold()
        if source in seen_sources:
            continue
        selected.append(article)
        selected_ids.add(str(article.get("article_id") or ""))
        seen_sources.add(source)
        if len(selected) == limit:
            return selected

    for article in ordered:
        article_id = str(article.get("article_id") or "")
        if article_id in selected_ids:
            continue
        selected.append(article)
        selected_ids.add(article_id)
        if len(selected) == limit:
            break
    return selected


def _representative_trends_payload(
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    trends, article_registry = _trend_context(trends_payload, articles)
    selected_trends: list[dict[str, Any]] = []
    for trend in trends:
        candidates = [article_registry[article_id] for article_id in trend["article_ids"]]
        selected = select_representative_articles(candidates)
        selected_trend = dict(trend)
        selected_trend["article_ids"] = [str(article["article_id"]) for article in selected]
        selected_trends.append(selected_trend)
    payload = dict(trends_payload)
    payload["trends"] = selected_trends
    return payload


def _scoped_article(article: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "article_id": article.get("article_id"),
        "title": article.get("title"),
        "source": article.get("source"),
        "published_at": article.get("published_at"),
        "summary": _normalized_text(article.get("summary"))[:ARTICLE_SUMMARY_MAX_CHARS],
        "candidate_companies": list(article.get("candidate_companies") or []),
        "matched_topic_ids": list(article.get("matched_topic_ids") or []),
    }


def _scoped_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "company_id": profile.get("company_id"),
        "company_name": profile.get("company_name"),
        "profile_summary": list(profile.get("profile_summary") or []),
        "business_areas": [
            {key: item.get(key) for key in ("id", "name")}
            for item in profile.get("business_areas", [])
            if isinstance(item, Mapping)
        ],
        "watch_topics": [
            {key: item.get(key) for key in ("id", "name", "transmission")}
            for item in profile.get("watch_topics", [])
            if isinstance(item, Mapping)
        ],
        "business_tags": list(profile.get("business_tags") or []),
        "excluded_rules": list(profile.get("excluded_rules") or []),
    }


def build_relevance_messages(
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Build one compact request for one company and every input trend."""
    if len(profiles) != 1:
        raise ValueError("A relevance request requires exactly one company profile")
    representative_payload = _representative_trends_payload(trends_payload, articles)
    trends, article_registry = _trend_context(representative_payload, articles)
    company_id = next(iter(profiles))
    company_name = profiles[company_id].get("company_name")

    scoped_trends = []
    for trend in trends:
        trend_articles = [
            article_registry[article_id] for article_id in trend["article_ids"]
        ]
        scoped_trends.append(
            {
                key: trend.get(key)
                for key in ("trend_id", "title_ko", "summary_ko", "why_it_matters_ko")
            }
            | {
                "articles": [
                    _scoped_article(article_registry[article_id])
                    for article_id in trend["article_ids"]
                ],
                "company_mentioned_in_articles": _mentions_company(
                    company_name, trend_articles
                ),
            }
        )

    user_payload = {
        "trends": scoped_trends,
        "company_profile": _scoped_profile(profiles[company_id]),
    }
    system_prompt = f"""너는 금융회사 경영정보 분석가다.
Structured Output 스키마에 맞춰 회사 {company_id}와 입력 트렌드 {len(trends)}건을 각각 정확히 한 번 평가하라.
relevance는 {', '.join(RELEVANCE_LEVELS)} 중 하나만 사용하라.
high는 주요 사업에 직접 전이, medium은 감시주제와 명확히 연결되나 추가 확인 필요, low는 간접 가능성, none은 구체적 연결이 없거나 excluded_rules에 해당하는 경우다.
high와 medium은 전이 경로, watch topic, business tag, 근거 기사 ID를 제시하라.
none이면 transmission_path_ko를 빈 문자열로, 세 배열을 모두 빈 배열로 출력하라.
candidate_companies와 기사 matched_topic_ids는 검색 경로 참고정보일 뿐 정답이 아니다. 후보에 없는 회사도 실제 사업 전이 경로가 있으면 평가하라.
기사에 회사명이 없다는 이유만으로 none을 선택하지 마라. 회사의 watch topic 이름과 transmission에 구체적으로 연결되면 간접 관련성을 판단하되, 특정 등급을 강제하지 마라.
기사의 라이선스 취득·협력·투자·출시 등 행동은 기사에 적힌 실제 주체의 행동이다. 이를 요청 회사가 수행한 것처럼 바꾸지 마라.
company_mentioned_in_articles가 false이면 요청 회사에 대해서는 영향 가능성, 검토 필요, 기회·위험 요인처럼 조건부로만 표현하라.
reason_ko와 transmission_path_ko는 근거에 기반해 간결한 한글로 작성하라.
입력에 없는 사건·수치·인과관계를 만들지 말고 투자추천이나 단정적 전략지시를 쓰지 마라.
기사 수·출처 수는 출력하지 말고 ID와 태그는 입력에 실제 존재하는 값만 사용하라."""
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                user_payload, ensure_ascii=False, separators=(",", ":")
            ),
        },
    ]


def build_relevance_response_format(
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if len(profiles) != 1:
        raise ValueError("A relevance response schema requires exactly one company profile")
    representative_payload = _representative_trends_payload(trends_payload, articles)
    trends, article_registry = _trend_context(representative_payload, articles)
    representative_ids = {
        article_id for trend in trends for article_id in trend["article_ids"]
    }
    topic_ids = sorted(
        {
            str(topic["id"])
            for profile in profiles.values()
            for topic in profile.get("watch_topics", [])
            if isinstance(topic, Mapping) and topic.get("id")
        }
    )
    business_tags = sorted(
        {str(tag) for profile in profiles.values() for tag in profile.get("business_tags", [])}
    )
    evaluation_schema = {
        "type": "object",
        "properties": {
            "trend_id": {"type": "string", "enum": [trend["trend_id"] for trend in trends]},
            "company_id": {"type": "string", "enum": sorted(profiles)},
            "relevance": {"type": "string", "enum": list(RELEVANCE_LEVELS)},
            "reason_ko": {"type": "string"},
            "transmission_path_ko": {"type": "string"},
            "matched_topic_ids": {
                "type": "array",
                "items": {"type": "string", "enum": topic_ids},
            },
            "business_tags": {
                "type": "array",
                "items": {"type": "string", "enum": business_tags},
            },
            "evidence_article_ids": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(representative_ids)},
            },
        },
        "required": sorted(EVALUATION_FIELDS),
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "evaluations": {"type": "array", "items": evaluation_schema},
        },
        "required": ["evaluations"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "company_relevance_payload",
            "strict": True,
            "schema": schema,
        },
    }


def compute_evidence_metrics(
    evidence_article_ids: Sequence[str],
    article_registry: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
    relevance: str = "low",
) -> dict[str, Any]:
    if relevance == "none":
        return {
            "article_count": 0,
            "source_count": 0,
            "recent_48h_count": 0,
            "recent_48h_share": 0.0,
            "corroboration": "none",
        }

    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence = [article_registry[article_id] for article_id in evidence_article_ids]
    sources = {str(article.get("source") or "").strip() for article in evidence}
    sources.discard("")
    cutoff = reference - timedelta(hours=RECENT_HOURS)
    recent_count = sum(
        1
        for article in evidence
        if (published := parse_datetime(article.get("published_at"))) is not None
        and published >= cutoff
    )
    article_count = len(evidence)
    source_count = len(sources)
    if article_count >= 3 and source_count >= 2:
        corroboration = "strong"
    elif article_count >= 2 and source_count >= 2:
        corroboration = "moderate"
    else:
        corroboration = "limited"
    return {
        "article_count": article_count,
        "source_count": source_count,
        "recent_48h_count": recent_count,
        "recent_48h_share": round(recent_count / article_count, 4) if article_count else 0.0,
        "corroboration": corroboration,
    }


def validate_relevance_payload(
    payload: Mapping[str, Any],
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Strictly validate all combinations and add code-computed evidence metrics."""
    if set(payload) != {"evaluations"}:
        raise ValueError("Relevance payload must contain only the evaluations field")
    trends, article_registry = _trend_context(trends_payload, articles)
    trend_by_id = {trend["trend_id"]: trend for trend in trends}
    expected_pairs = {
        (trend["trend_id"], company_id)
        for trend in trends
        for company_id in profiles
    }
    raw_evaluations = payload.get("evaluations")
    if not isinstance(raw_evaluations, list):
        raise ValueError("Relevance payload requires an evaluations array")

    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    reasons_by_trend: dict[str, list[str]] = {trend_id: [] for trend_id in trend_by_id}
    for index, raw in enumerate(raw_evaluations, start=1):
        label = f"Evaluation #{index}"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{label} must be an object")
        missing = EVALUATION_FIELDS - set(raw)
        extras = set(raw) - EVALUATION_FIELDS
        if missing:
            raise ValueError(f"{label} missing fields: {', '.join(sorted(missing))}")
        if extras:
            raise ValueError(f"{label} has unexpected fields: {', '.join(sorted(extras))}")

        trend_id = raw["trend_id"]
        company_id = raw["company_id"]
        if not isinstance(trend_id, str) or trend_id not in trend_by_id:
            raise ValueError(f"{label} references unknown trend_id: {trend_id!r}")
        if not isinstance(company_id, str) or company_id not in profiles:
            raise ValueError(f"{label} references unknown company_id: {company_id!r}")
        pair = (trend_id, company_id)
        if pair in by_pair:
            raise ValueError(f"Duplicate trend/company evaluation: {trend_id}/{company_id}")

        relevance = raw["relevance"]
        if relevance not in RELEVANCE_LEVELS:
            raise ValueError(f"{label} has invalid relevance: {relevance!r}")
        reason = raw["reason_ko"]
        transmission = raw["transmission_path_ko"]
        if not isinstance(reason, str) or not reason.strip() or not re.search(r"[가-힣]", reason):
            raise ValueError(f"{label} requires a Korean reason_ko")
        if not isinstance(transmission, str):
            raise ValueError(f"{label}.transmission_path_ko must be a string")

        topic_ids = _unique_strings(raw["matched_topic_ids"], field=f"{label}.matched_topic_ids")
        tags = _unique_strings(raw["business_tags"], field=f"{label}.business_tags")
        evidence_ids = _unique_strings(
            raw["evidence_article_ids"], field=f"{label}.evidence_article_ids"
        )
        allowed_topics = {
            str(topic["id"])
            for topic in profiles[company_id].get("watch_topics", [])
            if isinstance(topic, Mapping) and topic.get("id")
        }
        unknown_topics = sorted(set(topic_ids) - allowed_topics)
        if unknown_topics:
            raise ValueError(
                f"{label} uses topic IDs outside {company_id}: {', '.join(unknown_topics)}"
            )
        allowed_tags = {str(tag) for tag in profiles[company_id].get("business_tags", [])}
        unknown_tags = sorted(set(tags) - allowed_tags)
        if unknown_tags:
            raise ValueError(
                f"{label} uses business tags outside {company_id}: {', '.join(unknown_tags)}"
            )
        allowed_evidence = set(trend_by_id[trend_id]["article_ids"])
        unknown_evidence = sorted(set(evidence_ids) - allowed_evidence)
        if unknown_evidence:
            raise ValueError(
                f"{label} uses evidence outside {trend_id}: {', '.join(unknown_evidence)}"
            )

        mention_ids = evidence_ids or trend_by_id[trend_id]["article_ids"]
        company_mentioned = _mentions_company(
            profiles[company_id].get("company_name"),
            [article_registry[article_id] for article_id in mention_ids],
        )
        if relevance != "none" and not company_mentioned:
            indirect_description = f"{reason} {transmission}".strip()
            if not _uses_indirect_language(indirect_description):
                raise ValueError(
                    f"{label} must describe company relevance conditionally when "
                    "the company is absent from its evidence"
                )

        if relevance in BRIEF_CANDIDATE_LEVELS:
            if not transmission.strip() or not topic_ids or not tags or not evidence_ids:
                raise ValueError(
                    f"{label} {relevance} requires a transmission path, topic, tag, and evidence"
                )
        if relevance == "none" and (
            transmission.strip() or topic_ids or tags or evidence_ids
        ):
            raise ValueError(f"{label} none must have an empty path, topics, tags, and evidence")

        evaluation = {
            "trend_id": trend_id,
            "company_id": company_id,
            "relevance": relevance,
            "reason_ko": reason.strip(),
            "transmission_path_ko": transmission.strip(),
            "matched_topic_ids": topic_ids,
            "business_tags": tags,
            "evidence_article_ids": evidence_ids,
            "evidence_metrics": compute_evidence_metrics(
                evidence_ids, article_registry, now=now, relevance=relevance
            ),
        }
        by_pair[pair] = evaluation
        reasons_by_trend[trend_id].append(" ".join(reason.split()))

    actual_pairs = set(by_pair)
    if actual_pairs != expected_pairs:
        missing = sorted(expected_pairs - actual_pairs)
        unexpected = sorted(actual_pairs - expected_pairs)
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unexpected:
            details.append(f"unexpected={unexpected}")
        raise ValueError("Incomplete trend/company combinations: " + "; ".join(details))
    for trend_id, reasons in reasons_by_trend.items():
        if len(reasons) != len(set(reasons)):
            raise ValueError(f"Copied reason_ko detected across companies for {trend_id}")

    return [
        by_pair[(trend["trend_id"], company_id)]
        for trend in trends
        for company_id in sorted(profiles)
    ]


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _http_status(exc: Exception) -> int | None:
    status = _attribute(exc, "status_code")
    if status is None:
        status = _attribute(_attribute(exc, "response"), "status_code")
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error_code(exc: Exception) -> str | None:
    code = _attribute(exc, "code")
    if code:
        return str(code)
    body = _attribute(exc, "body")
    error = _attribute(body, "error")
    code = _attribute(error, "code")
    return str(code) if code else None


def validation_reason(exc: Exception, *, finish_reason: str = "") -> str:
    """Return bounded, allowlisted explanations, never model prose or API bodies."""
    if finish_reason == "length":
        return "출력 토큰 한도에 도달해 응답이 잘렸습니다."
    message = str(exc)
    rules = (
        ("Model returned no content", "모델이 빈 응답을 반환했습니다."),
        ("not valid JSON", "응답을 JSON으로 해석하지 못했습니다."),
        ("must be a JSON object", "응답 최상위 값이 JSON 객체가 아닙니다."),
        ("Incomplete trend/company combinations", "요청한 트렌드별 평가가 빠졌거나 요청하지 않은 평가가 포함됐습니다."),
        ("conditionally", "근거에 회사가 직접 등장하지 않는데 관련성을 조건부 표현으로 설명하지 않았습니다."),
        ("uses topic IDs outside", "회사 프로필에 없는 감시주제 ID를 사용했습니다."),
        ("uses business tags outside", "회사 프로필에 없는 업무 태그를 사용했습니다."),
        ("uses evidence outside", "해당 트렌드에 속하지 않는 근거 기사 ID를 사용했습니다."),
        ("requires a Korean reason_ko", "관련성 판단 이유(reason_ko)가 비어 있거나 한국어가 아닙니다."),
        ("requires a transmission path", "관련성이 high/medium인데 전이 경로·주제·태그·근거 중 필수 값이 빠졌습니다."),
        ("none must have an empty", "관련성이 none인데 전이 경로·주제·태그·근거가 남아 있습니다."),
        ("missing fields", "필수 평가 필드가 누락됐습니다."),
        ("unexpected fields", "허용되지 않은 평가 필드가 포함됐습니다."),
        ("unknown trend_id", "요청하지 않은 트렌드 ID를 반환했습니다."),
        ("unknown company_id", "요청하지 않은 회사 ID를 반환했습니다."),
        ("Duplicate trend/company", "같은 회사·트렌드 평가가 중복됐습니다."),
        ("invalid relevance", "허용되지 않은 관련성 등급을 반환했습니다."),
        ("Copied reason_ko", "회사 간 관련성 판단 이유가 동일하게 반복됐습니다."),
        ("contains duplicate", "목록 필드에 중복 값이 있습니다."),
        ("non-empty strings", "목록에 빈 값 또는 문자열이 아닌 값이 있습니다."),
        ("must be an array", "목록이어야 하는 필드의 자료형이 잘못됐습니다."),
        ("requires an evaluations array", "evaluations 평가 목록이 없거나 자료형이 잘못됐습니다."),
        ("must contain only the evaluations", "응답 최상위에는 evaluations 필드만 있어야 합니다."),
        ("must be a string", "문자열이어야 하는 필드의 자료형이 잘못됐습니다."),
        ("must be an object", "평가 항목이 객체가 아닙니다."),
    )
    reason = next((text for marker, text in rules if marker in message), "응답 검증 중 분류되지 않은 값 또는 자료형 오류가 발생했습니다.")
    item = re.search(r"Evaluation #(\d{1,4})\b", message)
    field = next((name for name in sorted(EVALUATION_FIELDS) if name in message), None)
    context = (f"평가 항목 {item.group(1)} · " if item else "") + (f"{field} · " if field else "")
    return context + reason


def _retry_after_seconds(exc: Exception, *, now: datetime) -> float | None:
    headers = _attribute(exc, "headers")
    if headers is None:
        headers = _attribute(_attribute(exc, "response"), "headers")
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at.astimezone(timezone.utc) - now).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, min(seconds, MAX_RETRY_WAIT_SECONDS))


def _unclassified(
    trends_payload: Mapping[str, Any],
    *,
    model: str,
    now: datetime,
    error_type: str,
    message: str,
    relevance_calls: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "generated_at": now.isoformat(),
        "source_trends_generated_at": trends_payload.get("generated_at"),
        "model": model,
        "status": "UNCLASSIFIED",
        "evaluations": [],
        "error": {"type": error_type, "message": message},
    }
    if relevance_calls is not None:
        result["relevance_calls"] = dict(relevance_calls)
    return result


def classify_company_relevance(
    trends_payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    *,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
    profiles_dir: str | os.PathLike[str] = DEFAULT_PROFILES_DIR,
    client: Any = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS_PER_COMPANY,
    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    sleep_fn: Any = time.sleep,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify each company sequentially, then validate the merged result."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not 1 <= max_attempts <= DEFAULT_MAX_ATTEMPTS:
        raise ValueError("max_attempts must be 1 or 2")
    try:
        loaded_profiles = dict(
            profiles if profiles is not None else load_all_company_profiles(profiles_dir)
        )
        if not loaded_profiles:
            raise ValueError("At least one company profile is required")
        representative_payload = _representative_trends_payload(trends_payload, articles)
        representative_trends, _ = _trend_context(representative_payload, articles)
    except Exception as exc:  # Input/profile failures do not benefit from an API retry.
        return _unclassified(
            trends_payload,
            model=model,
            now=reference,
            error_type=type(exc).__name__,
            message="관련성 분류 입력 또는 회사 프로파일이 유효하지 않습니다.",
        )

    if client is None:
        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            return _unclassified(
                trends_payload,
                model=model,
                now=reference,
                error_type="MissingApiKey",
                message="GROQ_API_KEY가 없어 관련성 분류를 실행하지 못했습니다.",
            )
        try:
            from groq import Groq
        except ImportError:
            return _unclassified(
                trends_payload,
                model=model,
                now=reference,
                error_type="MissingDependency",
                message="groq 패키지가 없어 관련성 분류를 실행하지 못했습니다.",
            )
        client = Groq(api_key=key)

    article_count = sum(len(trend["article_ids"]) for trend in representative_trends)
    relevance_calls: dict[str, dict[str, Any]] = {}
    merged_evaluations: list[dict[str, Any]] = []
    failures: list[Exception] = []

    for company_id in sorted(loaded_profiles):
        company_profiles = {company_id: loaded_profiles[company_id]}
        try:
            base_messages = build_relevance_messages(
                representative_payload, articles, company_profiles
            )
            response_format = build_relevance_response_format(
                representative_payload, articles, company_profiles
            )
        except Exception as exc:
            failures.append(exc)
            relevance_calls[company_id] = {
                "status": "failed",
                "attempts": 0,
                "input_chars": 0,
                "article_count": article_count,
                "watch_topic_count": len(
                    loaded_profiles[company_id].get("watch_topics", [])
                ),
                "max_tokens": max_tokens,
                "wait_seconds": [],
                "error_type": type(exc).__name__,
                "error_message": "관련성 요청 입력을 구성하지 못했습니다. " + validation_reason(exc),
            }
            continue

        call_debug: dict[str, Any] = {
            "status": "failed",
            "attempts": 0,
            "input_chars": sum(len(message["content"]) for message in base_messages),
            "article_count": article_count,
            "watch_topic_count": len(
                loaded_profiles[company_id].get("watch_topics", [])
            ),
            "max_tokens": max_tokens,
            "wait_seconds": [],
        }
        relevance_calls[company_id] = call_debug
        request: dict[str, Any] = {
            "model": model,
            "messages": base_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if reasoning_effort:
            request["reasoning_effort"] = reasoning_effort

        correction = ""
        company_succeeded = False
        for attempt in range(1, max_attempts + 1):
            call_debug["attempts"] = attempt
            finish_reason = ""
            attempt_request = dict(request)
            attempt_request["messages"] = list(base_messages)
            if correction:
                attempt_request["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "이전 응답의 검증 오류를 수정하라: "
                            f"{correction}. 요청한 회사의 모든 트렌드를 다시 출력하라."
                        ),
                    }
                )
            try:
                response = client.chat.completions.create(**attempt_request)
                choices = _attribute(response, "choices", []) or []
                choice = choices[0] if choices else None
                finish_reason = _attribute(choice, "finish_reason", "") or ""
                message = _attribute(choice, "message")
                content = _attribute(message, "content", "") or ""
                if not str(content).strip():
                    raise ValueError("Model returned no content")
                parsed = parse_structured_json(str(content))
                validate_relevance_payload(
                    parsed,
                    representative_payload,
                    articles,
                    company_profiles,
                    now=reference,
                )
            except Exception as exc:  # SDK error classes vary across supported versions.
                failures.append(exc)
                status = _http_status(exc)
                call_debug["error_type"] = type(exc).__name__
                if status is not None:
                    call_debug["http_status"] = status
                if error_code := _safe_error_code(exc):
                    call_debug["error_code"] = error_code
                is_validation = isinstance(exc, (TypeError, ValueError))
                detail = validation_reason(exc, finish_reason=finish_reason) if is_validation else (
                    f"API 요청 실패 (HTTP {status})." if status else "API 연결 또는 요청 처리에 실패했습니다."
                )
                call_debug["error_message"] = detail
                call_debug.setdefault("attempt_details", []).append({
                    "attempt": attempt, "outcome": "validation_error" if is_validation else "api_error",
                    "error_type": type(exc).__name__, "message": detail,
                    "finish_reason": finish_reason if finish_reason in {"stop", "length", "content_filter"} else "",
                    "http_status": status,
                })
                correction = str(exc) if is_validation else "Groq API request failed"
                if status == 413 or attempt >= max_attempts:
                    break
                wait_seconds = retry_base_delay * (2 ** (attempt - 1))
                if status == 429:
                    retry_after = _retry_after_seconds(exc, now=reference)
                    if retry_after is not None:
                        wait_seconds = retry_after
                wait_seconds = max(0.0, min(wait_seconds, MAX_RETRY_WAIT_SECONDS))
                call_debug["wait_seconds"].append(round(wait_seconds, 3))
                sleep_fn(wait_seconds)
                continue

            merged_evaluations.extend(
                dict(evaluation) for evaluation in parsed["evaluations"]
            )
            call_debug["status"] = "success"
            call_debug.pop("error_type", None)
            call_debug.pop("http_status", None)
            call_debug.pop("error_code", None)
            call_debug.pop("error_message", None)
            call_debug.setdefault("attempt_details", []).append({"attempt": attempt, "outcome": "success"})
            company_succeeded = True
            break

        if not company_succeeded:
            continue

    failed_companies = sorted(
        company_id
        for company_id, diagnostics in relevance_calls.items()
        if diagnostics["status"] != "success"
    )
    successful_companies = sorted(set(loaded_profiles) - set(failed_companies))

    # A company failing must not discard evaluations Groq already produced (and
    # validated) for its siblings: re-scope the merge to whichever companies
    # actually succeeded instead of throwing everything away.
    if not successful_companies:
        last_error = failures[-1] if failures else None
        return _unclassified(
            trends_payload,
            model=model,
            now=reference,
            error_type=type(last_error).__name__ if last_error else "UnknownError",
            message=(
                f"회사별 Groq 관련성 분류 중 {len(failed_companies)}개 회사 요청이 "
                "실패했습니다."
            ),
            relevance_calls=relevance_calls,
        )

    scoped_profiles = {company_id: loaded_profiles[company_id] for company_id in successful_companies}
    try:
        evaluations = validate_relevance_payload(
            {"evaluations": merged_evaluations},
            representative_payload,
            articles,
            scoped_profiles,
            now=reference,
        )
    except Exception as exc:
        return _unclassified(
            trends_payload,
            model=model,
            now=reference,
            error_type=type(exc).__name__,
            message="회사별 관련성 결과의 최종 병합 검증에 실패했습니다.",
            relevance_calls=relevance_calls,
        )

    result: dict[str, Any] = {
        "generated_at": reference.isoformat(),
        "source_trends_generated_at": trends_payload.get("generated_at"),
        "model": model,
        "status": "CLASSIFIED" if not failed_companies else "PARTIAL",
        "evaluations": evaluations,
        "relevance_calls": relevance_calls,
    }
    if failed_companies:
        result["error"] = {
            "type": "PartialClassification",
            "message": (
                f"{len(failed_companies)}개 회사({', '.join(failed_companies)}) 관련성 분류가 "
                f"실패해 나머지 {len(successful_companies)}개 회사만 분류했습니다."
            ),
        }
    return result
