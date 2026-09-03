from __future__ import annotations

import unittest

from rag_finance.profiles.loader import (
    EXPECTED_COMPANIES,
    apply_profile_exposure,
    load_company_profiles,
)


class ProfileLoaderTest(unittest.TestCase):
    def test_loads_all_poc_companies_and_source_status(self) -> None:
        profiles = load_company_profiles("profiles")
        self.assertEqual(set(profiles), EXPECTED_COMPANIES)
        for profile in profiles.values():
            self.assertEqual(
                set(profile["market_exposures"]),
                {"interest_rate", "volatility", "fx"},
            )
            for exposure in profile["market_exposures"].values():
                self.assertEqual(exposure["source_status"], "TODO_VERIFY")
                for field in ("transmission_paths", "key_metrics", "watchpoints"):
                    self.assertIsInstance(exposure[field], list)
                    self.assertTrue(exposure[field])
                for field in ("positive_factors", "negative_factors"):
                    self.assertIsInstance(exposure[field], list)
                self.assertTrue(
                    exposure["positive_factors"] or exposure["negative_factors"]
                )
                self.assertIn(exposure["relevance"], {"high", "medium", "low"})
                self.assertIn(
                    exposure["direction"], {"positive", "negative", "mixed", "neutral"}
                )

    def test_apply_profile_exposure_overwrites_relevance_and_direction(self) -> None:
        profiles = load_company_profiles("profiles")
        companies = {
            "한화생명": {"relevance": "LOW", "direction": "POSITIVE", "insight": "keep me"},
        }
        apply_profile_exposure(companies, profiles, "interest_rate")

        impact = companies["한화생명"]
        self.assertEqual(impact["relevance"], "HIGH")
        self.assertEqual(impact["direction"], "MIXED")
        self.assertEqual(impact["insight"], "keep me")
        self.assertIn("보유 채권 평가환경 개선", impact["positive_factors"])
        self.assertTrue(impact["watchpoints"])

    def test_apply_profile_exposure_ignores_unknown_category(self) -> None:
        profiles = load_company_profiles("profiles")
        companies = {"한화생명": {"relevance": "정보 없음", "direction": "정보 없음"}}
        apply_profile_exposure(companies, profiles, None)
        self.assertEqual(companies["한화생명"]["relevance"], "정보 없음")


if __name__ == "__main__":
    unittest.main()
