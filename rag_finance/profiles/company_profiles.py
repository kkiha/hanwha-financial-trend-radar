"""Load and validate compact runtime profiles for Hanwha financial affiliates."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_DIR = PROJECT_ROOT / "configs" / "company_profiles"
SCHEMA_FILENAME = "schema.json"


class CompanyProfileError(ValueError):
    """A profile file is missing, malformed, or internally inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompanyProfileError(f"Company profile file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CompanyProfileError(
            f"Invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise CompanyProfileError(f"Could not read company profile file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompanyProfileError(f"{path.name}: root value must be an object")
    return value


def load_profile_schema(
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    return _read_json(Path(profiles_dir) / SCHEMA_FILENAME)


def _resolve_ref(reference: str, root_schema: Mapping[str, Any]) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise CompanyProfileError(f"Unsupported external schema reference: {reference}")
    node: Any = root_schema
    for part in reference[2:].split("/"):
        if not isinstance(node, Mapping) or part not in node:
            raise CompanyProfileError(f"Invalid schema reference: {reference}")
        node = node[part]
    if not isinstance(node, Mapping):
        raise CompanyProfileError(f"Schema reference is not an object: {reference}")
    return node


def _validate_schema(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    *,
    path: str,
) -> None:
    """Validate the JSON Schema subset used by the checked-in runtime schema."""
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(str(schema["$ref"]), root_schema), root_schema, path=path)
        return

    if "const" in schema and value != schema["const"]:
        raise CompanyProfileError(f"{path}: expected {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise CompanyProfileError(f"{path}: value {value!r} is not one of {schema['enum']!r}")

    expected_type = schema.get("type")
    type_matches = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if expected_type and not type_matches.get(str(expected_type), False):
        raise CompanyProfileError(f"{path}: expected {expected_type}, got {type(value).__name__}")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise CompanyProfileError(f"{path}: string must contain at least {minimum} character(s)")
        pattern = schema.get("pattern")
        if pattern and re.search(str(pattern), value) is None:
            raise CompanyProfileError(f"{path}: value {value!r} does not match {pattern!r}")
        if schema.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise CompanyProfileError(f"{path}: expected an ISO date, got {value!r}") from exc

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise CompanyProfileError(f"{path}: expected at least {minimum} item(s)")
        if isinstance(maximum, int) and len(value) > maximum:
            raise CompanyProfileError(f"{path}: expected at most {maximum} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, root_schema, path=f"{path}[{index}]")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        missing = [field for field in required if field not in value]
        if missing:
            raise CompanyProfileError(f"{path}: missing required field(s): {', '.join(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise CompanyProfileError(f"{path}: unexpected field(s): {', '.join(extras)}")
        if isinstance(properties, Mapping):
            for field, child_schema in properties.items():
                if field in value and isinstance(child_schema, Mapping):
                    _validate_schema(
                        value[field], child_schema, root_schema, path=f"{path}.{field}"
                    )


def _unique_ids(items: Any, *, field: str, profile_name: str) -> set[str]:
    if not isinstance(items, list):
        raise CompanyProfileError(f"{profile_name}.{field}: expected a list")
    identifiers = [str(item.get("id")) for item in items if isinstance(item, Mapping)]
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        raise CompanyProfileError(
            f"{profile_name}.{field}: duplicate id(s): {', '.join(duplicates)}"
        )
    return set(identifiers)


def validate_company_profile(
    profile: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    source_name: str = "profile",
) -> dict[str, Any]:
    _validate_schema(profile, schema, schema, path=source_name)
    normalized = dict(profile)
    company_id = str(normalized["company_id"])
    business_ids = _unique_ids(
        normalized["business_areas"], field="business_areas", profile_name=source_name
    )
    topic_ids = _unique_ids(
        normalized["watch_topics"], field="watch_topics", profile_name=source_name
    )
    _unique_ids(normalized["rss_queries"], field="rss_queries", profile_name=source_name)

    for topic in normalized["watch_topics"]:
        unknown = sorted(set(topic["related_business_ids"]) - business_ids)
        if unknown:
            raise CompanyProfileError(
                f"{source_name}.watch_topics[{topic['id']}]: unknown related_business_ids: "
                f"{', '.join(unknown)}"
            )
    for query in normalized["rss_queries"]:
        unknown = sorted(set(query["topic_ids"]) - topic_ids)
        if unknown:
            raise CompanyProfileError(
                f"{source_name}.rss_queries[{query['id']}]: unknown topic_ids: "
                f"{', '.join(unknown)}"
            )

    normalized["company_id"] = company_id
    return normalized


def load_company_profile(
    company_id: str,
    *,
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
) -> dict[str, Any]:
    directory = Path(profiles_dir)
    schema = load_profile_schema(directory)
    path = directory / f"{company_id}.json"
    profile = validate_company_profile(_read_json(path), schema, source_name=path.name)
    if profile["company_id"] != company_id:
        raise CompanyProfileError(
            f"{path.name}: company_id {profile['company_id']!r} does not match filename"
        )
    return profile


def load_all_company_profiles(
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
) -> dict[str, dict[str, Any]]:
    directory = Path(profiles_dir)
    schema = load_profile_schema(directory)
    paths = sorted(directory.glob("*.json"))
    paths = [path for path in paths if path.name != SCHEMA_FILENAME]
    if not paths:
        raise CompanyProfileError(f"No company profiles found in {directory}")

    profiles: dict[str, dict[str, Any]] = {}
    query_owners: dict[str, str] = {}
    for path in paths:
        profile = validate_company_profile(_read_json(path), schema, source_name=path.name)
        company_id = profile["company_id"]
        if company_id in profiles:
            raise CompanyProfileError(
                f"Duplicate company_id {company_id!r} in {path.name} and another profile"
            )
        for query in profile["rss_queries"]:
            query_id = query["id"]
            if query_id in query_owners:
                raise CompanyProfileError(
                    f"Duplicate RSS query id {query_id!r} in {path.name} and "
                    f"{query_owners[query_id]}"
                )
            query_owners[query_id] = path.name
        profiles[company_id] = profile
    return profiles

