from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag_finance.signal.schema import Signal


def load_trend_keywords(keyword_dir: str | Path, category: str) -> dict[str, Any]:
    path = Path(keyword_dir) / f"{category}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Trend keyword file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid trend keyword JSON: {path}: {exc}") from exc
    if payload.get("category") != category:
        raise ValueError(f"Trend keyword category mismatch: {path}")
    for key in ("hard_keywords", "soft_keywords"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"{key} must be a list: {path}")
        payload[key] = [str(value).strip() for value in payload[key] if str(value).strip()]
    return payload


def build_trend_queries(signal: Signal, keyword_map: dict[str, Any]) -> tuple[str, str]:
    base = " ".join(
        value for value in (signal.headline, signal.metric, signal.category, signal.direction) if value
    )
    hard = " ".join(keyword_map.get("hard_keywords", []))
    soft = " ".join(keyword_map.get("soft_keywords", []))
    return f"{base} {hard}".strip(), f"{base} {soft}".strip()
