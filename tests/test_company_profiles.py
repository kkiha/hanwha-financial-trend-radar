from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from rag_finance.profiles.company_profiles import (
    CompanyProfileError,
    load_all_company_profiles,
    load_company_profile,
    load_profile_schema,
)


class CompanyProfileLoadingTest(unittest.TestCase):
    def test_loads_three_profiles_and_twenty_four_queries(self) -> None:
        profiles = load_all_company_profiles()

        self.assertEqual(
            set(profiles),
            {"hanwha_life", "hanwha_asset_management", "hanwha_investment"},
        )
        queries = [query for profile in profiles.values() for query in profile["rss_queries"]]
        self.assertEqual(len(queries), 24)
        self.assertEqual(len({query["id"] for query in queries}), 24)
        for profile in profiles.values():
            languages = [query["language"] for query in profile["rss_queries"]]
            self.assertEqual(languages.count("ko"), 4)
            self.assertEqual(languages.count("en"), 4)

    def test_loads_one_profile_by_company_id(self) -> None:
        profile = load_company_profile("hanwha_life")
        self.assertEqual(profile["company_name"], "한화생명")
        self.assertEqual(profile["schema_version"], "1.0")

    def test_schema_required_fields_match_every_profile(self) -> None:
        schema = load_profile_schema()
        required = set(schema["required"])
        for profile in load_all_company_profiles().values():
            self.assertTrue(required <= set(profile))


class CompanyProfileValidationTest(unittest.TestCase):
    def _write_profiles(self, directory: Path, profiles: list[dict]) -> None:
        schema = load_profile_schema()
        (directory / "schema.json").write_text(
            json.dumps(schema, ensure_ascii=False), encoding="utf-8"
        )
        for index, profile in enumerate(profiles):
            (directory / f"profile_{index}.json").write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )

    def test_unknown_topic_reference_has_actionable_error(self) -> None:
        profile = deepcopy(load_company_profile("hanwha_life"))
        profile["rss_queries"][0]["topic_ids"] = ["missing_topic"]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_profiles(Path(tmp), [profile])
            with self.assertRaisesRegex(CompanyProfileError, "unknown topic_ids"):
                load_all_company_profiles(tmp)

    def test_unknown_business_reference_has_actionable_error(self) -> None:
        profile = deepcopy(load_company_profile("hanwha_life"))
        profile["watch_topics"][0]["related_business_ids"] = ["missing_business"]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_profiles(Path(tmp), [profile])
            with self.assertRaisesRegex(CompanyProfileError, "unknown related_business_ids"):
                load_all_company_profiles(tmp)

    def test_duplicate_company_and_query_ids_are_rejected(self) -> None:
        profile = load_company_profile("hanwha_life")
        duplicate = deepcopy(profile)
        with tempfile.TemporaryDirectory() as tmp:
            self._write_profiles(Path(tmp), [profile, duplicate])
            with self.assertRaisesRegex(CompanyProfileError, "Duplicate company_id"):
                load_all_company_profiles(tmp)

        duplicate = deepcopy(load_company_profile("hanwha_asset_management"))
        duplicate["rss_queries"][0]["id"] = profile["rss_queries"][0]["id"]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_profiles(Path(tmp), [profile, duplicate])
            with self.assertRaisesRegex(CompanyProfileError, "Duplicate RSS query id"):
                load_all_company_profiles(tmp)


if __name__ == "__main__":
    unittest.main()
