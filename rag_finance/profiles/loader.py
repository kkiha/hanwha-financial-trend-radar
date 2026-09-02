from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_SOURCE_STATUS = {"VERIFIED", "USER_PROVIDED", "TODO_VERIFY"}
EXPECTED_COMPANIES = {"한화생명", "한화투자증권", "한화자산운용"}


def _load_yaml_compatible(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            from omegaconf import OmegaConf
        except ImportError as exc:
            raise RuntimeError(
                f"{path} is YAML rather than JSON-compatible YAML; install omegaconf"
            ) from exc
        payload = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if not isinstance(payload, dict):
        raise ValueError(f"Company profile must be an object: {path}")
    return payload


def _validate_profile(profile: dict[str, Any], path: Path) -> dict[str, Any]:
    company = str(profile.get("company", "")).strip()
    business_type = str(profile.get("business_type", "")).strip()
    exposures = profile.get("market_exposures")
    if not company or not business_type or not isinstance(exposures, dict):
        raise ValueError(f"Invalid company profile structure: {path}")
    for category, exposure in exposures.items():
        if not isinstance(exposure, dict):
            raise ValueError(f"Invalid exposure {category}: {path}")
        status = exposure.get("source_status")
        if status not in ALLOWED_SOURCE_STATUS:
            raise ValueError(f"Invalid source_status for {company}/{category}: {status}")
        if not isinstance(exposure.get("transmission_paths"), list):
            raise ValueError(f"transmission_paths must be a list: {path}")
    return profile


def load_company_profiles(profile_dir: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(profile_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Profile directory not found: {root}")
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.yaml")):
        profile = _validate_profile(_load_yaml_compatible(path), path)
        company = profile["company"]
        if company in profiles:
            raise ValueError(f"Duplicate company profile: {company}")
        profiles[company] = profile
    missing = EXPECTED_COMPANIES - profiles.keys()
    if missing:
        raise ValueError(f"Missing required company profiles: {sorted(missing)}")
    return profiles
