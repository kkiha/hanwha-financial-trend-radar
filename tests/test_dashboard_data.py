from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.dashboard_data import (
    COMPANY_ORDER,
    SIGNAL_CATALOG,
    available_signal_ids,
    load_dashboard_payload,
)
from rag_finance.profiles.loader import load_company_profiles


class DashboardDataTest(unittest.TestCase):
    def test_loads_day1_artifacts_by_signal_id(self) -> None:
        payload = load_dashboard_payload("US10Y_SAMPLE")
        self.assertEqual(payload["signal"]["headline"], "미국 장기금리 급락")
        self.assertTrue(payload["trend_summary"])
        self.assertEqual(len(payload["causes"]), 3)
        self.assertGreaterEqual(len(payload["evidence"]), 3)
        self.assertEqual(tuple(payload["companies"]), COMPANY_ORDER)
        self.assertEqual(payload["metadata"]["data_mode"], "demo_snapshot")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(
            available_signal_ids(),
            ["US10Y_SAMPLE", "VIX_SPIKE", "USDKRW_MOVE"],
        )

    def test_all_signals_load_distinct_evidence_and_impacts(self) -> None:
        payloads = {
            signal_id: load_dashboard_payload(signal_id)
            for signal_id in available_signal_ids()
        }
        metrics = {payload["signal"]["metric"] for payload in payloads.values()}
        first_evidence_ids = {
            payload["evidence"][0]["document_id"] for payload in payloads.values()
        }
        self.assertEqual(len(metrics), 3)
        self.assertEqual(len(first_evidence_ids), 3)
        for payload in payloads.values():
            self.assertEqual(payload["errors"], [])
            self.assertGreaterEqual(len(payload["evidence"]), 3)
            company_paths = {
                tuple(impact["transmission_paths"])
                for impact in payload["companies"].values()
            }
            self.assertEqual(len(company_paths), 3)
        for company in COMPANY_ORDER:
            paths_across_signals = {
                tuple(payload["companies"][company]["transmission_paths"])
                for payload in payloads.values()
            }
            self.assertEqual(len(paths_across_signals), 3)

    def test_relevance_and_direction_come_from_company_profile(self) -> None:
        profiles = load_company_profiles("profiles")
        for signal_id, entry in SIGNAL_CATALOG.items():
            cached = json.loads(
                Path(entry["cache_path"]).read_text(encoding="utf-8")
            )
            payload = load_dashboard_payload(signal_id)
            category = payload["signal"]["category"]
            for company in COMPANY_ORDER:
                with self.subTest(signal_id=signal_id, company=company):
                    # The cached LLM output must not carry these fields at all.
                    self.assertNotIn("relevance", cached["companies"][company])
                    self.assertNotIn("direction", cached["companies"][company])
                    exposure = profiles[company]["market_exposures"][category]
                    impact = payload["companies"][company]
                    self.assertEqual(impact["relevance"], exposure["relevance"].upper())
                    self.assertEqual(impact["direction"], exposure["direction"].upper())
                    self.assertEqual(impact["positive_factors"], exposure["positive_factors"])
                    self.assertEqual(impact["negative_factors"], exposure["negative_factors"])
                    self.assertEqual(impact["key_metrics"], exposure["key_metrics"])
                    self.assertEqual(impact["watchpoints"], exposure["watchpoints"])
                    self.assertTrue(impact["impact_summary"])

    def test_missing_json_fields_return_safe_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "signal.json").write_text(
                json.dumps({"signal_id": "BROKEN", "headline": "Fallback test"}),
                encoding="utf-8",
            )
            (root / "analysis.json").write_text("{}", encoding="utf-8")
            (root / "evidence.json").write_text("{}", encoding="utf-8")
            catalog = {
                "BROKEN": {
                    "label": "Fallback test",
                    "signal_path": "signal.json",
                    "cache_path": "analysis.json",
                    "evidence_path": "evidence.json",
                }
            }
            payload = load_dashboard_payload("BROKEN", project_root=root, catalog=catalog)

        self.assertEqual(payload["evidence"], [])
        self.assertEqual(tuple(payload["companies"]), COMPANY_ORDER)
        for company in COMPANY_ORDER:
            self.assertEqual(payload["companies"][company]["relevance"], "정보 없음")
            self.assertEqual(payload["companies"][company]["transmission_paths"], [])


if __name__ == "__main__":
    unittest.main()
