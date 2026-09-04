"""Hanwha Global Finance Radar — weekly AI trend briefing.

A separate entry point from app/streamlit_app.py, which stays as the legacy
Signal Radar. Run with:  streamlit run app/trend_feed_app.py
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trend_feed_data import (
    LIVE_TRENDS_PATH,
    WINDOW_DAYS,
    load_trend_feed,
    watch_area_label,
)
from rag_finance.ingestion.rss_collector import parse_datetime

PRODUCT_NAME = "Hanwha Global Finance Radar"
SUBTITLE = "글로벌 금융 흐름을 압축하는 AI 트렌드 브리핑"
LOGO_PATH = PROJECT_ROOT / "assets" / "hanwha_logo.png"
RANK_WORDS = {1: "01", 2: "02", 3: "03"}
# Evidence shown inline on a brief card; the rest go in an expander.
CI_EVIDENCE_PREVIEW = 2

st.set_page_config(
    page_title=PRODUCT_NAME,
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root {
        --gf-bg: #F6F5F1;
        --gf-card: #FFFFFF;
        --gf-hero: #1D242E;
        --gf-hero-2: #2A3441;
        --gf-orange: #F57E20;
        --gf-orange-ink: #B85C00;
        --gf-ink: #1B1F24;
        --gf-ink-2: #3D444C;
        --gf-ink-3: #6E757D;
        --gf-line: #E4E1DA;
        --gf-font: "Pretendard", "Pretendard Variable", -apple-system,
            "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "Segoe UI",
            system-ui, sans-serif;
    }
    /* Scoped to text nodes: a blanket attribute selector would also override
       Streamlit's Material Symbols font and print ligature names as text. */
    html, body, .stApp,
    .stApp p, .stApp span, .stApp div, .stApp li, .stApp a,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp button, .stApp label {
        font-family: var(--gf-font);
    }
    [data-testid="stIconMaterial"], .material-symbols-rounded {
        font-family: "Material Symbols Rounded" !important;
    }
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
        display: none !important;
    }
    .stApp {background: var(--gf-bg);}
    .block-container {max-width: 1360px; padding-top: 1.5rem; padding-bottom: 3.5rem;}

    /* Header */
    .gf-head {
        display: flex; align-items: flex-end; justify-content: space-between;
        gap: 1.5rem; padding-bottom: 0.9rem; margin-bottom: 0.5rem;
        border-bottom: 1px solid var(--gf-line);
    }
    .gf-head-left {display: flex; align-items: center; gap: 0.9rem;}
    .gf-logo {height: 30px; width: auto; display: block;}
    .gf-div {width: 1px; height: 32px; background: var(--gf-line);}
    .gf-title {
        font-size: 1.34rem; font-weight: 700; color: var(--gf-ink);
        letter-spacing: -0.015em; line-height: 1.2;
    }
    .gf-sub {font-size: 0.83rem; color: var(--gf-ink-3); margin-top: 0.2rem;}
    .gf-head-right {text-align: right; padding-bottom: 0.1rem;}
    .gf-status {
        display: inline-block; font-size: 0.66rem; font-weight: 700;
        letter-spacing: 0.08em; padding: 0.14rem 0.5rem; border-radius: 0.25rem;
    }
    .gf-status--live {background: var(--gf-orange); color: #FFFFFF;}
    .gf-status--cached {background: #E8E5DE; color: var(--gf-ink-2);}
    .gf-status--demo {
        background: #FFFFFF; color: var(--gf-orange-ink);
        border: 1px solid var(--gf-orange);
    }
    .gf-updated {font-size: 0.74rem; color: var(--gf-ink-3); margin-top: 0.3rem;}
    .gf-refresh {font-size: 0.7rem; margin-top: 0.12rem;}
    .gf-refresh--success {color: #2E6B4A;}
    .gf-refresh--partial {color: #8A6200;}
    .gf-refresh--failed {color: #A23A32;}

    /* Summary strip */
    .gf-strip {
        display: flex; flex-wrap: wrap; align-items: baseline;
        gap: 0 2.4rem; padding: 0.7rem 0 1.1rem;
        border-bottom: 1px solid var(--gf-line); margin-bottom: 1.3rem;
    }
    .gf-stat-label {
        font-size: 0.66rem; font-weight: 600; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--gf-ink-3);
    }
    .gf-stat-value {
        font-size: 1.28rem; font-weight: 700; color: var(--gf-ink);
        letter-spacing: -0.02em; margin-top: 0.1rem;
    }
    .gf-stat-value em {font-style: normal; font-size: 0.8rem; font-weight: 600; color: var(--gf-ink-3);}

    /* Hero */
    .gf-hero {
        background: linear-gradient(180deg, var(--gf-hero) 0%, var(--gf-hero-2) 100%);
        border-radius: 0.5rem; padding: 1.5rem 1.7rem 1.4rem; color: #FFFFFF;
        display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr);
        gap: 0 2.2rem; margin-bottom: 0.9rem;
    }
    .gf-rank {
        font-size: 0.78rem; font-weight: 700; letter-spacing: 0.16em;
        color: var(--gf-orange);
    }
    .gf-area {
        font-size: 0.68rem; font-weight: 600; letter-spacing: 0.05em;
        color: rgba(255, 255, 255, 0.62); margin-left: 0.6rem;
    }
    .gf-hero-title {
        font-size: 1.72rem; font-weight: 700; line-height: 1.32;
        letter-spacing: -0.022em; margin: 0.45rem 0 0.6rem;
    }
    .gf-hero-summary {
        font-size: 0.95rem; line-height: 1.72; color: rgba(255, 255, 255, 0.86);
        margin-bottom: 0.85rem;
    }
    .gf-why {
        border-left: 2px solid var(--gf-orange); padding-left: 0.75rem;
        font-size: 0.87rem; line-height: 1.68; color: rgba(255, 255, 255, 0.74);
    }
    .gf-hero-side {border-left: 1px solid rgba(255, 255, 255, 0.13); padding-left: 1.5rem;}
    .gf-metrics {display: flex; gap: 1.4rem; margin-bottom: 1rem;}
    .gf-metric-label {
        font-size: 0.62rem; font-weight: 600; letter-spacing: 0.07em;
        text-transform: uppercase; color: rgba(255, 255, 255, 0.5);
    }
    .gf-metric-value {font-size: 1.3rem; font-weight: 700; letter-spacing: -0.02em; margin-top: 0.05rem;}

    /* Mini chart */
    .gf-chart {display: flex; align-items: flex-end; gap: 3px; height: 42px; margin: 0.15rem 0 0.2rem;}
    .gf-bar {flex: 1; border-radius: 1px 1px 0 0; min-height: 2px;}
    .gf-chart-axis {
        display: flex; justify-content: space-between;
        font-size: 0.6rem; color: var(--gf-ink-3); margin-bottom: 0.6rem;
    }
    .gf-hero .gf-bar {background: rgba(255, 255, 255, 0.26);}
    .gf-hero .gf-bar--peak {background: var(--gf-orange);}
    .gf-hero .gf-chart-axis {color: rgba(255, 255, 255, 0.45);}
    .gf-card .gf-bar {background: #E4E1DA;}
    .gf-card .gf-bar--peak {background: var(--gf-orange);}

    /* Tags */
    .gf-tags {margin-top: 0.35rem;}
    .gf-tag {
        display: inline-block; font-size: 0.7rem; border-radius: 0.22rem;
        padding: 0.11rem 0.42rem; margin: 0 0.28rem 0.28rem 0;
        background: rgba(255, 255, 255, 0.1); color: rgba(255, 255, 255, 0.82);
    }
    .gf-card .gf-tag {background: #F2F0EB; color: var(--gf-ink-2);}

    /* Evidence lines */
    .gf-evlabel {
        font-size: 0.62rem; font-weight: 700; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--gf-ink-3); margin: 0.9rem 0 0.4rem;
    }
    .gf-hero .gf-evlabel {color: rgba(255, 255, 255, 0.45);}
    .gf-ev {
        padding: 0.42rem 0; border-top: 1px solid var(--gf-line);
        font-size: 0.83rem; line-height: 1.5;
    }
    .gf-hero .gf-ev {border-top: 1px solid rgba(255, 255, 255, 0.11);}
    .gf-ev a {color: inherit; text-decoration: none; border-bottom: 1px solid transparent;}
    .gf-ev a:hover {border-bottom-color: var(--gf-orange);}
    .gf-ev-meta {font-size: 0.7rem; color: var(--gf-ink-3); margin-top: 0.12rem;}
    .gf-hero .gf-ev-meta {color: rgba(255, 255, 255, 0.45);}

    /* Rank 2 / 3 */
    .gf-grid {display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.9rem;}
    .gf-card {
        background: var(--gf-card); border: 1px solid var(--gf-line);
        border-radius: 0.5rem; padding: 1.15rem 1.25rem 1.2rem;
        display: flex; flex-direction: column;
    }
    .gf-card .gf-rank {color: var(--gf-orange-ink);}
    .gf-card .gf-area {color: var(--gf-ink-3);}
    .gf-card-title {
        font-size: 1.13rem; font-weight: 700; color: var(--gf-ink);
        line-height: 1.4; letter-spacing: -0.015em; margin: 0.4rem 0 0.45rem;
    }
    .gf-card-summary {
        font-size: 0.86rem; line-height: 1.66; color: var(--gf-ink-2);
        margin-bottom: 0.8rem;
    }
    .gf-card .gf-metrics {gap: 1.3rem; margin-bottom: 0.7rem;}
    .gf-card .gf-metric-label {color: var(--gf-ink-3);}
    .gf-card .gf-metric-value {font-size: 1.08rem; color: var(--gf-ink);}
    .gf-card-foot {margin-top: auto;}
    .gf-synthetic {
        display: inline-block; font-size: 0.6rem; font-weight: 700;
        color: var(--gf-ink-3); border: 1px solid var(--gf-line);
        border-radius: 0.2rem; padding: 0 0.24rem; margin-left: 0.3rem;
    }
    .gf-sectionhead {
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--gf-ink-3);
        margin: 1.8rem 0 0.7rem;
    }
    .gf-note {font-size: 0.78rem; color: var(--gf-ink-3); line-height: 1.7;}
    .gf-tl {padding: 0.5rem 0; border-top: 1px solid var(--gf-line);}
    .gf-tl-title {font-size: 0.87rem; font-weight: 600; color: var(--gf-ink); line-height: 1.5;}
    .gf-tl-title a {color: inherit; text-decoration: none;}
    .gf-tl-title a:hover {border-bottom: 1px solid var(--gf-orange);}
    .gf-tl-meta {font-size: 0.72rem; color: var(--gf-ink-3); margin: 0.1rem 0 0.2rem;}
    .gf-tl-body {font-size: 0.81rem; color: var(--gf-ink-2); line-height: 1.6;}

    /* Company Intelligence */
    .gf-ci-head {
        border-top: 1px solid var(--gf-line); margin-top: 2.2rem;
        padding-top: 1.5rem; margin-bottom: 0.8rem;
    }
    .gf-ci-kicker {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: var(--gf-orange-ink);
    }
    .gf-ci-title {
        font-size: 1.4rem; font-weight: 700; color: var(--gf-ink);
        letter-spacing: -0.02em; margin-top: 0.2rem;
    }
    .gf-ci-intro {font-size: 0.82rem; color: var(--gf-ink-3); margin-top: 0.25rem;}
    .gf-ci-company {padding: 0.85rem 0 0.65rem;}
    .gf-ci-company-name {
        font-size: 1.25rem; font-weight: 700; color: var(--gf-ink);
        letter-spacing: -0.02em;
    }
    .gf-ci-summary {
        max-width: 920px; font-size: 0.92rem; color: var(--gf-ink-2);
        line-height: 1.75; margin-top: 0.35rem;
    }
    .gf-ci-alert {
        border-left: 3px solid var(--gf-orange); background: #FFF8F1;
        color: var(--gf-ink-2); padding: 0.75rem 0.9rem;
        border-radius: 0 0.35rem 0.35rem 0; font-size: 0.82rem; line-height: 1.6;
    }
    .gf-ci-subhead {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--gf-ink-3); margin: 0.9rem 0 0.5rem;
    }
    .gf-brief-card {
        background: var(--gf-card); border: 1px solid var(--gf-line);
        border-top: 3px solid var(--gf-orange); border-radius: 0.5rem;
        padding: 1.1rem 1.2rem; margin: 0.65rem 0 0.45rem;
    }
    .gf-brief-top {display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;}
    .gf-brief-title {
        font-size: 1.12rem; font-weight: 700; color: var(--gf-ink);
        line-height: 1.45; letter-spacing: -0.015em;
    }
    .gf-proof {
        flex: 0 0 auto; font-size: 0.68rem; font-weight: 600;
        color: #2E6B4A; background: #EAF4EE; border-radius: 999px;
        padding: 0.18rem 0.55rem;
    }
    .gf-brief-situation {
        font-size: 0.88rem; line-height: 1.68; color: var(--gf-ink-2);
        margin-top: 0.7rem;
    }
    .gf-brief-grid {
        display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.75rem; margin-top: 0.85rem;
    }
    .gf-brief-field {background: #F8F7F3; border-radius: 0.35rem; padding: 0.7rem 0.78rem;}
    .gf-brief-label {
        font-size: 0.63rem; font-weight: 700; letter-spacing: 0.07em;
        color: var(--gf-ink-3); margin-bottom: 0.25rem;
    }
    .gf-brief-value {font-size: 0.82rem; line-height: 1.62; color: var(--gf-ink-2);}
    .gf-ci-tags {margin-top: 0.75rem;}
    .gf-ci-tag {
        display: inline-block; font-size: 0.68rem; color: var(--gf-orange-ink);
        background: #FFF2E5; border-radius: 0.2rem; padding: 0.12rem 0.4rem;
        margin: 0 0.25rem 0.25rem 0;
    }
    .gf-watch {margin-top: 0.7rem; border-top: 1px solid var(--gf-line); padding-top: 0.55rem;}
    .gf-watch-row {font-size: 0.79rem; line-height: 1.6; color: var(--gf-ink-2);}
    .gf-ci-evidence {margin-top: 0.65rem;}
    .gf-monitor {
        border-top: 1px solid var(--gf-line); padding: 0.7rem 0.1rem;
        display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.3rem 1rem;
    }
    .gf-monitor-title {font-size: 0.88rem; font-weight: 650; color: var(--gf-ink);}
    .gf-monitor-reason {font-size: 0.78rem; line-height: 1.55; color: var(--gf-ink-3);}
    .gf-monitor-proof {font-size: 0.68rem; color: var(--gf-ink-3); white-space: nowrap;}
    [data-baseweb="tab-list"] {overflow-x: auto; scrollbar-width: thin;}
    [data-baseweb="tab"] {white-space: nowrap;}

    @media (max-width: 1100px) {
        .gf-hero {grid-template-columns: 1fr; gap: 1.3rem;}
        .gf-hero-side {border-left: 0; padding-left: 0;}
        .gf-grid {grid-template-columns: 1fr;}
    }
    @media (max-width: 700px) {
        .block-container {padding-left: 1rem; padding-right: 1rem; padding-top: 1rem;}
        .gf-head-left {align-items: flex-start;}
        .gf-logo {height: 24px;}
        .gf-div {height: 28px;}
        .gf-title {font-size: 1.05rem;}
        .gf-sub {font-size: 0.72rem;}
        .gf-strip {gap: 0.8rem 1.5rem;}
        .gf-hero {padding: 1.15rem;}
        .gf-hero-title {font-size: 1.35rem;}
        .gf-brief-top {display: block;}
        .gf-proof {display: inline-block; margin-top: 0.45rem;}
        .gf-brief-grid {grid-template-columns: 1fr;}
        .gf-monitor {grid-template-columns: 1fr;}
        .gf-monitor-proof {white-space: normal;}
    }

    div.stButton > button {
        border-radius: 0.3rem; border: 1px solid var(--gf-orange);
        color: var(--gf-orange-ink); font-size: 0.8rem; font-weight: 600;
        padding: 0.28rem 0.8rem;
    }
    div.stButton > button:hover {border-color: var(--gf-orange-ink); color: var(--gf-orange-ink);}
    [data-testid="stExpander"] details {
        border: 1px solid var(--gf-line); border-radius: 0.4rem; background: var(--gf-card);
    }
    [data-testid="stExpander"] summary {font-size: 0.82rem; font-weight: 600; color: var(--gf-ink-2);}
    </style>
    """,
    unsafe_allow_html=True,
)


