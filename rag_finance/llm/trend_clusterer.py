"""Group recent articles into three emerging trends with Groq.

The model only groups and writes prose. Every count shown on screen is computed
from the linked articles in code (see app/trend_feed_data.py), never generated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import time
from typing import Any, Mapping, Sequence

from rag_finance.ingestion.rss_collector import WATCH_AREAS


TREND_COUNT = 3
# Sized for Groq's free tier, which caps tokens-per-minute for the whole request
# (prompt + max_tokens). 36 trimmed articles leave room for the model's output.
MAX_ARTICLES_FOR_LLM = 36
# The full RSS summary is kept in the payload; only the prompt copy is trimmed.
LLM_SUMMARY_MAX_CHARS = 140
MAX_TAGS_PER_TREND = 3
MAX_WATCH_NEXT = 3
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 2600
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_RETRY_BASE_DELAY = 1.0

# The model may only pick from this list; anything else is dropped.
ALLOWED_BUSINESS_TAGS: tuple[str, ...] = (
    "보험 자산운용",
    "보험 리스크관리",
    "증권 리서치",
    "증권 리스크관리",
    "증권 디지털사업",
    "자산운용 포트폴리오",
    "자산운용 상품전략",
    "전사 전략",
    "디지털금융",
)

TEXT_FIELDS = ("title_ko", "summary_ko", "why_it_matters_ko")


class TrendClusteringError(Exception):
    """A model/API failure with safe, serializable attempt diagnostics."""

    def __init__(self, message: str, diagnostics: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics)


def select_articles_for_llm(
    articles: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_ARTICLES_FOR_LLM,
) -> list[dict[str, Any]]:
    """Round-robin across (watch area, language) so no bucket dominates the prompt."""
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        key = (str(article.get("watch_area") or ""), str(article.get("language") or ""))
        buckets[key].append(dict(article))
    for bucket in buckets.values():
        bucket.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

    ordered_keys = sorted(buckets)
    selected: list[dict[str, Any]] = []
    index = 0
    while len(selected) < limit:
        added = False
        for key in ordered_keys:
            bucket = buckets[key]
            if index < len(bucket):
                selected.append(bucket[index])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        index += 1
    return selected


def build_cluster_messages(
    articles: Sequence[Mapping[str, Any]],
    *,
    window_days: int = 7,
) -> list[dict[str, str]]:
    scoped = [
        {
            "article_id": article.get("article_id"),
            "title": article.get("title"),
            "source": article.get("source"),
            # Date alone is enough to group a week; the time of day is noise here.
            "published_at": str(article.get("published_at") or "")[:10],
            "summary": str(article.get("summary") or "")[:LLM_SUMMARY_MAX_CHARS],
            "watch_area": article.get("watch_area"),
        }
        for article in articles
    ]

    system_prompt = f"""너는 금융 트렌드 브리핑 편집자다.
