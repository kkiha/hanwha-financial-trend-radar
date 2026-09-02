from __future__ import annotations

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
    signal_label,
)


st.set_page_config(
    page_title="Hanwha Financial Trend Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2.2rem; padding-bottom: 3rem;}
    [data-testid="stMetric"] {
        background: rgba(245, 126, 32, 0.055);
        border: 1px solid rgba(245, 126, 32, 0.22);
        border-radius: 0.7rem;
        padding: 0.7rem 0.9rem;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: rgba(128, 128, 128, 0.24);
        border-radius: 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _render_header() -> None:
    st.title("Hanwha Financial Trend Radar")
    st.caption("Global financial signals translated into company-specific perspectives")
    st.warning(
        "DEMO · SNAPSHOT DATA  |  시연용 합성 데이터이며 실시간 시장 데이터가 아닙니다.",
        icon="⚠️",
    )


def _render_trending(signal: dict[str, Any]) -> None:
    st.subheader("What's Trending?")
    st.markdown(f"### {_display(signal.get('headline'), 'Signal 정보 없음')}")
    metric_col, change_col, z_col, direction_col = st.columns(4)
    metric_col.metric("Metric", _display(signal.get("metric")))
    change_col.metric(
        "Weekly Change",
        _weekly_change(signal.get("weekly_change"), signal.get("weekly_change_unit")),
    )
    z_col.metric("Z-score", _number(signal.get("z_score"), 1))
    direction_col.metric("Direction", _direction(signal.get("direction")))


def _render_evidence(evidence: list[dict[str, Any]]) -> None:
    st.subheader("Why Did It Move?")
    st.info("아래 근거는 실제 기사나 실시간 피드가 아닌 합성 Snapshot Evidence입니다.", icon="ℹ️")
    if not evidence:
        st.warning("표시할 Evidence가 없습니다.")
        return

    for index, item in enumerate(evidence[:5], start=1):
        with st.container(border=True):
            st.markdown(f"**{index}. {_display(item.get('title'), '제목 없음')}**")
            source = _display(item.get("source"), "출처 없음")
            date = _display(item.get("date") or item.get("published_at"), "")
            st.caption(" · ".join(part for part in (source, date) if part))
            st.write(_display(item.get("excerpt"), "요약 정보가 없습니다."))
            url = str(item.get("url") or "").strip()
            if url:
                st.markdown(f"[Snapshot Evidence URL]({url})")


def _render_companies(companies: dict[str, dict[str, Any]]) -> None:
    st.subheader("Company Impact")
    columns = st.columns(3)
    for column, company in zip(columns, COMPANY_ORDER):
        impact = companies.get(company, {})
        with column:
            with st.container(border=True):
                st.markdown(f"### {company}")
                relevance_col, direction_col = st.columns(2)
                relevance_col.caption("RELEVANCE")
                relevance_col.markdown(f"**{_display(impact.get('relevance'), '정보 없음')}**")
                direction_col.caption("DIRECTION")
                direction_col.markdown(f"**{_display(impact.get('direction'), '정보 없음')}**")
                st.markdown("**Transmission Paths**")
                paths = impact.get("transmission_paths")
                if isinstance(paths, list) and paths:
                    for path in paths:
                        st.markdown(f"- {_display(path)}")
                else:
                    st.caption("정보 없음")
                st.markdown("**Insight**")
                st.write(_display(impact.get("insight"), "분석 결과가 없습니다."))


def main() -> None:
    _render_header()
    signal_ids = available_signal_ids()
    if not signal_ids:
        st.error("등록된 Demo Signal이 없습니다.")
        return

    selected_signal_id = st.selectbox(
        "Demo Signal",
        signal_ids,
        format_func=signal_label,
    )

    payload = load_dashboard_payload(selected_signal_id)
    for error in payload.get("errors", []):
        st.error(error)
    _render_trending(payload.get("signal", {}))
    st.divider()
    _render_evidence(payload.get("evidence", []))
    st.divider()
    _render_companies(payload.get("companies", {}))


if __name__ == "__main__":
    main()
