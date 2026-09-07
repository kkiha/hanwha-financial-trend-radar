"""Shared OpenAI transport settings; application code owns all retries."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_REASONING_EFFORT = "none"


def resolve_api_key(api_key: str | None = None) -> str:
    if api_key is not None:
        return api_key.strip()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    # Streamlit Cloud secrets are read on the server, never sent to the UI.
    try:
        import streamlit as st
        if st.runtime.exists():
            return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except (ImportError, FileNotFoundError, KeyError):
        pass
    return ""


def create_client(key: str) -> Any:
    from openai import OpenAI
    return OpenAI(api_key=key, base_url="https://api.openai.com/v1",
                  timeout=45.0, max_retries=0)


def completion_options(*, model: str, max_tokens: int,
                       reasoning_effort: str | None, temperature: float) -> dict[str, Any]:
    options: dict[str, Any] = {
        "model": model, "max_completion_tokens": max_tokens, "store": False,
    }
    effort = reasoning_effort or DEFAULT_REASONING_EFFORT
    options["reasoning_effort"] = effort
    # Omit sampling controls for reasoning runs to avoid incompatible parameters.
    if effort == "none":
        options["temperature"] = temperature
    return options


def api_error_message(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "OpenAI API 키 인증에 실패했습니다. OPENAI_API_KEY를 확인해 주세요."
    if status == 403:
        return "OpenAI 프로젝트의 모델 접근 권한을 확인해 주세요."
    if status == 404:
        return "OpenAI 모델 이름 또는 프로젝트의 모델 접근 권한을 확인해 주세요."
    if status == 429:
        if getattr(exc, "code", None) == "insufficient_quota":
            return "OpenAI API 잔액 또는 사용 예산이 부족합니다. API 결제 설정을 확인해 주세요."
        return "OpenAI API 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
    if status == 400:
        return "OpenAI 요청 형식 또는 모델 옵션이 유효하지 않습니다. 서버 설정을 확인해 주세요."
    return "OpenAI API 연결 또는 요청 처리에 실패했습니다. 잠시 후 다시 시도해 주세요."


def is_permanent_api_error(exc: Exception) -> bool:
    return (getattr(exc, "status_code", None) in {400, 401, 403, 404, 413, 422}
            or getattr(exc, "code", None) == "insufficient_quota")
