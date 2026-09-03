from __future__ import annotations

import base64
from html import escape
import json
from numbers import Real
from pathlib import Path
import sys
from typing import Any

import streamlit as st

# Streamlit executes this file with app/ at sys.path[0]. Add the repository root
# so the same package import works for CLI, AppTest, and IDE launch modes.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dashboard_data import (
    COMPANY_ORDER,
    available_signal_ids,
    load_dashboard_payload,
    signal_short_label,
)


PRODUCT_NAME = "Financial Trend Radar"
SUBTITLE = "금융시장 Signal과 관련 Evidence를 연결하고 업무 관점별 확인 항목을 제시합니다"
# The card is a business lens, not a verdict about a company's P&L.
LENS_LABELS = {
    "한화생명": "보험 관점",
    "한화투자증권": "증권 관점",
    "한화자산운용": "자산운용 관점",
}
ASSET_DIR = PROJECT_ROOT / "assets"
LOGO_CANDIDATES = (
    "hanwha_logo.svg",
    "hanwha_logo.png",
    "hanwha_logo.jpg",
    "hanwha_logo.jpeg",
    "hanwha_logo.webp",
)
LOGO_MIME = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

st.set_page_config(
    page_title="Hanwha Financial Trend Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _logo_path() -> Path | None:
    """Locate the official logo asset. Absent is a supported state, not an error."""
    for name in LOGO_CANDIDATES:
        candidate = ASSET_DIR / name
        if candidate.is_file():
            return candidate
    return None


def _logo_data_uri() -> str:
    path = _logo_path()
    if path is None:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    mime = LOGO_MIME.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


# st.logo() is deliberately not used: it draws a second, differently sized logo
# in the Streamlit header bar, which we hide. The brand bar below owns the mark.


# Brand system.
#   --hw-orange      marks only (fills, rules, chips). Never text: 2.66:1 on white.
#   --hw-orange-ink  the only orange allowed on type: 4.60:1 on white (WCAG AA).
# Orange stays roughly 10-15% of the surface: active segment, brand rule, card
# accent, summary rule, hero rule, direction badge, section rules.
st.markdown(
    """
    <style>
    :root {
        --hw-orange: #F57E20;
        --hw-orange-ink: #B85C00;
        --hw-orange-tint: rgba(245, 126, 32, 0.10);
        --hw-ink: #23272B;
        --hw-ink-2: #3A4046;
        --hw-ink-3: #6B7178;
        --hw-line: #E6E2DE;
        --hw-surface: #FFFFFF;
        --hw-surface-2: #F7F5F3;
        --hw-font: "Pretendard", "Pretendard Variable", -apple-system,
            "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "Segoe UI",
            system-ui, sans-serif;
    }
    /* Scoped to text elements only. A blanket attribute selector over Streamlit's
       emotion class names would also hit its Material Symbols icon spans, which
       then render their ligature name ("arrow_down") as literal text. */
    html, body, .stApp,
    .stApp p, .stApp span, .stApp div, .stApp li, .stApp label,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp button {
        font-family: var(--hw-font);
    }
    [data-testid="stIconMaterial"], .material-symbols-rounded {
        font-family: "Material Symbols Rounded" !important;
    }
    /* The Streamlit header bar is hidden: it floats over the page and would clip
       the brand bar. Hiding it also removes its duplicate st.logo() mark. */
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
        display: none !important;
    }
    .stApp {background: var(--hw-surface);}
    .block-container {max-width: 1200px; padding-top: 1.6rem; padding-bottom: 3rem;}

    /* Brand bar */
    .hw-brandbar {
        display: flex; align-items: flex-end; justify-content: space-between;
        gap: 1rem; padding-bottom: 0.75rem; margin-bottom: 1.05rem;
        border-bottom: 2px solid var(--hw-orange);
    }
    .hw-brand-left {display: flex; align-items: center; gap: 0.85rem;}
    .hw-logo {height: 30px; width: auto; display: block;}
    .hw-brand-div {width: 1px; height: 30px; background: var(--hw-line);}
    .hw-product {
        font-size: 1.22rem; font-weight: 700; color: var(--hw-ink);
        letter-spacing: -0.012em; line-height: 1.25;
    }
    .hw-mark-word {color: var(--hw-orange-ink);}
    .hw-subtitle {font-size: 0.82rem; color: var(--hw-ink-3); margin-top: 0.15rem;}
    .hw-tagrow {display: flex; gap: 0.35rem; padding-bottom: 0.2rem;}
    .hw-tag {
        border: 1px solid rgba(245, 126, 32, 0.5); color: var(--hw-orange-ink);
        border-radius: 999px; padding: 0.1rem 0.5rem; font-size: 0.63rem;
        font-weight: 700; letter-spacing: 0.07em; white-space: nowrap;
    }

    /* Section heading. The accent rule lives on the wrapper so the note can sit
       on its own line and still align with the title. */
    .hw-sectionhead {
        border-left: 3px solid var(--hw-orange);
        padding-left: 0.6rem; margin: 1.6rem 0 0.65rem;
    }
    h2.hw-section {
        font-size: 1rem; font-weight: 700; color: var(--hw-ink);
        margin: 0; padding: 0; line-height: 1.35;
    }
    .hw-section-note {
        font-size: 0.74rem; font-weight: 400; color: var(--hw-ink-3);
        margin-top: 0.15rem; line-height: 1.5;
    }

    /* Provenance markers: who produced this block. Deliberately neutral gray —
       orange is the brand accent budget and must not be spent here. */
    .hw-prov {
        display: inline-block; font-size: 0.58rem; font-weight: 700;
        letter-spacing: 0.05em; padding: 0.06rem 0.32rem; border-radius: 0.25rem;
        white-space: nowrap; vertical-align: middle; margin-left: 0.3rem;
        border: 1px solid var(--hw-line); background: #FAFAF9; color: var(--hw-ink-3);
    }
    .hw-prov--ai {border-style: dashed; border-color: #B4BAC1; color: #4A5057;}
    .hw-prov--profile {background: #EDEBE8; color: #4A5057;}
    .hw-legend {
        display: flex; flex-wrap: wrap; align-items: center;
        font-size: 0.74rem; color: var(--hw-ink-3); margin: 0.6rem 0 0.2rem;
    }
    .hw-legend-item {display: inline-flex; align-items: center; margin-right: 1.1rem;}
    .hw-legend-item .hw-prov {margin-left: 0; margin-right: 0.32rem;}

    /* What's Trending — exactly one hero figure */
    .hw-headline-row {
        display: flex; align-items: center; gap: 0.55rem;
        flex-wrap: wrap; margin-bottom: 0.7rem;
    }
    .hw-headline {
        font-size: 1.5rem; font-weight: 700; color: var(--hw-ink);
        letter-spacing: -0.015em; line-height: 1.3;
    }
    .hw-eyebrow {
        font-size: 0.72rem; font-weight: 600; color: var(--hw-ink-3);
        background: var(--hw-surface-2); border: 1px solid var(--hw-line);
        border-radius: 0.3rem; padding: 0.16rem 0.45rem; white-space: nowrap;
    }
    .hw-tilegrid {display: grid; grid-template-columns: 1.3fr 1fr 1fr; gap: 0.6rem;}
    .hw-tile {
        background: var(--hw-surface-2); border: 1px solid var(--hw-line);
        border-radius: 0.55rem; padding: 0.6rem 0.85rem;
    }
    .hw-tile--hero {background: var(--hw-surface); border-left: 3px solid var(--hw-orange);}
    .hw-tile-label {
        font-size: 0.68rem; font-weight: 600; letter-spacing: 0.07em;
        text-transform: uppercase; color: var(--hw-ink-3);
    }
    .hw-tile-value {
        font-size: 1.15rem; font-weight: 600; color: var(--hw-ink);
        margin-top: 0.15rem; line-height: 1.3;
    }
    .hw-tile--hero .hw-tile-value {font-size: 2rem; font-weight: 700; letter-spacing: -0.02em;}

    /* AI Trend Summary */
    .hw-summary {
        background: var(--hw-surface-2); border-left: 4px solid var(--hw-orange);
        border-radius: 0.35rem; padding: 0.8rem 1rem;
        font-size: 0.92rem; line-height: 1.65; color: var(--hw-ink-2);
    }

    /* Business Lens */
    .hw-cardgrid {display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem;}
    .hw-card {
        background: var(--hw-surface); border: 1px solid var(--hw-line);
        border-top: 3px solid var(--hw-orange); border-radius: 0.6rem;
        padding: 0.85rem 0.95rem 1rem; display: flex; flex-direction: column;
    }
    .hw-lens {
        display: inline-block; font-size: 0.66rem; font-weight: 700;
        letter-spacing: 0.05em; border-radius: 0.28rem; padding: 0.1rem 0.42rem;
        background: var(--hw-orange-tint); color: var(--hw-orange-ink);
        border: 1px solid rgba(245, 126, 32, 0.35); margin-bottom: 0.35rem;
    }
    .hw-company {font-size: 1.02rem; font-weight: 700; color: var(--hw-ink);}
    .hw-impact {
        font-size: 0.94rem; font-weight: 600; line-height: 1.5;
        color: var(--hw-ink); margin: 0.5rem 0 0.1rem;
    }
    .hw-rule {height: 1px; background: var(--hw-line); margin: 0.65rem 0 0.2rem;}
    .hw-flabel {
        font-size: 0.66rem; font-weight: 700; letter-spacing: 0.06em;
        text-transform: uppercase; color: var(--hw-ink-3); margin-top: 0.6rem;
    }
    .hw-list {
        margin: 0.2rem 0 0; padding-left: 0.95rem;
        font-size: 0.84rem; line-height: 1.6; color: var(--hw-ink-2);
    }
    .hw-list li {margin-bottom: 0.1rem;}
    .hw-empty {font-size: 0.8rem; color: var(--hw-ink-3); font-style: italic; margin-top: 0.15rem;}

    /* Short noun phrases read better as chips than as bullet lists. */
    .hw-chiprow {margin-top: 0.22rem;}
    .hw-chip {
        display: inline-block; font-size: 0.75rem; color: var(--hw-ink-2);
        background: var(--hw-surface-2); border: 1px solid var(--hw-line);
        border-radius: 0.28rem; padding: 0.11rem 0.42rem; margin: 0 0.25rem 0.28rem 0;
    }

    /* Pinned to the card bottom so the three insights line up across cards. */
    .hw-insight-block {margin-top: auto; padding-top: 0.55rem;}
    .hw-insight-block .hw-flabel {margin-top: 0;}
    .hw-insight {font-size: 0.85rem; line-height: 1.65; color: var(--hw-ink-2); margin-top: 0.2rem;}

    /* What to Watch */
    .hw-watch {
        background: var(--hw-surface-2); border: 1px solid var(--hw-line);
        border-radius: 0.5rem; padding: 0.7rem 0.85rem;
    }
    .hw-watch-name {font-size: 0.86rem; font-weight: 700; color: var(--hw-ink);}

    /* Why Did It Move? */
    .hw-causes {
        margin: 0; padding-left: 1.05rem;
        font-size: 0.9rem; line-height: 1.75; color: var(--hw-ink-2);
    }

    /* AI scope disclosure */
    .hw-scope {width: 100%; border-collapse: collapse; font-size: 0.83rem; color: var(--hw-ink-2);}
    .hw-scope td {padding: 0.35rem 0.5rem 0.35rem 0; vertical-align: top; line-height: 1.6;
        border-bottom: 1px solid var(--hw-line);}
    .hw-scope tr:last-child td {border-bottom: 0;}
    .hw-scope-k {
        width: 9.5rem; white-space: nowrap; font-weight: 700;
        font-size: 0.76rem; color: var(--hw-ink-3);
    }
    .hw-scope code {font-size: 0.78rem; background: var(--hw-surface-2); padding: 0.05rem 0.25rem;
        border-radius: 0.2rem;}

    /* Evidence */
    .hw-ev {border-top: 1px solid var(--hw-line); padding-top: 0.6rem; margin-top: 0.6rem;}
    .hw-ev:first-child {border-top: 0; padding-top: 0; margin-top: 0;}
    .hw-ev-title {font-size: 0.9rem; font-weight: 700; color: var(--hw-ink);}
    .hw-ev-meta {font-size: 0.72rem; color: var(--hw-ink-3); margin: 0.12rem 0 0.28rem;}
    .hw-ev-body {font-size: 0.84rem; line-height: 1.6; color: var(--hw-ink-2);}

    @media (max-width: 980px) {
        .hw-cardgrid {grid-template-columns: 1fr;}
        .hw-tilegrid {grid-template-columns: 1fr;}
    }

    /* Streamlit chrome — decoration only. If a selector misses on a Streamlit
       upgrade the layout still holds, since it is built from our own classes. */
    [data-testid="stAlertContainer"] {
        background: var(--hw-surface-2); border: 1px solid var(--hw-line);
        border-left: 3px solid var(--hw-orange); border-radius: 0.45rem;
        color: var(--hw-ink-2); font-size: 0.83rem;
    }
    [data-testid="stExpander"] details {
        border: 1px solid var(--hw-line); border-radius: 0.5rem; background: var(--hw-surface);
    }
    [data-testid="stExpander"] summary {font-size: 0.85rem; font-weight: 600; color: var(--hw-ink-2);}
    [data-testid="stElementToolbar"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _esc(value: Any) -> str:
    """Escape for an HTML text node. quote=False keeps apostrophes readable."""
    return escape(str(value), quote=False)


def _display(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _number(value: Any, digits: int = 2) -> str:
    if isinstance(value, bool) or not isinstance(value, Real):
        return "—"
    return f"{float(value):.{digits}f}"


def _weekly_change(value: Any, unit: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, Real):
        return "—"
    number = float(value)
    if unit == "percentage_point":
        return f"{number * 100:+.0f} bp"
    if unit == "index_point":
        return f"{number:+.1f} pts"
    if unit == "krw_per_usd":
        return f"{number:+.1f} KRW"
    return f"{number:+.2f} {_display(unit, '')}".strip()


def _direction(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    arrows = {"UP": "↑", "DOWN": "↓", "FLAT": "→"}
    return f"{arrows.get(normalized, '')} {normalized}".strip() or "—"


def _items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_display(item, "") for item in value) if text]


def _list_html(values: Any, empty_text: str = "해당 없음") -> str:
    items = _items(values)
    if not items:
        return f'<div class="hw-empty">{_esc(empty_text)}</div>'
    entries = "".join(f"<li>{_esc(item)}</li>" for item in items)
    return f'<ul class="hw-list">{entries}</ul>'


def _chips_html(label: str, values: Any, empty_text: str = "정보 없음") -> str:
    items = _items(values)
    if not items:
        body = f'<div class="hw-empty">{_esc(empty_text)}</div>'
    else:
        chips = "".join(f'<span class="hw-chip">{_esc(item)}</span>' for item in items)
        body = f'<div class="hw-chiprow">{chips}</div>'
    return f'<div class="hw-flabel">{_esc(label)}</div>{body}'


def _llm_model_name() -> str:
    """Model named in the demo config. Absent or unreadable config is fine."""
    try:
        config = json.loads((PROJECT_ROOT / "configs" / "trend_demo.yaml").read_text(encoding="utf-8"))
        return str(config.get("llm", {}).get("model", "") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _prov(kind: str, label: str) -> str:
    """A provenance marker: which producer this block came from."""
    return f'<span class="hw-prov hw-prov--{kind}">{_esc(label)}</span>'


def _section(title: str, note: str = "", tags: str = "") -> None:
    note_html = f'<div class="hw-section-note">{_esc(note)}</div>' if note else ""
    st.markdown(
        '<div class="hw-sectionhead">'
        f'<h2 class="hw-section">{_esc(title)}{tags}</h2>'
        f"{note_html}</div>",
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    logo_uri = _logo_data_uri()
    if logo_uri:
        brand = (
            f'<img class="hw-logo" src="{logo_uri}" alt="Hanwha" />'
            '<div class="hw-brand-div"></div>'
        )
        product = _esc(PRODUCT_NAME)
    else:
        brand = ""
        product = f'<span class="hw-mark-word">Hanwha</span> {_esc(PRODUCT_NAME)}'
    st.markdown(
        '<div class="hw-brandbar">'
        f'<div class="hw-brand-left">{brand}'
        f'<div><div class="hw-product">{product}</div>'
        f'<div class="hw-subtitle">{_esc(SUBTITLE)}</div></div></div>'
        '<div class="hw-tagrow">'
        '<span class="hw-tag">PROTOTYPE</span>'
        '<span class="hw-tag">SNAPSHOT MODE</span>'
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.warning(
        "SNAPSHOT MODE  |  현재 Prototype은 분석 Workflow와 UX 검증을 위해 "
        "Representative Snapshot Dataset을 사용합니다.",
        icon="ℹ️",
    )
    legend = (
        ("ai", "AI 생성", "Brief 문장과 관련 요인"),
        ("profile", "Profile 기준", "Check Points와 지표"),
        ("data", "Snapshot", "시그널 수치"),
        ("search", "검색 선별", "근거 5건"),
    )
    items = "".join(
        f'<span class="hw-legend-item">{_prov(kind, label)}{_esc(description)}</span>'
        for kind, label, description in legend
    )
    st.markdown(f'<div class="hw-legend">{items}</div>', unsafe_allow_html=True)


def _render_signal_selector(signal_ids: list[str]) -> str:
    # segmented_control is de-selectable and can return None; fall back to the
    # first signal so the page never renders empty.
    selected = st.segmented_control(
        "Demo Signal",
        signal_ids,
        default=signal_ids[0],
        format_func=signal_short_label,
        label_visibility="collapsed",
    )
    return selected or signal_ids[0]


def _render_trending(signal: dict[str, Any]) -> None:
    _section("What's Trending?", tags=_prov("data", "Snapshot"))
    tiles = (
        ("Weekly Change", _weekly_change(signal.get("weekly_change"), signal.get("weekly_change_unit")), True),
        ("Z-score", _number(signal.get("z_score"), 1), False),
        ("Direction", _direction(signal.get("direction")), False),
    )
    tile_html = "".join(
        f'<div class="hw-tile{" hw-tile--hero" if hero else ""}">'
        f'<div class="hw-tile-label">{_esc(label)}</div>'
        f'<div class="hw-tile-value">{_esc(value)}</div></div>'
        for label, value, hero in tiles
    )
    st.markdown(
        '<div class="hw-headline-row">'
        f'<span class="hw-headline">{_esc(_display(signal.get("headline"), "Signal 정보 없음"))}</span>'
        f'<span class="hw-eyebrow">{_esc(_display(signal.get("metric")))}</span>'
        "</div>"
        f'<div class="hw-tilegrid">{tile_html}</div>',
        unsafe_allow_html=True,
    )


def _render_trend_summary(trend_summary: str) -> None:
    _section("AI Brief", tags=_prov("ai", "AI 생성"))
    text = _esc(_display(trend_summary, "요약 정보가 없습니다."))
    st.markdown(f'<div class="hw-summary">{text}</div>', unsafe_allow_html=True)


def _lens_card_html(company: str, impact: dict[str, Any]) -> str:
    """A business lens: what to examine under this signal, not a verdict.

    relevance/direction and the positive/negative factor lists stay in the
    profile data but are deliberately not rendered — showing them reads as an
    automated impact judgement, which this prototype does not make.
    """
    summary = _display(impact.get("impact_summary"), "")
    summary_html = (
        f'<div class="hw-impact">{_esc(summary)}{_prov("ai", "AI")}</div>' if summary else ""
    )
    return (
        '<div class="hw-card">'
        f'<div class="hw-lens">{_esc(LENS_LABELS.get(company, "업무 관점"))}</div>'
        f'<div class="hw-company">{_esc(company)}</div>'
        f"{summary_html}"
        '<div class="hw-rule"></div>'
        f'{_chips_html("Check Points", impact.get("transmission_paths"))}'
        f'{_chips_html("Key Metrics to Watch", impact.get("key_metrics"))}'
        '<div class="hw-insight-block"><div class="hw-rule"></div>'
        f'<div class="hw-flabel">AI Brief{_prov("ai", "AI")}</div>'
        f'<div class="hw-insight">{_esc(_display(impact.get("insight"), "요약 정보가 없습니다."))}</div>'
        "</div></div>"
    )


def _render_business_lens(companies: dict[str, dict[str, Any]]) -> None:
    _section(
        "Business Lens",
        "같은 Signal에서 업무 관점별로 추가 확인할 항목입니다. "
        "Check Points와 지표는 Company Profile에서 읽고, Brief 문장만 AI가 작성합니다.",
        _prov("profile", "Profile 기준") + _prov("ai", "AI 생성"),
    )
    cards = "".join(
        _lens_card_html(company, companies.get(company, {})) for company in COMPANY_ORDER
    )
    st.markdown(f'<div class="hw-cardgrid">{cards}</div>', unsafe_allow_html=True)


def _render_watchlist(companies: dict[str, dict[str, Any]]) -> None:
    _section("Key Watchpoints", tags=_prov("profile", "Profile 기준"))
    blocks = []
    for company in COMPANY_ORDER:
        impact = companies.get(company, {})
        watchpoints = _items(impact.get("watchpoints")) or _items(impact.get("key_metrics"))
        blocks.append(
            '<div class="hw-watch">'
            f'<div class="hw-watch-name">{_esc(company)}</div>'
            f'{_list_html(watchpoints, "정보 없음")}'
            "</div>"
        )
    st.markdown(f'<div class="hw-cardgrid">{"".join(blocks)}</div>', unsafe_allow_html=True)


def _render_causes(causes: list[str]) -> None:
    # Not "Why Did It Move?" — the prototype does not establish causation.
    _section(
        "주요 관련 요인",
        "현재 Signal과 함께 확인할 주요 관련 요인입니다. 원인을 확정한 것은 아닙니다.",
        _prov("ai", "AI 생성"),
    )
    items = _items(causes)[:3]
    if not items:
        st.markdown('<div class="hw-empty">원인 정보가 없습니다.</div>', unsafe_allow_html=True)
        return
    entries = "".join(f"<li>{_esc(item)}</li>" for item in items)
    st.markdown(f'<ul class="hw-causes">{entries}</ul>', unsafe_allow_html=True)


def _render_evidence(evidence: list[dict[str, Any]]) -> None:
    _section(
        "Evidence",
        "LLM이 아니라 BM25 + RRF 검색으로 Snapshot corpus에서 선별한 근거입니다.",
        _prov("search", "검색 선별"),
    )
    with st.expander(f"관련 Evidence {len(evidence)}건 보기", expanded=False):
        st.info("Representative Snapshot Dataset에서 선별한 문서입니다.", icon="ℹ️")
        if not evidence:
            st.warning("표시할 Evidence가 없습니다.")
            return
        blocks = []
        for index, item in enumerate(evidence[:5], start=1):
            meta = " · ".join(
                part
                for part in (
                    _display(item.get("source"), ""),
                    _display(item.get("date") or item.get("published_at"), ""),
                    _display(item.get("document_id"), ""),
                )
                if part
            )
            blocks.append(
                '<div class="hw-ev">'
                f'<div class="hw-ev-title">{index}. {_esc(_display(item.get("title"), "제목 없음"))}</div>'
                f'<div class="hw-ev-meta">{_esc(meta)}</div>'
                f'<div class="hw-ev-body">{_esc(_display(item.get("excerpt"), "요약 정보가 없습니다."))}</div>'
                "</div>"
            )
        st.markdown("".join(blocks), unsafe_allow_html=True)


def _render_ai_scope(metadata: dict[str, Any]) -> None:
    analysis_mode = _display(metadata.get("analysis_mode"), "알 수 없음")
    mode_note = {
        "cached_llm_output": "사전에 생성하고 검증한 출력을 사용합니다. 화면을 열 때 실시간으로 생성하지 않습니다.",
        "live_llm": "화면 요청 시점에 LLM을 호출해 생성합니다.",
    }.get(analysis_mode, "")
    model = _llm_model_name()
    model_row = (
        f'<tr><td class="hw-scope-k">모델</td><td>{_esc(model)}</td></tr>' if model else ""
    )
    with st.expander("이 화면의 AI · Snapshot 범위", expanded=False):
        st.markdown(
            '<table class="hw-scope">'
            f'<tr><td class="hw-scope-k">분석 모드</td><td><code>{_esc(analysis_mode)}</code> — {_esc(mode_note)}</td></tr>'
            f"{model_row}"
            '<tr><td class="hw-scope-k">AI가 생성하는 것</td><td>'
            "AI Brief, 주요 관련 요인 3건, Business Lens 카드의 요약 문장과 Brief</td></tr>"
            '<tr><td class="hw-scope-k">AI가 생성하지 않는 것</td><td>'
            "Check Points, 주요 지표, Key Watchpoints — 모두 Company Profile에서 직접 읽습니다.</td></tr>"
            '<tr><td class="hw-scope-k">판정하지 않는 것</td><td>'
            "이 도구는 회사별 손익 영향, 긍정·부정 방향, 민감도를 확정적으로 판정하지 않습니다. "
            "추가로 확인할 항목을 제시하는 데까지가 범위입니다.</td></tr>"
            '<tr><td class="hw-scope-k">근거(Evidence)</td><td>'
            "LLM 생성물이 아니라 Snapshot corpus 26건에서 BM25 + RRF로 검색해 선별합니다.</td></tr>"
            '<tr><td class="hw-scope-k">시그널 수치</td><td>'
            "Representative Snapshot Dataset의 고정 값입니다. 실시간 시장 데이터가 아닙니다.</td></tr>"
            '<tr><td class="hw-scope-k">검증</td><td>'
            "JSON schema 검증과 Profile grounding을 통과한 출력만 사용합니다. "
            "Profile에 없는 Check Point가 나오면 실패로 처리합니다.</td></tr>"
            '<tr><td class="hw-scope-k">하지 않는 것</td><td>'
            "투자 추천, 매수·매도 의견, 목표가를 생성하지 않습니다 "
            "(<code>investment_advice: false</code>).</td></tr>"
            "</table>",
            unsafe_allow_html=True,
        )


def main() -> None:
    _render_header()
    signal_ids = available_signal_ids()
    if not signal_ids:
        st.error("등록된 Demo Signal이 없습니다.")
        return

    selected_signal_id = _render_signal_selector(signal_ids)

    payload = load_dashboard_payload(selected_signal_id)
    for error in payload.get("errors", []):
        st.error(error)
    _render_trending(payload.get("signal", {}))
    _render_trend_summary(payload.get("trend_summary", ""))
    _render_business_lens(payload.get("companies", {}))
    _render_watchlist(payload.get("companies", {}))
    _render_causes(payload.get("causes", []))
    _render_evidence(payload.get("evidence", []))
    _render_ai_scope(payload.get("metadata", {}))


if __name__ == "__main__":
    main()
