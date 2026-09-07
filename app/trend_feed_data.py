"""Load the trend feed payload and compute every number the screen shows.

The LLM groups articles and writes prose. Counts, source diversity, recency and
ranking are all derived here from the linked articles, so nothing on screen is a
model-generated statistic.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from rag_finance.ingestion.rss_collector import WATCH_AREAS, parse_datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = PROJECT_ROOT / "data" / "live"
LIVE_TRENDS_PATH = LIVE_DIR / "latest_trends.json"
LIVE_ARTICLES_PATH = LIVE_DIR / "latest_articles.json"
LIVE_REFRESH_PATH = LIVE_DIR / "latest_refresh.json"
LIVE_COMPANY_RELEVANCE_PATH = LIVE_DIR / "latest_company_relevance.json"
LIVE_COMPANY_BRIEFS_PATH = LIVE_DIR / "latest_company_briefs.json"
FALLBACK_PATH = PROJECT_ROOT / "data" / "demo_outputs" / "trend_feed_fallback.json"

WINDOW_DAYS = 7
RECENT_HOURS = 48
# A live payload older than this is still shown, but labelled CACHED.
LIVE_FRESH_HOURS = 24

# Ranking weights. Kept deliberately simple and explained in the Methodology
# panel: volume alone would let one noisy wire service dominate.
WEIGHT_ARTICLES = 0.5
WEIGHT_SOURCES = 0.3
WEIGHT_RECENCY = 0.2

COMPANY_INTELLIGENCE_ORDER = (
    ("hanwha_life", "한화생명"),
    ("hanwha_investment", "한화투자증권"),
    ("hanwha_asset_management", "한화자산운용"),
)
CORROBORATION_LABELS = {
    "strong": "다수 출처로 확인",
    "moderate": "복수 출처로 확인",
    "limited": "제한적 근거",
    "none": "근거 없음",
}


def _read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    payload = _read_json_value(path)
    return payload if isinstance(payload, dict) else None


def _as_articles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def corroboration_label(value: Any) -> str:
    """Return a reader-facing label without changing the persisted schema."""
    return CORROBORATION_LABELS.get(str(value or "").lower(), "근거 수준 미확인")


def _attach_evidence(
    item: Mapping[str, Any], articles_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    enriched = dict(item)
    enriched["evidence_articles"] = [
        dict(articles_by_id[article_id])
        for article_id in item.get("evidence_article_ids", [])
        if isinstance(article_id, str) and article_id in articles_by_id
    ]
    metrics = item.get("evidence_metrics")
    corroboration = metrics.get("corroboration") if isinstance(metrics, Mapping) else None
    enriched["corroboration_label"] = corroboration_label(corroboration)
    return enriched


def build_company_intelligence(
    briefs_payload: Mapping[str, Any] | None,
    articles: Sequence[Mapping[str, Any]],
    *,
    trends_generated_at: Any,
    is_synthetic: bool = False,
) -> dict[str, Any]:
    """Validate and enrich runtime briefs solely for display.

    Company shells contain status text only. No prose, brief, or monitoring item
    is invented when runtime output is absent or unusable.
    """
    unavailable = [
        {
            "company_id": company_id,
            "company_name": company_name,
            "status": "UNAVAILABLE",
            "weekly_summary_ko": "",
            "briefs": [],
            "monitoring_items": [],
        }
        for company_id, company_name in COMPANY_INTELLIGENCE_ORDER
    ]

    if is_synthetic:
        reason = "DEMO 트렌드에는 실제 회사별 Intelligence Brief를 표시하지 않습니다."
        return {"status": "UNAVAILABLE", "reason": reason, "companies": unavailable}
    if not isinstance(briefs_payload, Mapping):
        reason = "회사별 Brief 파일이 없습니다. 전체 refresh를 실행해 주세요."
        return {"status": "UNAVAILABLE", "reason": reason, "companies": unavailable}

    status = str(briefs_payload.get("status") or "UNKNOWN")
    if status not in {"GENERATED", "PARTIAL"}:
        error = briefs_payload.get("error")
        detail = str(error.get("message") or "").strip() if isinstance(error, Mapping) else ""
        reason = "회사별 Brief가 생성되지 않았습니다."
        if detail:
            reason += f" {detail}"
        else:
            reason += f" 생성 상태: {status}"
        return {
            "status": status,
            "reason": reason,
            "generated_at": briefs_payload.get("generated_at"),
            "companies": unavailable,
        }

    source_stamp = parse_datetime(briefs_payload.get("source_trends_generated_at"))
    trend_stamp = parse_datetime(trends_generated_at)
    if source_stamp is None or trend_stamp is None or source_stamp != trend_stamp:
        reason = (
            "현재 표시 중인 트렌드와 회사별 Brief의 생성 기준 시각이 일치하지 않습니다. "
            "전체 refresh를 다시 실행해 주세요."
        )
        return {
            "status": "STALE",
            "reason": reason,
            "generated_at": briefs_payload.get("generated_at"),
            "source_trends_generated_at": briefs_payload.get("source_trends_generated_at"),
            "companies": unavailable,
        }

    articles_by_id = {
        str(article.get("article_id")): article
        for article in articles
        if isinstance(article, Mapping) and article.get("article_id")
    }
    raw_companies = {
        str(company.get("company_id")): company
        for company in briefs_payload.get("companies", [])
        if isinstance(company, Mapping) and company.get("company_id")
    }
    companies: list[dict[str, Any]] = []
    for company_id, company_name in COMPANY_INTELLIGENCE_ORDER:
        raw = raw_companies.get(company_id)
        if raw is None:
            companies.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "status": "UNAVAILABLE",
                    "reason": f"생성 결과에 {company_name} 데이터가 없습니다.",
                    "weekly_summary_ko": "",
                    "briefs": [],
                    "monitoring_items": [],
                }
            )
            continue
        companies.append(
            {
                "company_id": company_id,
                "company_name": str(raw.get("company_name") or company_name),
                "status": "AVAILABLE",
                "generation_status": raw.get("generation_status", "GENERATED"),
                "generation_note": raw.get("generation_note", ""),
                "failed_briefs": raw.get("failed_briefs", []),
                "weekly_summary_ko": str(raw.get("weekly_summary_ko") or ""),
                "briefs": [
                    _attach_evidence(item, articles_by_id)
                    for item in raw.get("briefs", [])
                    if isinstance(item, Mapping)
                ],
                "monitoring_items": [
                    _attach_evidence(item, articles_by_id)
                    for item in raw.get("monitoring_items", [])
                    if isinstance(item, Mapping)
                ],
            }
        )
    return {
        "status": status,
        "reason": "일부 Main Brief 생성이 미완료입니다. 성공한 항목과 Monitoring을 표시합니다." if status == "PARTIAL" else "",
        "generated_at": briefs_payload.get("generated_at"),
        "source_trends_generated_at": briefs_payload.get("source_trends_generated_at"),
        "companies": companies,
    }


def materialize_relative_times(
    articles: Sequence[Mapping[str, Any]], reference: datetime
) -> list[dict[str, Any]]:
    """Turn the fallback's `hours_ago` offsets into timestamps inside the window.

    The demo file stores offsets rather than fixed dates so the chart and the
    48-hour share stay meaningful whenever it is shown. These are synthetic
    articles and the screen labels them as such.
    """
    materialized: list[dict[str, Any]] = []
    for article in articles:
        entry = dict(article)
        hours_ago = entry.pop("hours_ago", None)
        if isinstance(hours_ago, (int, float)) and not isinstance(hours_ago, bool):
            entry["published_at"] = (
                reference - timedelta(hours=float(hours_ago))
            ).isoformat()
        materialized.append(entry)
    return materialized


def watch_area_label(key: Any) -> str:
    area = WATCH_AREAS.get(str(key or ""), {})
    return str(area.get("label") or "금융 전반")


def _ratio(part: int, whole: int) -> float:
    return (part / whole) if whole else 0.0


def daily_counts(
    articles: Sequence[Mapping[str, Any]],
    *,
    window_days: int = WINDOW_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Article count per day for the mini chart, oldest day first."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days = [(reference - timedelta(days=offset)).date() for offset in range(window_days - 1, -1, -1)]
    counts = Counter()
    for article in articles:
        published = parse_datetime(article.get("published_at"))
        if published is not None:
            counts[published.date()] += 1
    return [{"date": day.isoformat(), "label": f"{day.month}/{day.day}", "count": counts.get(day, 0)} for day in days]


def compute_trend_metrics(
    trend: Mapping[str, Any],
    articles_by_id: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    linked = [
        dict(articles_by_id[article_id])
        for article_id in trend.get("article_ids", [])
        if article_id in articles_by_id
    ]
    linked.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)

    sources = {str(item.get("source") or "").strip() for item in linked}
    sources.discard("")
    recent_cutoff = reference - timedelta(hours=RECENT_HOURS)
    recent = [
        item
        for item in linked
        if (parsed := parse_datetime(item.get("published_at"))) is not None
        and parsed >= recent_cutoff
    ]
    languages = Counter(str(item.get("language") or "en") for item in linked)
    areas = Counter(str(item.get("watch_area") or "") for item in linked)
    latest = linked[0].get("published_at") if linked else None

    return {
        "articles": linked,
        "article_count": len(linked),
        "source_count": len(sources),
        "recent_48h_count": len(recent),
        "recent_48h_share": _ratio(len(recent), len(linked)),
        "language_mix": {"ko": languages.get("ko", 0), "en": languages.get("en", 0)},
        "latest_published_at": latest,
        "watch_area": areas.most_common(1)[0][0] if areas else "",
        "daily_counts": daily_counts(linked, window_days=window_days, now=reference),
    }


def rank_trends(trends: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Volume, source diversity and recency, each normalised against the top trend.

    priority = 0.5 * (articles / max articles)
             + 0.3 * (sources / max sources)
             + 0.2 * (share published in the last 48h)
    """
    if not trends:
        return []
    max_articles = max(int(item.get("article_count", 0)) for item in trends) or 1
    max_sources = max(int(item.get("source_count", 0)) for item in trends) or 1

    scored: list[dict[str, Any]] = []
    for trend in trends:
        entry = dict(trend)
        entry["priority_score"] = round(
            WEIGHT_ARTICLES * _ratio(int(entry.get("article_count", 0)), max_articles)
            + WEIGHT_SOURCES * _ratio(int(entry.get("source_count", 0)), max_sources)
            + WEIGHT_RECENCY * float(entry.get("recent_48h_share", 0.0)),
            4,
        )
        scored.append(entry)

    scored.sort(
        key=lambda item: (item["priority_score"], item["article_count"]), reverse=True
    )
    for rank, entry in enumerate(scored, start=1):
        entry["rank"] = rank
    return scored


