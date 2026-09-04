"""Collect recent finance headlines from public RSS feeds.

Deliberately small: RSS only, no article-body crawling, no browser automation and
no ML models. Only what a feed already hands us (title, source, timestamp, URL,
short description) is kept.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Iterable, Sequence
import urllib.parse
import xml.etree.ElementTree as ET

from rag_finance.profiles.company_profiles import (
    DEFAULT_PROFILES_DIR,
    load_all_company_profiles,
)


# Broad areas rather than narrow questions, so the watch list does not go stale.
WATCH_AREAS: dict[str, dict[str, str]] = {
    "rates_liquidity": {
        "label": "금리·물가·유동성",
        "global_query": "interest rates OR inflation OR bond yields OR central bank",
        "korean_query": "금리 OR 물가 OR 국채금리 OR 중앙은행",
    },
    "risk_flows": {
        "label": "시장위험·자금 흐름",
        "global_query": "financial markets OR market volatility OR capital flows OR credit risk",
        "korean_query": "금융시장 OR 시장 변동성 OR 자금 흐름 OR 신용위험",
    },
    "regulation_innovation": {
        "label": "금융규제·디지털금융",
        "global_query": (
            "financial regulation OR digital finance OR tokenization OR stablecoin OR financial AI"
        ),
        "korean_query": "금융규제 OR 디지털금융 OR 토큰증권 OR 스테이블코인 OR 금융 AI",
    },
}

# Direct publisher feeds, verified to return items. The search feeds above are
# rate-limited per host and answer 200 with an empty channel when throttled, so
# these keep a refresh useful when that happens. Their articles are classified
# into a watch area by keyword rather than by query.
BACKUP_FEEDS: tuple[dict[str, str], ...] = (
    {
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "language": "en",
        "default_area": "rates_liquidity",
    },
    {
        "url": "https://www.yna.co.kr/rss/economy.xml",
        "language": "ko",
        "default_area": "risk_flows",
    },
    {
        "url": "https://www.hankyung.com/feed/economy",
        "language": "ko",
        "default_area": "risk_flows",
    },
    {
        "url": "https://www.mk.co.kr/rss/30100041/",
        "language": "ko",
        "default_area": "risk_flows",
    },
)

# Keyword hints for classifying general economy feeds into a watch area.
AREA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rates_liquidity": (
        "금리", "물가", "국채", "채권", "중앙은행", "한국은행", "연준", "기준금리", "유동성",
        "inflation", "interest rate", "bond", "yield", "central bank", "monetary", "liquidity",
    ),
    "regulation_innovation": (
        "규제", "금융위", "금감원", "감독", "토큰", "스테이블코인", "가상자산", "디지털금융",
        "인공지능", "제도",
        "regulation", "supervis", "token", "stablecoin", "digital finance", "crypto",
        "artificial intelligence",
    ),
    "risk_flows": (
        "증시", "환율", "변동성", "자금", "외국인", "신용", "리스크", "위험",
        "market", "volatility", "credit", "capital flow", "currency", "risk",
    ),
}

GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"
FEED_LOCALES: dict[str, dict[str, str]] = {
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_key": "global_query"},
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko", "query_key": "korean_query"},
}

DEFAULT_WINDOW_DAYS = 7
DEFAULT_TIMEOUT = 12
DEFAULT_RETRIES = 1
RETRY_BACKOFF_SECONDS = 1.0
MAX_WORKERS = 8
USER_AGENT = "HanwhaGlobalFinanceRadar/0.1 (prototype; RSS only)"
TITLE_MATCH_RATIO = 0.86
SUMMARY_MAX_CHARS = 320
SOURCE_MODES = ("profiles", "common", "both")
DEFAULT_SOURCE_MODE = "common"
CANDIDATE_METADATA_FIELDS = (
    "candidate_companies",
    "matched_topic_ids",
    "matched_query_ids",
)

# Why a collection produced nothing, so the caller can tell the user what to fix.
REASON_OK = "ok"
REASON_MISSING_DEPENDENCY = "missing_dependency"
REASON_ALL_FEEDS_FAILED = "all_feeds_failed"
REASON_EMPTY_FEEDS = "empty_feeds"
REASON_NO_RECENT_ARTICLES = "no_recent_articles"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^0-9a-z가-힣\s]")
# Google News appends " - Publisher" to headlines.
_SOURCE_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "ocid", "ncid", "cmpid")


@dataclass(frozen=True)
class FeedSpec:
    url: str
    watch_area: str
    language: str
    provider: str = "search"
    classify: bool = False
    query_id: str | None = None
    company_id: str | None = None
    topic_ids: tuple[str, ...] = ()


def _search_feed_url(query: str, language: str, window_days: int) -> str:
    locale = FEED_LOCALES[language]
    params = {
        "q": f"{query} when:{max(1, int(window_days))}d",
        "hl": locale["hl"],
        "gl": locale["gl"],
        "ceid": locale["ceid"],
    }
    return f"{GOOGLE_NEWS_SEARCH}?{urllib.parse.urlencode(params)}"


def build_profile_feed_specs(
    profiles: dict[str, dict[str, Any]] | None = None,
    *,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[FeedSpec]:
    """Build one Google News feed for every validated runtime profile query."""
    loaded = profiles if profiles is not None else load_all_company_profiles(profiles_dir)
    specs: list[FeedSpec] = []
    for company_id in sorted(loaded):
        profile = loaded[company_id]
        for query in profile["rss_queries"]:
            language = str(query["language"])
            topic_ids = tuple(str(item) for item in query["topic_ids"])
            specs.append(
                FeedSpec(
                    url=_search_feed_url(str(query["query"]), language, window_days),
                    watch_area=topic_ids[0] if topic_ids else "company_profile",
                    language=language,
                    provider="profile_search",
                    query_id=str(query["id"]),
                    company_id=company_id,
                    topic_ids=topic_ids,
                )
            )
    return specs


def classify_watch_area(text: str, default: str) -> str:
    """Pick a watch area by keyword; used for general economy feeds."""
    lowered = str(text or "").lower()
    for area, keywords in AREA_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return area
    return default


def build_feed_specs(
    watch_areas: dict[str, dict[str, str]] | None = None,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    include_backup: bool = True,
    source_mode: str = DEFAULT_SOURCE_MODE,
    profiles: dict[str, dict[str, Any]] | None = None,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
) -> list[FeedSpec]:
    """Build common, profile-specific, or combined RSS feed specifications."""
    if source_mode not in SOURCE_MODES:
        raise ValueError(
            f"Invalid RSS source_mode {source_mode!r}; expected one of {', '.join(SOURCE_MODES)}"
        )
    areas = watch_areas or WATCH_AREAS
    specs: list[FeedSpec] = []
    if source_mode in {"common", "both"}:
        for area_key, area in areas.items():
            for language, locale in FEED_LOCALES.items():
                query = area.get(locale["query_key"], "")
                if not query:
                    continue
                specs.append(
                    FeedSpec(
                        url=_search_feed_url(query, language, window_days),
                        watch_area=area_key,
                        language=language,
                        query_id=f"common_{area_key}_{language}",
                    )
                )

    if source_mode in {"profiles", "both"}:
        specs.extend(
            build_profile_feed_specs(
                profiles,
                profiles_dir=profiles_dir,
                window_days=window_days,
            )
        )

    if include_backup and source_mode in {"common", "both"}:
        specs.extend(
            FeedSpec(
                url=feed["url"],
                watch_area=feed["default_area"],
                language=feed["language"],
                provider="direct",
                classify=True,
            )
            for feed in BACKUP_FEEDS
        )
    return specs


def strip_html(value: Any) -> str:
    text = _TAG_RE.sub(" ", str(value or ""))
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return _WS_RE.sub(" ", text).strip()


def strip_source_suffix(title: str) -> str:
    """Drop the trailing ' - Publisher' that aggregators append."""
    cleaned = _SOURCE_SUFFIX_RE.sub("", title).strip()
    return cleaned or title.strip()


def normalize_title(title: Any) -> str:
    """Lowercased, punctuation-free form used only for duplicate detection."""
    text = strip_source_suffix(strip_html(title)).lower()
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()


def canonical_url(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return raw
    kept = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith(_TRACKING_PARAMS)
    ]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urllib.parse.urlencode(kept), "")
    )


def make_article_id(url: Any, title: Any) -> str:
    """Stable across runs: same story keeps the same id."""
    seed = canonical_url(url) or normalize_title(title)
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"A{digest.upper()}"


def parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(element: ET.Element | None) -> str:
    return strip_html(element.text if element is not None else "")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(
    xml_text: str,
    *,
    watch_area: str,
    language: str,
    fetched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom into normalized article dicts."""
    stamp = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    entries = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    articles: list[dict[str, Any]] = []
    for entry in entries:
        children = {_local(child.tag): child for child in entry}
        title = strip_source_suffix(_text(children.get("title")))
        if not title:
            continue

        link = _text(children.get("link"))
        if not link:
            for child in entry:
                if _local(child.tag) == "link" and child.get("href"):
                    link = child.get("href", "")
                    break

        published = parse_datetime(
            _text(children.get("pubDate"))
            or _text(children.get("published"))
            or _text(children.get("updated"))
        )
        if published is None:
            continue

        source_node = children.get("source")
        source = _text(source_node)
        if not source:
            source = urllib.parse.urlsplit(link).netloc.replace("www.", "") or "출처 미상"

        summary = strip_html(
            _text(children.get("description")) or _text(children.get("summary"))
        )
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = summary[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "…"

        articles.append(
            {
                "article_id": make_article_id(link, title),
                "title": title,
                "source": source,
                "published_at": published.isoformat(),
                "url": link,
                "summary": summary,
                "language": language,
                "watch_area": watch_area,
                "fetched_at": stamp.isoformat(),
            }
        )
    return articles


def within_window(
    articles: Iterable[dict[str, Any]],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = reference - timedelta(days=window_days)
    kept: list[dict[str, Any]] = []
    for article in articles:
        published = parse_datetime(article.get("published_at"))
        if published is None or published < cutoff:
            continue
        # Feeds occasionally carry a clock-skewed future timestamp.
        if published > reference + timedelta(hours=6):
            continue
        kept.append(article)
    return kept


def dedupe_articles(articles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop repeats while merging profile-query candidate metadata."""
    kept: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    normalized_kept: list[tuple[str, dict[str, Any]]] = []

    def merge_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
        for field in CANDIDATE_METADATA_FIELDS:
            values = list(target.get(field) or []) + list(source.get(field) or [])
            target[field] = sorted({str(value) for value in values if str(value).strip()})

    for article in sorted(
        articles, key=lambda item: str(item.get("published_at") or ""), reverse=True
    ):
        entry = dict(article)
        merge_metadata(entry, {})
        url_key = canonical_url(entry.get("url"))
        duplicate = by_url.get(url_key) if url_key else None
        title_key = normalize_title(article.get("title"))
        if duplicate is None and title_key:
            duplicate = by_title.get(title_key)
        if duplicate is None and title_key:
            duplicate = next(
                (
                    existing_article
                    for existing_title, existing_article in normalized_kept
                    if SequenceMatcher(None, title_key, existing_title).ratio()
                    >= TITLE_MATCH_RATIO
                ),
                None,
            )
        if duplicate is not None:
            merge_metadata(duplicate, entry)
            continue
        if not title_key:
            continue

        if url_key:
            by_url[url_key] = entry
        by_title[title_key] = entry
        normalized_kept.append((title_key, entry))
        kept.append(entry)

    kept.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    return kept


def fetch_feed_text(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    import requests  # imported lazily so parsing stays usable without network deps

    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def _fetch_one(
    spec: FeedSpec,
    *,
    fetcher,
    timeout: int,
    retries: int,
    window_days: int,
    reference: datetime,
) -> dict[str, Any]:
    """Fetch and parse a single feed. Never raises: the report carries the failure."""
    report: dict[str, Any] = {
        "watch_area": spec.watch_area,
        "language": spec.language,
        "provider": spec.provider,
        "ok": False,
        "count": 0,
        "attempts": 0,
        "query_id": spec.query_id,
        "company_id": spec.company_id,
        "topic_ids": list(spec.topic_ids),
    }
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        report["attempts"] = attempt + 1
        try:
            xml_text = fetcher(spec.url, timeout=timeout)
        except ImportError as exc:
            # A missing dependency will not fix itself on a retry.
            report.update(error=f"{type(exc).__name__}: {exc}", error_kind="dependency")
            return report
        except Exception as exc:  # noqa: BLE001 - a broken feed is expected, not fatal
            last_error = exc
            if attempt < retries:
                time.sleep(RETRY_BACKOFF_SECONDS)
            continue

        parsed = parse_feed(
            xml_text,
            watch_area=spec.watch_area,
            language=spec.language,
            fetched_at=reference,
        )
        if spec.classify:
            for article in parsed:
                article["watch_area"] = classify_watch_area(
                    f"{article.get('title', '')} {article.get('summary', '')}",
                    spec.watch_area,
                )
        if spec.company_id:
            for article in parsed:
                article["candidate_companies"] = [spec.company_id]
                article["matched_topic_ids"] = list(spec.topic_ids)
                article["matched_query_ids"] = [spec.query_id] if spec.query_id else []
        # A provider that throttles answers 200 with a valid but item-less feed,
        # so "responded" and "returned articles" have to be tracked separately.
        report.update(ok=True, count=len(parsed), empty=not parsed, articles=parsed)
        return report

    report.update(
        error=f"{type(last_error).__name__}: {last_error}", error_kind="request"
    )
    return report


def collect_articles(
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    watch_areas: dict[str, dict[str, str]] | None = None,
    fetcher=fetch_feed_text,
    now: datetime | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    max_workers: int = MAX_WORKERS,
    include_backup: bool = True,
    source_mode: str = DEFAULT_SOURCE_MODE,
    profiles: dict[str, dict[str, Any]] | None = None,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch every feed in parallel; one failing feed must not stop the collection."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    specs = build_feed_specs(
        watch_areas,
        window_days=window_days,
        include_backup=include_backup,
        source_mode=source_mode,
        profiles=profiles,
        profiles_dir=profiles_dir,
    )
    started = time.perf_counter()

    workers = max(1, min(max_workers, len(specs) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        feed_reports = list(
            pool.map(
                lambda spec: _fetch_one(
                    spec,
                    fetcher=fetcher,
                    timeout=timeout,
                    retries=retries,
                    window_days=window_days,
                    reference=reference,
                ),
                specs,
            )
        )

    raw: list[dict[str, Any]] = []
    for report in feed_reports:
        raw.extend(report.pop("articles", []))

    recent = within_window(raw, window_days=window_days, now=reference)
    articles = dedupe_articles(recent)

    ok_reports = [item for item in feed_reports if item["ok"]]
    with_articles = [item for item in ok_reports if item["count"]]
    if not ok_reports:
        if any(item.get("error_kind") == "dependency" for item in feed_reports):
            reason = REASON_MISSING_DEPENDENCY
        else:
            reason = REASON_ALL_FEEDS_FAILED
    elif not with_articles:
        reason = REASON_EMPTY_FEEDS
    elif not articles:
        reason = REASON_NO_RECENT_ARTICLES
    else:
        reason = REASON_OK

    debug = {
        "collected_at": reference.isoformat(),
        "window_days": window_days,
        "source_mode": source_mode,
        "profile_count": len({spec.company_id for spec in specs if spec.company_id}),
        "query_count": sum(1 for spec in specs if spec.provider != "direct"),
        "feeds_total": len(specs),
        "feeds_ok": len(ok_reports),
        "feeds_with_articles": len(with_articles),
        "feeds_empty": len(ok_reports) - len(with_articles),
        "feeds_failed": len(feed_reports) - len(ok_reports),
        "ok_by_language": {
            language: sum(1 for item in ok_reports if item["language"] == language)
            for language in FEED_LOCALES
        },
        "with_articles_by_language": {
            language: sum(1 for item in with_articles if item["language"] == language)
            for language in FEED_LOCALES
        },
        "raw_count": len(raw),
        "in_window_count": len(recent),
        "deduped_count": len(articles),
        "language_counts": {
            language: sum(1 for item in articles if item.get("language") == language)
            for language in FEED_LOCALES
        },
        "company_candidate_counts": {
            company_id: sum(
                1
                for article in articles
                if company_id in (article.get("candidate_companies") or [])
            )
            for company_id in sorted(
                {spec.company_id for spec in specs if spec.company_id}
            )
        },
        "reason": reason,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "feeds": feed_reports,
    }
    return articles, debug
