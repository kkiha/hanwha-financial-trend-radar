"""UI-only view model for the executive briefing component."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.trend_feed_data import watch_area_label


def safe_url(value: Any) -> str:
    """Allow only navigable HTTP(S) evidence, including in exported reports."""
    value = str(value or "").strip()
    try:
        parts = urlsplit(value)
        return value if parts.scheme.lower() in {"http", "https"} and parts.hostname else ""
    except ValueError:
        return ""


def prepare_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy display data only; never mutate loader output or persisted artifacts."""
    view = deepcopy({key: payload.get(key) for key in (
        "status", "generated_at", "window_days", "stats", "trends", "notice",
        "company_intelligence",
    )})
    view["trends"] = view.get("trends") or []
    view["stats"] = view.get("stats") or {}
    for trend in view["trends"]:
        trend["watch_area_label"] = watch_area_label(trend.get("watch_area"))
    intelligence = view.get("company_intelligence") or {}
    intelligence.setdefault("companies", [])
    view["company_intelligence"] = intelligence
    reason = str(intelligence.get("reason") or "")
    for company in intelligence["companies"]:
        company["display_summary"] = company_summary(company, reason)
        company.setdefault("briefs", [])
        company.setdefault("monitoring_items", [])
    refresh = payload.get("refresh") or {}
    view["refresh"] = {key: refresh.get(key) for key in ("outcome", "attempted_at")}
    view["refresh_label"] = {
        "success": "성공", "partial": "부분 완료", "failed": "실패",
    }.get(refresh.get("outcome"), "갱신 기록 없음")
    view["refresh_message"] = str(refresh.get("message") or "")
    if refresh.get("relevance_calls"):
        view["refresh_message"] = refresh_feedback(refresh)["message"]

    def sanitize(value: Any) -> None:
        if isinstance(value, dict):
            if "url" in value:
                value["url"] = safe_url(value["url"])
            for child in value.values():
                sanitize(child)
        elif isinstance(value, list):
            for child in value:
                sanitize(child)
    sanitize(view)
    return view


def refresh_feedback(report: Mapping[str, Any]) -> dict[str, str]:
    """Explain all stages, including a failed company after successful trends."""
    outcome = str(report.get("outcome") or ("success" if report.get("clustered") else "partial"))
    parts = []
    if report.get("clustered"):
        parts.append(f"트렌드 {report.get('trends', 0)}건 갱신")
    summary = str(report.get("summary") or "").replace("\n", " · ")
    if summary:
        parts.append(summary)
    if outcome != "success":
        error = str(report.get("error") or report.get("message") or "일부 분석을 완료하지 못했습니다.")
        if report.get("relevance_status") == "PARTIAL" and report.get("stage") == "relevance":
            error = "회사 관련성 분류가 일부 완료됐습니다. 성공한 회사의 결과는 저장했습니다."
        parts.append(error)
        if not report.get("clustered") and "기존" not in error:
            parts.append("기존 결과를 유지합니다.")
    names = {"hanwha_life": "한화생명", "hanwha_investment": "한화투자증권", "hanwha_asset_management": "한화자산운용"}
    failed = [names.get(cid, cid) + (": " + str(call["error_message"]) if call.get("error_message") else "") for cid, call in (report.get("relevance_calls") or {}).items()
              if call.get("status") == "failed"]
    if failed:
        parts.append("회사 분석 미완료: " + ", ".join(failed))
    return {"outcome": outcome, "message": " · ".join(parts)}

def company_summary(company: Mapping[str, Any], fallback_reason: str = "") -> str:
    """Describe existing brief counts only; unavailable data is not an empty result."""
    if company.get("status") != "AVAILABLE":
        own_reason = str(company.get("reason") or "").strip()
        if own_reason and own_reason != fallback_reason:
            return own_reason
        if fallback_reason:
            return "회사별 브리핑을 표시할 수 없습니다. 사유는 위 안내를 확인해 주세요."
        return "회사별 브리핑 데이터가 없어 이번 주 상태를 요약할 수 없습니다."

    briefs = company.get("briefs") or []
    monitoring = company.get("monitoring_items") or []
    if briefs:
        summary = str(company.get("weekly_summary_ko") or "").strip()
        return summary or (
            f"이번 주 {len(briefs)}건의 Main Brief와 "
            f"{len(monitoring)}건의 Monitoring 이슈가 확인되었습니다."
        )
    if monitoring:
        return (
            "이번 주 Main Brief 기준을 충족한 트렌드는 없으며, "
            f"{len(monitoring)}건의 Monitoring 이슈를 계속 관찰할 필요가 있습니다."
        )
    return (
        "이번 주 주요 트렌드 중 이 회사에 대해 "
        "추가 브리핑이 필요한 수준의 이슈는 확인되지 않았습니다."
    )
