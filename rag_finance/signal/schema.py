from __future__ import annotations

from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any, Mapping


TREND_CATEGORIES = {"interest_rate", "equity", "fx", "credit", "volatility"}
SIGNAL_DIRECTIONS = {"up", "down", "flat"}


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing required text field: {key}")
    return value


def _optional_number(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{key} must be numeric or null")
    return float(value)


@dataclass(frozen=True)
class Signal:
    signal_id: str
    metric: str
    category: str
    current: float | None
    weekly_change: float | None
    weekly_change_unit: str
    z_score: float | None
    direction: str
    headline: str
    observed_at: str
    data_mode: str
    snapshot_notice: str
    evidence_snapshot: str = ""
    cached_output: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Signal":
        category = _required_text(data, "category").lower()
        if category not in TREND_CATEGORIES:
            raise ValueError(f"Unsupported trend category: {category}")

        direction = _required_text(data, "direction").lower()
        if direction not in SIGNAL_DIRECTIONS:
            raise ValueError(f"Unsupported signal direction: {direction}")

        data_mode = _required_text(data, "data_mode")
        if data_mode not in {"demo_snapshot", "snapshot", "live"}:
            raise ValueError(f"Unsupported data_mode: {data_mode}")

        snapshot_notice = _required_text(data, "snapshot_notice")
        return cls(
            signal_id=_required_text(data, "signal_id"),
            metric=_required_text(data, "metric"),
            category=category,
            current=_optional_number(data, "current"),
            weekly_change=_optional_number(data, "weekly_change"),
            weekly_change_unit=_required_text(data, "weekly_change_unit"),
            z_score=_optional_number(data, "z_score"),
            direction=direction,
            headline=_required_text(data, "headline"),
            observed_at=_required_text(data, "observed_at"),
            data_mode=data_mode,
            snapshot_notice=snapshot_notice,
            evidence_snapshot=str(data.get("evidence_snapshot", "")).strip(),
            cached_output=str(data.get("cached_output", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    document_id: str
    title: str
    source: str
    date: str
    url: str
    excerpt: str
    category: str
    data_mode: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
