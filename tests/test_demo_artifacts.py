from __future__ import annotations

import unittest

from app.dashboard_data import COMPANY_ORDER, SIGNAL_CATALOG
from rag_finance.llm.trend_analyzer import analyze_trend
from rag_finance.profiles.loader import load_company_profiles
from rag_finance.retrieval.demo_index import build_demo_index
from rag_finance.retrieval.trend_pipeline import retrieve_trend_evidence
from rag_finance.signal.loader import load_signal


class DemoArtifactValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index_path = "indexes/demo_trends/index.json"
        cls.index = build_demo_index("data/demo_corpus", cls.index_path)
        cls.profiles = load_company_profiles("profiles")

    def test_all_cached_artifacts_pass_day1_validation(self) -> None:
        self.assertEqual(self.index["document_count"], 26)
        self.assertEqual(len(SIGNAL_CATALOG), 3)
        for signal_id, entry in SIGNAL_CATALOG.items():
            with self.subTest(signal_id=signal_id):
                signal = load_signal(entry["signal_path"])
                evidence, _ = retrieve_trend_evidence(
                    signal,
                    index_path=self.index_path,
                    keyword_dir="trend_keywords",
                    evidence_snapshot_path=entry["evidence_path"],
                    topk=5,
                )
                result = analyze_trend(
                    signal,
                    evidence,
                    self.profiles,
                    demo_mode=True,
                    cache_path=entry["cache_path"],
                )
                self.assertEqual(signal.signal_id, signal_id)
                self.assertGreaterEqual(len(evidence), 3)
                self.assertEqual(tuple(result["companies"]), COMPANY_ORDER)
                path_sets = {
                    tuple(result["companies"][company]["transmission_paths"])
                    for company in COMPANY_ORDER
                }
                self.assertEqual(len(path_sets), 3)


if __name__ == "__main__":
    unittest.main()