def _esc(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=False)


def _logo_uri() -> str:
    try:
        return (
            "data:image/png;base64,"
            + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
        )
    except OSError:
        return ""


def _format_stamp(value: Any) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "시각 정보 없음"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _relative(value: Any, now: datetime) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return ""
    hours = (now - parsed).total_seconds() / 3600
    if hours < 1:
        return "1시간 이내"
    if hours < 24:
        return f"{int(hours)}시간 전"
    return f"{int(hours // 24)}일 전"


def _chart_html(daily: list[dict[str, Any]]) -> str:
    if not daily:
        return ""
    peak = max((int(day.get("count", 0)) for day in daily), default=0) or 1
    bars = "".join(
        '<div class="gf-bar{peak}" style="height:{height}%" title="{label} · {count}건"></div>'.format(
            peak=" gf-bar--peak" if int(day.get("count", 0)) == peak and peak > 0 else "",
            height=max(4, round(int(day.get("count", 0)) / peak * 100)),
            label=_esc(day.get("label")),
            count=int(day.get("count", 0)),
        )
        for day in daily
    )
    first, last = _esc(daily[0].get("label")), _esc(daily[-1].get("label"))
    return (
        f'<div class="gf-chart">{bars}</div>'
        f'<div class="gf-chart-axis"><span>{first}</span><span>{last}</span></div>'
    )


