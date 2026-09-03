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
from typing import Any, Mapping, Sequence

from rag_finance.ingestion.rss_collector import WATCH_AREAS, parse_datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = PROJECT_ROOT / "data" / "live"
LIVE_TRENDS_PATH = LIVE_DIR / "latest_trends.json"
LIVE_ARTICLES_PATH = LIVE_DIR / "latest_articles.json"
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


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_articles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


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
    fallback_path: Path = FALLBACK_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prefer a valid live payload; otherwise fall back to the bundled demo file."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    live_path = Path(live_path) if live_path else default_live_path()
    live = _read_json(Path(live_path))
    if live and live.get("trends") and _as_articles(live.get("articles")):
        payload = build_payload(
            live,
            status="LIVE" if _is_fresh(live, reference) else "CACHED",
            source_path=Path(live_path),
            now=reference,
        )
        if payload["trends"]:
            return payload

    fallback = _read_json(Path(fallback_path)) or {}
    payload = build_payload(
        fallback, status="DEMO", source_path=Path(fallback_path), now=reference
    )
    if not payload["trends"]:
        payload["notice"] = payload.get("notice") or "표시할 트렌드 데이터가 없습니다."
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
