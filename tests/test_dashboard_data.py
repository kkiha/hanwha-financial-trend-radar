from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.dashboard_data import COMPANY_ORDER, available_signal_ids, load_dashboard_payload


class DashboardDataTest(unittest.TestCase):
    def test_loads_day1_artifacts_by_signal_id(self) -> None:
        payload = load_dashboard_payload("US10Y_SAMPLE")
        self.assertEqual(payload["signal"]["headline"], "미국 장기금리 급락")
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