def _metrics_html(trend: dict[str, Any]) -> str:
    cells = (
        ("관련 기사", f"{trend.get('article_count', 0)}건"),
        ("고유 출처", f"{trend.get('source_count', 0)}개"),
        ("48시간 집중도", f"{round(float(trend.get('recent_48h_share', 0.0)) * 100)}%"),
    )
    return '<div class="gf-metrics">' + "".join(
        f'<div><div class="gf-metric-label">{_esc(label)}</div>'
        f'<div class="gf-metric-value">{_esc(value)}</div></div>'
        for label, value in cells
    ) + "</div>"


def _tags_html(trend: dict[str, Any]) -> str:
    tags = [tag for tag in trend.get("related_business_tags", []) if str(tag).strip()]
    if not tags:
        return ""
    return '<div class="gf-tags">' + "".join(
        f'<span class="gf-tag">{_esc(tag)}</span>' for tag in tags
    ) + "</div>"


def _evidence_html(trend: dict[str, Any], limit: int, now: datetime) -> str:
    rows = []
    for article in trend.get("articles", [])[:limit]:
        title = _esc(article.get("title"))
        url = str(article.get("url") or "").strip()
        headline = f'<a href="{escape(url, quote=True)}" target="_blank">{title}</a>' if url else title
        synthetic = "" if url else '<span class="gf-synthetic">합성</span>'
        meta = " · ".join(
            part
            for part in (
                _esc(article.get("source")),
                _relative(article.get("published_at"), now),
                "국내" if article.get("language") == "ko" else "해외",
            )
            if part
        )
        rows.append(
            f'<div class="gf-ev">{headline}{synthetic}'
            f'<div class="gf-ev-meta">{meta}</div></div>'
        )
    if not rows:
        return ""
    return '<div class="gf-evlabel">주요 근거</div>' + "".join(rows)