반드시 JSON 객체만 출력하고 Markdown이나 설명 문장을 JSON 밖에 쓰지 마라.
입력 기사에서 공통으로 나타난 변화를 찾아 정확히 {TREND_COUNT}개의 트렌드로 묶어라.
기사 제목을 그대로 반복하지 말고 여러 기사에 걸친 흐름을 요약하라.
기사에 없는 사건, 숫자, 인과관계를 만들지 마라.
기사 수나 증가율 같은 수치는 쓰지 마라. 수치는 시스템이 따로 계산한다.
투자 추천, 매수·매도 의견, 목표주가를 쓰지 마라.
"한화는 반드시 무엇을 해야 한다" 같은 단정적인 전략 지시를 쓰지 마라.
미래 사건을 예측하지 말고 관찰된 변화와 후속 확인 항목만 쓰라.
한글로 작성하고 영어는 고유명사와 필수 금융용어에만 사용하라.
article_ids는 입력에 있는 article_id만 사용하라.
각 트렌드는 가능하면 기사 3건 이상, 서로 다른 출처 2곳 이상을 묶어라.
related_business_tags는 다음 목록에서만 최대 {MAX_TAGS_PER_TREND}개 고르라: {", ".join(ALLOWED_BUSINESS_TAGS)}"""

    trend_example = {
        "trend_id": "trend_01",
        "title_ko": "간결한 한국어 제목",
        "summary_ko": f"최근 {window_days}일간 나타난 변화",
        "why_it_matters_ko": "금융산업 관점에서 주목할 이유",
        "watch_next": ["후속 관찰 포인트 1", "후속 관찰 포인트 2"],
        "article_ids": ["입력에 존재하는 article_id"],
        "related_business_tags": list(ALLOWED_BUSINESS_TAGS[:2]),
    }
    contract = {
        "generated_at": "ISO datetime",
        "window_days": window_days,
        "trends": [
            {**trend_example, "trend_id": f"trend_{index:02d}"}
            for index in range(1, TREND_COUNT + 1)
        ],
    }
    user_payload = {
        "output_contract": contract,
        "window_days": window_days,
        "watch_areas": {key: value["label"] for key, value in WATCH_AREAS.items()},
        "articles": scoped,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def build_trend_response_format(
    articles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build Groq strict Structured Outputs schema for the selected articles."""
    article_ids = [
        str(article["article_id"])
        for article in articles
        if article.get("article_id")
    ]
    trend_schema = {
        "type": "object",
        "properties": {
            "trend_id": {"type": "string"},
            "title_ko": {"type": "string"},
            "summary_ko": {"type": "string"},
            "why_it_matters_ko": {"type": "string"},
            "watch_next": {"type": "array", "items": {"type": "string"}},
            "article_ids": {
                "type": "array",
                "items": {"type": "string", "enum": article_ids},
            },
            "related_business_tags": {
                "type": "array",
                "items": {"type": "string", "enum": list(ALLOWED_BUSINESS_TAGS)},
            },
        },
        "required": [
            "trend_id",
            "title_ko",
            "summary_ko",
            "why_it_matters_ko",
            "watch_next",
            "article_ids",
            "related_business_tags",
        ],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "generated_at": {"type": "string"},
            "window_days": {"type": "integer"},
            "trends": {"type": "array", "items": trend_schema},
        },
        "required": ["generated_at", "window_days", "trends"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "financial_trend_payload",
            "strict": True,
            "schema": schema,
        },
    }


