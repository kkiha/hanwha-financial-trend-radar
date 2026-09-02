from __future__ import annotations

import json
from pathlib import Path

from .schema import Signal


def load_signal(path: str | Path) -> Signal:
    signal_path = Path(path)
    try:
        payload = json.loads(signal_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Signal file not found: {signal_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid signal JSON: {signal_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Signal payload must be a JSON object: {signal_path}")
    return Signal.from_mapping(payload)