def _render_header(payload: dict[str, Any]) -> None:
    logo = _logo_uri()
    brand = (
        f'<img class="gf-logo" src="{logo}" alt="Hanwha" /><div class="gf-div"></div>'
        if logo
        else ""
    )
    status = str(payload.get("status") or "DEMO")
    status_class = {"LIVE": "live", "CACHED": "cached"}.get(status, "demo")
    refresh = payload.get("refresh") if isinstance(payload.get("refresh"), dict) else {}
    outcome = str(refresh.get("outcome") or "")
    outcome_class = outcome if outcome in {"success", "partial", "failed"} else "partial"
    outcome_label = {"success": "성공", "partial": "부분 완료", "failed": "실패"}.get(
        outcome, ""
    )
    refresh_line = ""
    if refresh.get("attempted_at"):
        refresh_line = (
            f'<div class="gf-refresh gf-refresh--{outcome_class}">'
            f'최근 시도 {_esc(_format_stamp(refresh.get("attempted_at")))}'
            f'{" · " + _esc(outcome_label) if outcome_label else ""}</div>'
        )

    left, right = st.columns([5, 2], vertical_alignment="bottom")
    with left:
        st.markdown(
            f'<div class="gf-head-left">{brand}<div>'
            f'<div class="gf-title">{_esc(PRODUCT_NAME)}</div>'
            f'<div class="gf-sub">{_esc(SUBTITLE)}</div></div></div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f'<div class="gf-head-right">'
            f'<span class="gf-status gf-status--{status_class}">{_esc(status)}</span>'
            f'<div class="gf-updated">표시 데이터 {_esc(_format_stamp(payload.get("generated_at")))}</div>'
            f"{refresh_line}"
            "</div>",
            unsafe_allow_html=True,
        )