def _collection_stats(
    articles: Sequence[Mapping[str, Any]], trend_count: int
) -> dict[str, Any]:
    sources = {str(item.get("source") or "").strip() for item in articles}
    sources.discard("")
    languages = Counter(str(item.get("language") or "en") for item in articles)
    return {
        "article_count": len(articles),
        "source_count": len(sources),
        "trend_count": trend_count,
        "window_days": WINDOW_DAYS,
        "language_mix": {"ko": languages.get("ko", 0), "en": languages.get("en", 0)},
    }


def build_payload(
    raw: Mapping[str, Any],
    *,
    status: str,
    source_path: Path | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    articles = _as_articles(raw.get("articles"))
    if raw.get("is_synthetic"):
        articles = materialize_relative_times(articles, reference)
    articles_by_id = {
        str(item.get("article_id")): item for item in articles if item.get("article_id")
    }
    window_days = raw.get("window_days")
    if not isinstance(window_days, int) or window_days <= 0:
        window_days = WINDOW_DAYS

    enriched: list[dict[str, Any]] = []
    for trend in raw.get("trends", []) or []:
        if not isinstance(trend, Mapping):
            continue
        entry = dict(trend)
        entry.update(
            compute_trend_metrics(
                trend, articles_by_id, now=reference, window_days=window_days
            )
        )
        if entry["article_count"]:
            enriched.append(entry)

    return {
        "status": status,
        "generated_at": raw.get("generated_at"),
        "window_days": window_days,
        "model": raw.get("model"),
        "is_synthetic": bool(raw.get("is_synthetic")),
        "notice": raw.get("notice", ""),
        "source_path": str(source_path) if source_path else "",
        "trends": rank_trends(enriched),
        "articles": articles,
        "stats": _collection_stats(articles, len(enriched)),
        "collection": raw.get("collection", {}),
    }


def _is_fresh(raw: Mapping[str, Any], reference: datetime) -> bool:
    generated = parse_datetime(raw.get("generated_at"))
    if generated is None:
        return False
    return (reference - generated) <= timedelta(hours=LIVE_FRESH_HOURS)


def default_live_path() -> Path:
    """GFR_LIVE_TRENDS_PATH lets tests pin the payload instead of reading data/live."""
    override = os.environ.get("GFR_LIVE_TRENDS_PATH", "").strip()
    return Path(override) if override else LIVE_TRENDS_PATH


def load_trend_feed(
    *,
    live_path: Path | str | None = None,
    refresh_path: Path | str | None = None,
    company_briefs_path: Path | str | None = None,
    articles_path: Path | str | None = None,
    fallback_path: Path = FALLBACK_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prefer a valid live payload; otherwise fall back to the bundled demo file."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    live_path = Path(live_path) if live_path else default_live_path()
    refresh_path = (
        Path(refresh_path)
        if refresh_path
        else Path(live_path).with_name(LIVE_REFRESH_PATH.name)
    )
    company_briefs_path = (
        Path(company_briefs_path)
        if company_briefs_path
        else Path(live_path).with_name(LIVE_COMPANY_BRIEFS_PATH.name)
    )
    articles_path = (
        Path(articles_path)
        if articles_path
        else Path(live_path).with_name(LIVE_ARTICLES_PATH.name)
    )
    refresh_status = _read_json(refresh_path) or {}
    company_briefs = _read_json(company_briefs_path)
    article_registry = _as_articles(_read_json_value(articles_path))
    live = _read_json(Path(live_path))
    if live and live.get("trends") and _as_articles(live.get("articles")):
        payload = build_payload(
            live,
            status="LIVE" if _is_fresh(live, reference) else "CACHED",
            source_path=Path(live_path),
            now=reference,
        )
        if payload["trends"]:
            payload["refresh"] = refresh_status
            payload["company_intelligence"] = build_company_intelligence(
                company_briefs,
                article_registry or payload["articles"],
                trends_generated_at=payload.get("generated_at"),
            )
            attach_previous_briefs(payload["company_intelligence"], Path(company_briefs_path).parent)
            return payload

    fallback = _read_json(Path(fallback_path)) or {}
    payload = build_payload(
        fallback, status="DEMO", source_path=Path(fallback_path), now=reference
    )
    if not payload["trends"]:
        payload["notice"] = payload.get("notice") or "표시할 트렌드 데이터가 없습니다."
    payload["refresh"] = refresh_status
    payload["company_intelligence"] = build_company_intelligence(
        None,
        [],
        trends_generated_at=payload.get("generated_at"),
        is_synthetic=True,
    )
    return payload


def save_live_payload(
    trends: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    *,
    collection: Mapping[str, Any] | None = None,
    live_dir: Path = LIVE_DIR,
) -> Path:
    """Write the runtime files. data/live is git-ignored on purpose."""
    directory = Path(live_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": trends.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "window_days": trends.get("window_days", WINDOW_DAYS),
        "model": trends.get("model"),
        "analyzed_article_count": trends.get("analyzed_article_count"),
        "llm_diagnostics": trends.get("llm_diagnostics", {}),
        "is_synthetic": False,
        "collection": dict(collection or {}),
        "trends": list(trends.get("trends", [])),
        "articles": [dict(item) for item in articles],
    }
    (directory / "latest_articles.json").write_text(
        json.dumps(list(articles), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    target = directory / "latest_trends.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def save_refresh_status(
    status: Mapping[str, Any], *, live_dir: Path = LIVE_DIR
) -> Path:
    """Persist the latest refresh attempt separately from the last good trends."""
    directory = Path(live_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / LIVE_REFRESH_PATH.name
    target.write_text(
        json.dumps(dict(status), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _save_json_atomically(payload: Mapping[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return target


def save_company_relevance(
    payload: Mapping[str, Any], *, live_dir: Path = LIVE_DIR
) -> Path:
    """Atomically persist relevance for the current trend generation."""
    return _save_json_atomically(
        payload, Path(live_dir) / LIVE_COMPANY_RELEVANCE_PATH.name
    )


def save_company_briefs(
    payload: Mapping[str, Any], *, live_dir: Path = LIVE_DIR,
    articles: Sequence[Mapping[str, Any]] = (),
) -> Path:
    """Atomically persist company briefs without risking a truncated JSON file."""
    # Save an evidence-complete successful snapshot before replacing current state.
    cache_company_briefs(payload, articles, live_dir=Path(live_dir))
    return _save_json_atomically(payload, Path(live_dir) / LIVE_COMPANY_BRIEFS_PATH.name)


def cache_company_briefs(payload, articles, *, live_dir: Path) -> None:
    if not payload or payload.get("status") not in {"GENERATED", "PARTIAL"}:
        return
    path = live_dir / "latest_company_briefs_success.json"
    cache = _read_json(path) or {"companies": {}}
    registry = {a["article_id"]: a for a in articles if a.get("article_id")}
    for raw in payload.get("companies", []):
        if not raw.get("company_id"):
            continue
        # Keep a previous full result when the new attempt produced only Monitoring.
        if raw.get("generation_status") == "PARTIAL" and not raw.get("briefs"):
            continue
        company = dict(raw)
        for field in ("briefs", "monitoring_items"):
            company[field] = [_attach_evidence(item, registry) for item in raw.get(field, [])]
        snapshot = {"generated_at": payload.get("generated_at"),
                    "source_trends_generated_at": payload.get("source_trends_generated_at"),
                    "company": company}
        history = cache["companies"].get(raw["company_id"], [])
        if history and history[0].get("generated_at") == snapshot["generated_at"]:
            continue
        cache["companies"][raw["company_id"]] = [snapshot, *history][:5]
    _save_json_atomically(cache, path)


def preserve_previous_briefs(live_dir: Path) -> None:
    """Migrate an existing successful result before new collection replaces articles."""
    previous = _read_json(live_dir / LIVE_COMPANY_BRIEFS_PATH.name)
    trends = _read_json(live_dir / LIVE_TRENDS_PATH.name) or {}
    if previous and previous.get("source_trends_generated_at") == trends.get("generated_at"):
        cache_company_briefs(previous, _as_articles(trends.get("articles")), live_dir=live_dir)


def attach_previous_briefs(intelligence, live_dir: Path) -> None:
    cache = _read_json(live_dir / "latest_company_briefs_success.json") or {}
    for company in intelligence.get("companies", []):
        if company.get("status") == "AVAILABLE" and company.get("generation_status") != "PARTIAL":
            continue
        history = cache.get("companies", {}).get(company["company_id"], [])
        snapshot = next((item for item in history if item.get("generated_at") != intelligence.get("generated_at")), None)
        if snapshot:
            company["previous_success"] = snapshot
