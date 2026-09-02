from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPANY_ORDER = ("한화생명", "한화투자증권", "한화자산운용")

SIGNAL_CATALOG: dict[str, dict[str, str]] = {
    "US10Y_SAMPLE": {
        "label": "미국 장기금리 급락",
        "signal_path": "data/sample_signals/us10y_drop.json",
        "cache_path": "data/demo_outputs/us10y_sample_analysis.json",
        "evidence_path": "data/demo_evidence/us10y_sample_evidence.json",
    },
    "VIX_SPIKE": {
        "label": "VIX 급등과 Risk-off 확산",
        "signal_path": "data/sample_signals/vix_spike.json",
        "cache_path": "data/demo_outputs/vix_spike_analysis.json",
        "evidence_path": "data/demo_evidence/vix_spike_evidence.json",
    },
    "USDKRW_MOVE": {
        "label": "USD/KRW 급등과 원화 약세",
        "signal_path": "data/sample_signals/usdkrw_move.json",
        "cache_path": "data/demo_outputs/usdkrw_move_analysis.json",
        "evidence_path": "data/demo_evidence/usdkrw_move_evidence.json",
    }
}


def _empty_company() -> dict[str, Any]:
    return {
        "relevance": "정보 없음",
        "direction": "정보 없음",
        "transmission_paths": [],
        "insight": "분석 결과가 없습니다.",
    }


def _read_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{label} 파일을 찾을 수 없습니다: {path}")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} 파일을 읽을 수 없습니다: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label} 데이터가 JSON object가 아닙니다.")
        return {}
    return payload


def available_signal_ids(catalog: Mapping[str, Mapping[str, str]] | None = None) -> list[str]:
    return list((catalog or SIGNAL_CATALOG).keys())


def signal_label(signal_id: str, catalog: Mapping[str, Mapping[str, str]] | None = None) -> str:
    entry = (catalog or SIGNAL_CATALOG).get(signal_id, {})
    return str(entry.get("label") or signal_id)


def load_dashboard_payload(
    signal_id: str,
    *,
    project_root: str | Path = PROJECT_ROOT,
    catalog: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Load Day 1 artifacts and normalize missing fields for the presentation layer."""
    active_catalog = catalog or SIGNAL_CATALOG
    entry = active_catalog.get(signal_id)
    errors: list[str] = []
    if not entry:
        errors.append(f"등록되지 않은 Signal ID입니다: {signal_id}")
        entry = {}

    root = Path(project_root)
    signal_data = _read_json(root / entry["signal_path"], errors, "Signal") if entry.get("signal_path") else {}
    analysis_data = _read_json(root / entry["cache_path"], errors, "Cached analysis") if entry.get("cache_path") else {}
    evidence_data = _read_json(root / entry["evidence_path"], errors, "Evidence") if entry.get("evidence_path") else {}

    cached_signal = analysis_data.get("signal")
    if not isinstance(cached_signal, dict):
        cached_signal = {}
    signal = dict(cached_signal)
    for key in (
        "signal_id", "headline", "metric", "category", "current", "weekly_change",
        "weekly_change_unit", "z_score", "direction", "observed_at", "data_mode",
        "snapshot_notice",
    ):
        value = signal_data.get(key)
        if value not in (None, ""):
            signal[key] = value
    signal.setdefault("signal_id", signal_id)
    signal.setdefault("headline", entry.get("label", "Signal 정보 없음"))
    signal.setdefault("data_mode", "demo_snapshot")
    signal.setdefault("snapshot_notice", "시연용 Snapshot 데이터입니다.")

    evidence = analysis_data.get("evidence")
    if not isinstance(evidence, list):
        evidence = evidence_data.get("evidence", [])
    evidence = [item for item in evidence if isinstance(item, dict)][:5]

    raw_companies = analysis_data.get("companies")
    if not isinstance(raw_companies, dict):
        raw_companies = {}
    companies: dict[str, dict[str, Any]] = {}
    for company in COMPANY_ORDER:
        impact = raw_companies.get(company)
        companies[company] = dict(impact) if isinstance(impact, dict) else _empty_company()
        companies[company].setdefault("relevance", "정보 없음")
        companies[company].setdefault("direction", "정보 없음")
        if not isinstance(companies[company].get("transmission_paths"), list):
            companies[company]["transmission_paths"] = []
        companies[company].setdefault("insight", "분석 결과가 없습니다.")

    return {
        "signal_id": signal_id,
        "signal": signal,
        "evidence": evidence,
        "companies": companies,
        "metadata": {
            "data_mode": signal.get("data_mode", "demo_snapshot"),
            "analysis_mode": "cached_llm_output",
            "snapshot_notice": signal.get("snapshot_notice", "시연용 Snapshot 데이터입니다."),
        },
        "errors": errors,
    }