def _render_strip(payload: dict[str, Any]) -> None:
    stats = payload.get("stats", {})
    mix = stats.get("language_mix", {})
    cells = (
        ("분석 기간", f"최근 {payload.get('window_days', WINDOW_DAYS)}일", ""),
        ("수집 기사", f"{stats.get('article_count', 0)}건", f"국내 {mix.get('ko', 0)} · 해외 {mix.get('en', 0)}"),
        ("고유 출처", f"{stats.get('source_count', 0)}개", ""),
        ("Emerging Trends", f"{stats.get('trend_count', 0)}건", ""),
    )
    st.markdown(
        '<div class="gf-strip">'
        + "".join(
            f'<div><div class="gf-stat-label">{_esc(label)}</div>'
            f'<div class="gf-stat-value">{_esc(value)}'
            + (f" <em>{_esc(note)}</em>" if note else "")
            + "</div></div>"
            for label, value, note in cells
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_hero(trend: dict[str, Any], now: datetime) -> None:
    st.markdown(
        '<div class="gf-hero"><div>'
        f'<span class="gf-rank">{_esc(RANK_WORDS.get(trend.get("rank"), "01"))}</span>'
        f'<span class="gf-area">{_esc(watch_area_label(trend.get("watch_area")))}</span>'
        f'<div class="gf-hero-title">{_esc(trend.get("title_ko"))}</div>'
        f'<div class="gf-hero-summary">{_esc(trend.get("summary_ko"))}</div>'
        f'<div class="gf-why">{_esc(trend.get("why_it_matters_ko"))}</div>'
        f"{_tags_html(trend)}"
        "</div><div class=\"gf-hero-side\">"
        f"{_metrics_html(trend)}{_chart_html(trend.get('daily_counts', []))}"
        f"{_evidence_html(trend, 3, now)}"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _card_html(trend: dict[str, Any], now: datetime) -> str:
    return (
        '<div class="gf-card">'
        f'<span class="gf-rank">{_esc(RANK_WORDS.get(trend.get("rank"), "--"))}</span>'
        f'<span class="gf-area">{_esc(watch_area_label(trend.get("watch_area")))}</span>'
        f'<div class="gf-card-title">{_esc(trend.get("title_ko"))}</div>'
        f'<div class="gf-card-summary">{_esc(trend.get("summary_ko"))}</div>'
        '<div class="gf-card-foot">'
        f"{_metrics_html(trend)}{_chart_html(trend.get('daily_counts', []))}"
        f"{_tags_html(trend)}{_evidence_html(trend, 2, now)}"
        "</div></div>"
    )


def _render_detail(trends: list[dict[str, Any]], now: datetime) -> None:
    st.markdown('<div class="gf-sectionhead">Trend Detail</div>', unsafe_allow_html=True)
    labels = [
        f"{RANK_WORDS.get(trend.get('rank'), '--')}  {trend.get('title_ko', '')}"
        for trend in trends
    ]
    choice = st.radio(
        "트렌드 선택", labels, horizontal=True, label_visibility="collapsed"
    )
    selected = trends[labels.index(choice)] if choice in labels else trends[0]

    watch_next = [item for item in selected.get("watch_next", []) if str(item).strip()]
    if watch_next:
        st.markdown(
            '<div class="gf-evlabel">Watch Next</div>'
            + "".join(
                f'<div class="gf-note">· {_esc(item)}</div>' for item in watch_next[:2]
            ),
            unsafe_allow_html=True,
        )

    rows = []
    for article in selected.get("articles", []):
        title = _esc(article.get("title"))
        url = str(article.get("url") or "").strip()
        headline = f'<a href="{escape(url, quote=True)}" target="_blank">{title}</a>' if url else title
        synthetic = "" if url else '<span class="gf-synthetic">합성</span>'
        meta = " · ".join(
            part
            for part in (
                _esc(article.get("source")),
                _format_stamp(article.get("published_at")),
                "국내" if article.get("language") == "ko" else "해외",
                _esc(watch_area_label(article.get("watch_area"))),
            )
            if part
        )
        rows.append(
            f'<div class="gf-tl"><div class="gf-tl-title">{headline}{synthetic}</div>'
            f'<div class="gf-tl-meta">{meta}</div>'
            f'<div class="gf-tl-body">{_esc(article.get("summary"))}</div></div>'
        )
    st.markdown(
        '<div class="gf-evlabel">관련 기사 타임라인</div>' + "".join(rows),
        unsafe_allow_html=True,
    )


def _render_methodology(payload: dict[str, Any]) -> None:
    with st.expander("Methodology · 데이터 범위", expanded=False):
        st.markdown(
            f"""
<div class="gf-note">
· 최근 {payload.get('window_days', WINDOW_DAYS)}일 공개 RSS에서 제목·출처·발행시각·URL·짧은 설명만 수집합니다. 기사 본문은 크롤링하지 않습니다.<br>
· 동일 URL과 거의 같은 제목의 재배포 기사를 제거한 뒤 분석합니다.<br>
· Groq LLM은 기사를 3개 주제로 묶고 요약 문장을 작성합니다. 기사 수·출처 수·최근 집중도는 모두 코드에서 계산하며 LLM이 생성하지 않습니다.<br>
· 우선순위 = 0.5 × (기사 수 비중) + 0.3 × (출처 수 비중) + 0.2 × (최근 48시간 비중). 기사 수만으로 정렬하면 한 통신사의 재배포가 순위를 지배합니다.<br>
· <b>LIVE</b>는 24시간 이내 마지막 성공 결과, <b>CACHED</b>는 그보다 오래된 직전 성공 결과, <b>DEMO</b>는 저장소에 포함된 합성 예시입니다. 최근 갱신 시도의 성공·실패는 별도로 표시합니다.<br>
· 투자 추천이나 매수·매도 의견이 아니며, 미래 사건을 예측하지 않습니다.
</div>
""",
            unsafe_allow_html=True,
        )
        if payload.get("model"):
            st.caption(f"모델: {payload['model']} · 데이터: {payload.get('source_path', '')}")


def _refresh_now() -> None:
    """Collect and cluster. Failures are reported quietly, never as a red wall."""
    from scripts.refresh_trend_feed import refresh

    with st.spinner("최근 7일 기사를 수집하고 트렌드를 분석하는 중입니다…"):
        try:
            report = refresh()
        except Exception as exc:  # noqa: BLE001 - the demo must survive any failure
            st.session_state["gf_message"] = (
                f"수집에 실패했습니다. 기존 결과를 유지합니다. ({type(exc).__name__}: {exc})"
            )
            return

    summary = report.get("summary", "")
    if report.get("clustered"):
        st.session_state["gf_message"] = (
            f"{summary} · 트렌드 {report.get('trends', 0)}건 갱신"
        )
    else:
        # Partial success still shows the counts, then why the AI step stopped.
        error = str(report.get("error", ""))
        suffix = "" if "기존" in error else " 기존 결과를 유지합니다."
        st.session_state["gf_message"] = (
            f"{summary} · {error}{suffix}"
        ).replace("\n", " ")


def _ci_article_rows_html(articles: Sequence[Mapping[str, Any]], now: datetime) -> str:
    """Evidence lines for a brief. Reuses the trend evidence styling."""
    rows = []
    for article in articles:
        title = _esc(article.get("title"))
        url = str(article.get("url") or "").strip()
        headline = (
            f'<a href="{escape(url, quote=True)}" target="_blank">{title}</a>'
            if url
            else title
        )
        synthetic = "" if url else '<span class="gf-synthetic">합성</span>'
        meta = " · ".join(
            part
            for part in (
                _esc(article.get("source")),
                _relative(article.get("published_at"), now),
                "국내" if article.get("language") == "ko" else "해외",
            )
            if part
        )
        rows.append(
            f'<div class="gf-ev">{headline}{synthetic}'
            f'<div class="gf-ev-meta">{meta}</div></div>'
        )
    return "".join(rows)


def _ci_tags_html(values: Any) -> str:
    tags = [str(tag).strip() for tag in (values or []) if str(tag).strip()]
    if not tags:
        return ""
    return '<div class="gf-ci-tags">' + "".join(
        f'<span class="gf-ci-tag">{_esc(tag)}</span>' for tag in tags
    ) + "</div>"


def _brief_card_html(brief: Mapping[str, Any], now: datetime) -> str:
    """One Main Brief card. Evidence beyond the first two goes in an expander."""
    fields = (
        ("회사 관련성", brief.get("company_relevance_ko")),
        ("사업 영향", brief.get("business_impact_ko")),
    )
    grid = "".join(
        f'<div class="gf-brief-field"><div class="gf-brief-label">{_esc(label)}</div>'
        f'<div class="gf-brief-value">{_esc(value)}</div></div>'
        for label, value in fields
        if str(value or "").strip()
    )
    grid_html = f'<div class="gf-brief-grid">{grid}</div>' if grid else ""

    watch = [str(item).strip() for item in (brief.get("watch_next") or []) if str(item).strip()]
    watch_html = ""
    if watch:
        watch_html = (
            '<div class="gf-watch"><div class="gf-brief-label">WATCH NEXT</div>'
            + "".join(f'<div class="gf-watch-row">· {_esc(item)}</div>' for item in watch)
            + "</div>"
        )

    evidence = list(brief.get("evidence_articles") or [])
    evidence_html = ""
    if evidence:
        evidence_html = (
            '<div class="gf-ci-evidence"><div class="gf-brief-label">근거 기사</div>'
            f"{_ci_article_rows_html(evidence[:CI_EVIDENCE_PREVIEW], now)}</div>"
        )

    situation = str(brief.get("situation_ko") or "").strip()
    situation_html = (
        f'<div class="gf-brief-situation">{_esc(situation)}</div>' if situation else ""
    )
    return (
        '<div class="gf-brief-card"><div class="gf-brief-top">'
        f'<div class="gf-brief-title">{_esc(brief.get("title_ko"))}</div>'
        f'<span class="gf-proof">{_esc(brief.get("corroboration_label"))}</span>'
        "</div>"
        f"{situation_html}{grid_html}"
        f'{_ci_tags_html(brief.get("business_tags"))}'
        f"{watch_html}{evidence_html}</div>"
    )


def _monitor_item_html(item: Mapping[str, Any]) -> str:
    reason = str(item.get("reason_ko") or "").strip()
    reason_html = f'<div class="gf-monitor-reason">{_esc(reason)}</div>' if reason else ""
    evidence_count = len(item.get("evidence_articles") or [])
    proof = _esc(item.get("corroboration_label"))
    if evidence_count:
        proof += f" · 근거 {evidence_count}건"
    return (
        '<div class="gf-monitor"><div>'
        f'<div class="gf-monitor-title">{_esc(item.get("title_ko"))}</div>'
        f"{reason_html}"
        f'{_ci_tags_html(item.get("business_tags"))}</div>'
        f'<div class="gf-monitor-proof">{proof}</div></div>'
    )


def _render_company_tab(company: Mapping[str, Any], fallback_reason: str, now: datetime) -> None:
    st.markdown(
        '<div class="gf-ci-company">'
        f'<div class="gf-ci-company-name">{_esc(company.get("company_name"))}</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    if company.get("status") != "AVAILABLE":
        # Never invent prose. A company-specific cause is worth an alert; a
        # section-wide one is already shown above, so repeat only a short line.
        own_reason = str(company.get("reason") or "").strip()
        if own_reason and own_reason != fallback_reason:
            st.markdown(
                f'<div class="gf-ci-alert">{_esc(own_reason)}</div>',
                unsafe_allow_html=True,
            )
        elif fallback_reason:
            st.markdown(
                '<div class="gf-ci-intro">표시할 Brief가 없습니다. '
                '사유는 위 안내를 확인해 주세요.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="gf-ci-alert">표시할 Brief가 없습니다.</div>',
                unsafe_allow_html=True,
            )
        return

    summary = str(company.get("weekly_summary_ko") or "").strip()
    if summary:
        st.markdown(
            f'<div class="gf-ci-summary">{_esc(summary)}</div>', unsafe_allow_html=True
        )

    briefs = list(company.get("briefs") or [])
    if briefs:
        st.markdown('<div class="gf-ci-subhead">Main Brief</div>', unsafe_allow_html=True)
        for index, brief in enumerate(briefs):
            st.markdown(_brief_card_html(brief, now), unsafe_allow_html=True)
            extra = list(brief.get("evidence_articles") or [])[CI_EVIDENCE_PREVIEW:]
            if extra:
                with st.expander(f"근거 기사 {len(extra)}건 더 보기", expanded=False):
                    st.markdown(
                        f'<div class="gf-ci-evidence">{_ci_article_rows_html(extra, now)}</div>',
                        unsafe_allow_html=True,
                    )
    else:
        st.markdown(
            '<div class="gf-ci-alert">표시할 Main Brief가 없습니다.</div>',
            unsafe_allow_html=True,
        )

    monitoring = list(company.get("monitoring_items") or [])
    if monitoring:
        st.markdown(
            '<div class="gf-ci-subhead">Monitoring</div>', unsafe_allow_html=True
        )
        st.markdown(
            "".join(_monitor_item_html(item) for item in monitoring),
            unsafe_allow_html=True,
        )


def _render_company_intelligence(payload: Mapping[str, Any], now: datetime) -> None:
    intelligence = payload.get("company_intelligence")
    if not isinstance(intelligence, Mapping):
        return

    companies = list(intelligence.get("companies") or [])
    if not companies:
        return

    st.markdown(
        '<div class="gf-ci-head">'
        '<div class="gf-ci-kicker">Company Intelligence</div>'
        '<div class="gf-ci-title">계열사별 주간 브리핑</div>'
        '<div class="gf-ci-intro">같은 트렌드를 회사별 사업 관점에서 다시 읽습니다. '
        '근거는 위 트렌드에 연결된 실제 기사입니다.</div></div>',
        unsafe_allow_html=True,
    )

    reason = str(intelligence.get("reason") or "").strip()
    if intelligence.get("status") != "GENERATED" and reason:
        st.markdown(f'<div class="gf-ci-alert">{_esc(reason)}</div>', unsafe_allow_html=True)

    tabs = st.tabs([str(company.get("company_name") or "") for company in companies])
    for tab, company in zip(tabs, companies):
        with tab:
            _render_company_tab(company, reason, now)


def main() -> None:
    now = datetime.now(timezone.utc)
    payload = load_trend_feed()

    _render_header(payload)
    action_col, message_col = st.columns([2, 6], vertical_alignment="center")
    with action_col:
        if st.button("최신 데이터 불러오기", use_container_width=True):
            _refresh_now()
            st.rerun()
    with message_col:
        message = st.session_state.get("gf_message")
        if message:
            st.caption(message)
        elif payload.get("refresh", {}).get("outcome") in {"failed", "partial"}:
            refresh = payload["refresh"]
            st.caption(
                f"최근 갱신 시도 {_format_stamp(refresh.get('attempted_at'))}: "
                f"{refresh.get('message', '')}"
            )
        elif payload.get("status") == "DEMO" and payload.get("notice"):
            st.caption(payload["notice"])

    _render_strip(payload)

    trends = payload.get("trends", [])
    if not trends:
        st.caption("표시할 트렌드가 없습니다. 최신 데이터를 불러오거나 fallback 파일을 확인하세요.")
        _render_methodology(payload)
        return

    _render_hero(trends[0], now)
    if len(trends) > 1:
        st.markdown(
            f'<div class="gf-grid">'
            + "".join(_card_html(trend, now) for trend in trends[1:3])
            + "</div>",
            unsafe_allow_html=True,
        )
    _render_detail(trends, now)
    _render_company_intelligence(payload, now)
    _render_methodology(payload)


if __name__ == "__main__":
    main()
