"""Collect recent finance headlines from public RSS feeds.

Deliberately small: RSS only, no article-body crawling, no browser automation and
no ML models. Only what a feed already hands us (title, source, timestamp, URL,
short description) is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import hashlib
import re
from typing import Any, Iterable, Sequence
import urllib.parse
import xml.etree.ElementTree as ET


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

GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"
FEED_LOCALES: dict[str, dict[str, str]] = {
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_key": "global_query"},
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko", "query_key": "korean_query"},
}

DEFAULT_WINDOW_DAYS = 7
DEFAULT_TIMEOUT = 12
USER_AGENT = "HanwhaGlobalFinanceRadar/0.1 (prototype; RSS only)"
TITLE_MATCH_RATIO = 0.86
SUMMARY_MAX_CHARS = 320

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


def build_feed_specs(
    watch_areas: dict[str, dict[str, str]] | None = None,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[FeedSpec]:
    """One search feed per watch area per language."""
    areas = watch_areas or WATCH_AREAS
    specs: list[FeedSpec] = []
    for area_key, area in areas.items():
        for language, locale in FEED_LOCALES.items():
            query = area.get(locale["query_key"], "")
            if not query:
                continue
            params = {
                "q": f"{query} when:{max(1, int(window_days))}d",
                "hl": locale["hl"],
                "gl": locale["gl"],
                "ceid": locale["ceid"],
            }
            specs.append(
                FeedSpec(
                    url=f"{GOOGLE_NEWS_SEARCH}?{urllib.parse.urlencode(params)}",
                    watch_area=area_key,
                    language=language,
                )
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
    """Drop repeats: same URL, then near-identical headlines (syndication)."""
    kept: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    normalized_kept: list[str] = []

    for article in sorted(
        articles, key=lambda item: str(item.get("published_at") or ""), reverse=True
    ):
        url_key = canonical_url(article.get("url"))
        if url_key and url_key in seen_urls:
            continue
        title_key = normalize_title(article.get("title"))
        if not title_key or title_key in seen_titles:
            continue
        if any(
            SequenceMatcher(None, title_key, existing).ratio() >= TITLE_MATCH_RATIO
            for existing in normalized_kept
        ):
            continue

        if url_key:
            seen_urls.add(url_key)
        seen_titles.add(title_key)
        normalized_kept.append(title_key)
        kept.append(article)

    kept.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    return kept


def fetch_feed_text(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
    import requests  # imported lazily so parsing stays usable without network deps

    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def collect_articles(
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    watch_areas: dict[str, dict[str, str]] | None = None,
    fetcher=fetch_feed_text,
    now: datetime | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch every feed; one failing feed must not stop the collection."""
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    specs = build_feed_specs(watch_areas, window_days=window_days)
    raw: list[dict[str, Any]] = []
    feed_reports: list[dict[str, Any]] = []

    for spec in specs:
        report: dict[str, Any] = {
            "watch_area": spec.watch_area,
            "language": spec.language,
            "ok": False,
            "count": 0,
        }
        try:
            xml_text = fetcher(spec.url, timeout=timeout)
            parsed = parse_feed(
                xml_text,
                watch_area=spec.watch_area,
                language=spec.language,
                fetched_at=reference,
            )
            raw.extend(parsed)
            report.update(ok=True, count=len(parsed))
        except Exception as exc:  # noqa: BLE001 - a broken feed is expected, not fatal
            report["error"] = f"{type(exc).__name__}: {exc}"
        feed_reports.append(report)

    recent = within_window(raw, window_days=window_days, now=reference)
    articles = dedupe_articles(recent)
    debug = {
        "collected_at": reference.isoformat(),
        "window_days": window_days,
        "feeds_total": len(specs),
        "feeds_ok": sum(1 for item in feed_reports if item["ok"]),
        "raw_count": len(raw),
        "in_window_count": len(recent),
        "deduped_count": len(articles),
        "feeds": feed_reports,
    }
    return articles, debug
