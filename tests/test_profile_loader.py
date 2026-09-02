from __future__ import annotations

import unittest

from rag_finance.profiles.loader import EXPECTED_COMPANIES, load_company_profiles


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
                self.assertTrue(exposure["transmission_paths"])


if __name__ == "__main__":
    unittest.main()
