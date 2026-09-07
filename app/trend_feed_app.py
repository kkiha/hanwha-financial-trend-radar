"""Hanwha executive briefing UI, using the existing RSS/LLM pipeline.

Run: streamlit run app/trend_feed_app.py
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
import sys

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.briefing_view import prepare_view, refresh_feedback
from app.trend_feed_data import load_trend_feed

FRONTEND = Path(__file__).with_name("frontend")

st.set_page_config(
    page_title="Hanwha Global Finance Radar", page_icon="📡", layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data
def _assets(asset_version: tuple[int, ...]):
    font = base64.b64encode((FRONTEND / "PretendardVariable.woff2").read_bytes()).decode("ascii")
    license_text = (FRONTEND / "Pretendard-LICENSE.txt").read_text(encoding="utf-8")
    font_css = (
        "/* " + license_text.replace("*/", "* /") + " */"
        "@font-face{font-family:BriefingPretendard;src:url(data:font/woff2;base64,"
        + font + ") format('woff2');font-weight:100 900;font-style:normal;font-display:swap}"
    )
    sources = {
        "html": (FRONTEND / "briefing.html").read_text(encoding="utf-8"),
        "css": (FRONTEND / "briefing.css").read_text(encoding="utf-8"),
        "js": (FRONTEND / "briefing.js").read_text(encoding="utf-8"),
    }
    report_css = font_css + (FRONTEND / "report.css").read_text(encoding="utf-8")
    return sources, font_css, report_css


def _refresh_now() -> None:
    from scripts.refresh_trend_feed import refresh

    try:
        report = refresh()
    except Exception as exc:  # Keep prior results if collection or analysis raises.
        st.session_state["gf_feedback"] = {
            "outcome": "failed",
            "message": f"갱신에 실패했습니다. 기존 결과를 유지합니다. ({type(exc).__name__})",
        }
    else:
        st.session_state["gf_feedback"] = refresh_feedback(report)
    # Distinguish repeated identical outcomes so the client can finish each request.
    st.session_state["gf_feedback"]["completed_at"] = datetime.now(timezone.utc).isoformat()


def main() -> None:
    sources, font_css, report_css = _assets(tuple(
        (FRONTEND / name).stat().st_mtime_ns
        for name in ("briefing.html", "briefing.css", "briefing.js", "report.css", "PretendardVariable.woff2")
    ))
    chrome_css = Path(__file__).with_name("trend_feed.css").read_text(encoding="utf-8")
    st.markdown("<style>" + font_css + chrome_css + "</style>", unsafe_allow_html=True)
    payload = prepare_view(load_trend_feed())
    payload["feedback"] = st.session_state.get("gf_feedback")
    payload["report_css"] = report_css
    logo_path = PROJECT_ROOT / "assets" / "hanwha_logo.png"
    payload["logo"] = (
        "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode("ascii")
        if logo_path.exists() else ""
    )
    # Registration belongs to the active runtime, never a global resource cache.
    renderer = st.components.v2.component("executive_briefing", **sources)
    renderer(
        key="finance-briefing", data=payload,
        on_refresh_change=_refresh_now,
    )


if __name__ == "__main__":
    main()