def parse_structured_json(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM output must be a JSON object")
    return payload


def normalize_business_tags(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    allowed = set(ALLOWED_BUSINESS_TAGS)
    tags: list[str] = []
    for value in values:
        tag = " ".join(str(value or "").split())
        if tag in allowed and tag not in tags:
            tags.append(tag)
    return tags[:MAX_TAGS_PER_TREND]


def validate_trend_payload(
    payload: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reject invented article ids and off-list tags; keep exactly three trends."""
    known_ids = {
        str(article.get("article_id"))
        for article in articles
        if article.get("article_id")
    }

    raw_trends = payload.get("trends")
    if not isinstance(raw_trends, list) or not raw_trends:
        raise ValueError("Trend payload requires a non-empty trends list")

    trends: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_trends[:TREND_COUNT], start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Trend #{index} must be an object")

        trend: dict[str, Any] = {"trend_id": str(raw.get("trend_id") or f"trend_{index:02d}")}
        for field in TEXT_FIELDS:
            value = raw.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Trend #{index} missing {field}")
            trend[field] = value.strip()

        article_ids = [
            str(item)
            for item in (raw.get("article_ids") or [])
            if str(item) in known_ids
        ]
        # De-duplicate while keeping the model's ordering.
        trend["article_ids"] = list(dict.fromkeys(article_ids))
        if not trend["article_ids"]:
            raise ValueError(f"Trend #{index} has no article_ids that exist in the input")

        watch_next = [
            " ".join(str(item).split())
            for item in (raw.get("watch_next") or [])
            if str(item).strip()
        ]
        trend["watch_next"] = watch_next[:MAX_WATCH_NEXT]
        trend["related_business_tags"] = normalize_business_tags(
            raw.get("related_business_tags")
        )
        trends.append(trend)

    if len(trends) != TREND_COUNT:
        raise ValueError(f"Expected {TREND_COUNT} trends, got {len(trends)}")

    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        generated_at = datetime.now(timezone.utc).isoformat()

    window_days = payload.get("window_days")
    if not isinstance(window_days, int) or window_days <= 0:
        window_days = 7

    return {"generated_at": generated_at, "window_days": window_days, "trends": trends}


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_summary(response: Any) -> dict[str, int]:
    usage = _attribute(response, "usage")
    if usage is None:
        return {}
    result: dict[str, int] = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _attribute(usage, field)
        if isinstance(value, int):
            result[field] = value
    return result


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if not isinstance(value, int):
        value = getattr(getattr(exc, "response", None), "status_code", None)
    return value if isinstance(value, int) else None


def _is_transient_api_error(exc: Exception) -> bool:
    status = _status_code(exc)
    if status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "ratelimit"))


def _diagnostic_base(model: str, selected_count: int, max_attempts: int) -> dict[str, Any]:
    return {
        "model": model,
        "selected_article_count": selected_count,
        "max_attempts": max_attempts,
        "attempts": [],
    }


def cluster_trends(
    articles: Sequence[Mapping[str, Any]],
    *,
    client: Any = None,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    window_days: int = 7,
    max_articles: int = MAX_ARTICLES_FOR_LLM,
    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    sleep_fn: Any = time.sleep,
) -> dict[str, Any]:
    if len(articles) < TREND_COUNT:
        raise ValueError("At least three articles are required to build trends")

    selected = select_articles_for_llm(articles, limit=max_articles)
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if client is None:
        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("GROQ_API_KEY is required to cluster trends")
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("Install the groq package for trend clustering") from exc
        client = Groq(api_key=key)

    base_messages = build_cluster_messages(selected, window_days=window_days)
    request: dict[str, Any] = {
        "model": model,
        "messages": base_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": build_trend_response_format(selected),
    }
    if reasoning_effort:
        # Reasoning models otherwise spend the whole budget thinking and return
        # empty content with finish_reason "length".
        request["reasoning_effort"] = reasoning_effort

    diagnostics = _diagnostic_base(model, len(selected), max_attempts)
    correction = ""
    for attempt in range(1, max_attempts + 1):
        attempt_request = dict(request)
        attempt_request["messages"] = list(base_messages)
        if correction:
            attempt_request["messages"].append(
                {
                    "role": "user",
                    "content": (
                        "이전 응답은 다음 검증을 통과하지 못했다: "
                        f"{correction}. 입력 기사 ID만 사용해 정확히 "
                        f"{TREND_COUNT}개 트렌드를 다시 생성하라."
                    ),
                }
            )

        attempt_info: dict[str, Any] = {"attempt": attempt}
        try:
            response = client.chat.completions.create(**attempt_request)
        except Exception as exc:  # SDK exception types vary by installed version.
            status = _status_code(exc)
            attempt_info.update(
                outcome="api_error",
                error_type=type(exc).__name__,
                status_code=status,
            )
            diagnostics["attempts"].append(attempt_info)
            if attempt < max_attempts and _is_transient_api_error(exc):
                sleep_fn(retry_base_delay * (2 ** (attempt - 1)))
                continue
            raise TrendClusteringError(
                "Groq API 요청을 완료하지 못했습니다.", diagnostics
            ) from exc

        choices = _attribute(response, "choices", []) or []
        choice = choices[0] if choices else None
        message = _attribute(choice, "message")
        content = _attribute(message, "content", "") or ""
        attempt_info.update(
            request_id=_attribute(response, "id"),
            finish_reason=_attribute(choice, "finish_reason", "unknown"),
            usage=_usage_summary(response),
        )

        try:
            if not str(content).strip():
                raise ValueError(
                    "Model returned no content "
                    f"(finish_reason={attempt_info['finish_reason']})"
                )
            payload = parse_structured_json(str(content))
            attempt_info["top_level_keys"] = sorted(str(key) for key in payload)
            result = validate_trend_payload(payload, selected)
        except (TypeError, ValueError) as exc:
            correction = str(exc)
            attempt_info.update(
                outcome="validation_error",
                error_type=type(exc).__name__,
                validation_error=correction,
            )
            diagnostics["attempts"].append(attempt_info)
            if attempt < max_attempts:
                continue
            raise TrendClusteringError(
                f"모델 응답 검증에 {max_attempts}회 연속 실패했습니다.", diagnostics
            ) from exc

        attempt_info["outcome"] = "success"
        diagnostics["attempts"].append(attempt_info)
        result["model"] = model
        result["analyzed_article_count"] = len(selected)
        result["llm_diagnostics"] = diagnostics
        return result

    raise AssertionError("unreachable")
