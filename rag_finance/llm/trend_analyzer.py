from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from rag_finance.profiles.loader import apply_profile_exposure
from rag_finance.signal.schema import Evidence, Signal


RELEVANCE_VALUES = {"HIGH", "MEDIUM", "LOW"}
DIRECTION_VALUES = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"}
EXPECTED_COMPANIES = ("한화생명", "한화투자증권", "한화자산운용")


def build_trend_messages(
    signal: Signal,
    evidence: Sequence[Evidence],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    scoped_profiles: dict[str, Any] = {}
    for company in EXPECTED_COMPANIES:
        profile = profiles[company]
        scoped_profiles[company] = {
            "company": company,
            "business_type": profile.get("business_type"),
            "market_exposure": profile.get("market_exposures", {}).get(signal.category, {}),
        }

    system_prompt = """너는 금융 Trend Intelligence 분석기다.
반드시 JSON 객체만 출력하고 Markdown이나 설명 문장을 JSON 밖에 쓰지 마라.
Company Profile에 없는 사업구조를 만들지 마라.
source_status가 TODO_VERIFY인 항목은 제한된 Prototype 가정이며 사실처럼 확장하지 마라.
Evidence에 없는 사건과 숫자를 만들지 마라.
투자 추천이나 매수·매도 의견을 쓰지 마라.
relevance와 direction은 시스템이 Company Profile에서 직접 주입하므로 생성하지 마라.
Profile의 positive_factors와 negative_factors를 근거로 해석 문장을 작성하라.
impact_summary는 회사별 차이가 드러나는 한 문장으로 쓰고 insight는 두세 문장으로 풀어라.
companies에는 한화생명, 한화투자증권, 한화자산운용을 모두 포함하라."""
    contract = {
        "signal": {
            "metric": "string",
            "category": "string",
            "direction": "string",
            "weekly_change": "number|null",
            "z_score": "number|null",
        },
        "trend_summary": "string",
        "causes": ["string"],
        "companies": {
            company: {
                "impact_summary": "string",
                "transmission_paths": ["profile에 존재하는 string"],
                "insight": "string",
            }
            for company in EXPECTED_COMPANIES
        },
    }
    user_payload = {
        "output_contract": contract,
        "signal": signal.to_dict(),
        "evidence": [item.to_dict() for item in evidence],
        "company_profiles": scoped_profiles,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def parse_structured_json(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM output must be a JSON object")
    return payload


def validate_structured_analysis(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    signal = result.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("Structured analysis requires a signal object")
    for key in ("metric", "category", "direction", "weekly_change", "z_score"):
        if key not in signal:
            raise ValueError(f"Structured analysis signal missing: {key}")
    if not isinstance(result.get("trend_summary"), str) or not result["trend_summary"].strip():
        raise ValueError("Structured analysis requires trend_summary")
    if not isinstance(result.get("causes"), list):
        raise ValueError("Structured analysis causes must be a list")

    companies = result.get("companies")
    if not isinstance(companies, dict):
        raise ValueError("Structured analysis requires companies")
    for company in EXPECTED_COMPANIES:
        impact = companies.get(company)
        if not isinstance(impact, dict):
            raise ValueError(f"Structured analysis missing company: {company}")
        # relevance/direction are Profile-owned and injected after validation. They
        # are only checked when a payload still carries them.
        if "relevance" in impact and impact["relevance"] not in RELEVANCE_VALUES:
            raise ValueError(f"Invalid relevance for {company}: {impact.get('relevance')}")
        if "direction" in impact and impact["direction"] not in DIRECTION_VALUES:
            raise ValueError(f"Invalid direction for {company}: {impact.get('direction')}")
        if not isinstance(impact.get("transmission_paths"), list):
            raise ValueError(f"transmission_paths must be a list for {company}")
        if not isinstance(impact.get("insight"), str):
            raise ValueError(f"insight must be text for {company}")
        if "impact_summary" in impact and not isinstance(impact["impact_summary"], str):
            raise ValueError(f"impact_summary must be text for {company}")
    return result


def _load_cached_analysis(path: str | Path) -> dict[str, Any]:
    cache_path = Path(path)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Cached analysis not found: {cache_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid cached analysis JSON: {cache_path}: {exc}") from exc
    return validate_structured_analysis(payload)


def _validate_profile_grounding(
    result: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    category: str,
) -> None:
    for company in EXPECTED_COMPANIES:
        exposure = profiles[company].get("market_exposures", {}).get(category, {})
        allowed_paths = set(exposure.get("transmission_paths", []))
        returned_paths = set(result["companies"][company]["transmission_paths"])
        invented = returned_paths - allowed_paths
        if invented:
            raise ValueError(f"Analysis invented transmission paths for {company}: {sorted(invented)}")


def analyze_trend(
    signal: Signal,
    evidence: Sequence[Evidence],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    demo_mode: bool,
    cache_path: str | Path | None = None,
    client: Any = None,
    api_key: str | None = None,
    model: str = "llama-3.3-70b-versatile",
    temperature: float = 0.1,
    max_tokens: int = 1400,
) -> dict[str, Any]:
    if len(evidence) < 3:
        raise ValueError("At least three evidence items are required for analysis")

    if demo_mode:
        if not cache_path:
            raise ValueError("DEMO_MODE requires a cached analysis path")
        result = _load_cached_analysis(cache_path)
        analysis_mode = "cached_llm_output"
    else:
        if client is None:
            key = api_key or os.environ.get("GROQ_API_KEY", "")
            if not key:
                raise RuntimeError("GROQ_API_KEY is required when DEMO_MODE is false")
            try:
                from groq import Groq
            except ImportError as exc:
                raise RuntimeError("Install the groq package for live LLM analysis") from exc
            client = Groq(api_key=key)
        messages = build_trend_messages(signal, evidence, profiles)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = validate_structured_analysis(parse_structured_json(response.choices[0].message.content))
        analysis_mode = "live_llm"

    if result["signal"].get("metric") != signal.metric:
        raise ValueError("Analysis signal metric does not match the input signal")
    if result["signal"].get("category") != signal.category:
        raise ValueError("Analysis signal category does not match the input signal")
    _validate_profile_grounding(result, profiles, signal.category)
    # Single injection point shared by the cached and live paths: relevance,
    # direction and the exposure factor lists always come from the Company Profile.
    apply_profile_exposure(result["companies"], profiles, signal.category)

    result["evidence"] = [item.to_dict() for item in evidence]
    result["metadata"] = {
        "data_mode": signal.data_mode,
        "analysis_mode": analysis_mode,
        "snapshot_notice": signal.snapshot_notice,
        "investment_advice": False,
    }
    return result
