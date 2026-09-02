from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_finance.retrieval.demo_index import build_demo_index
from rag_finance.retrieval.trend_pipeline import retrieve_trend_evidence
from rag_finance.signal.loader import load_signal


class TrendPipelineTest(unittest.TestCase):
    def test_builds_separate_index_and_retrieves_snapshot_evidence(self) -> None:
        signal = load_signal("data/sample_signals/us10y_drop.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "demo_trends" / "index.json"
            index = build_demo_index("data/demo_corpus", index_path)
            evidence, debug = retrieve_trend_evidence(
                signal,
                index_path=index_path,
                keyword_dir="trend_keywords",
                evidence_snapshot_path=signal.evidence_snapshot,
                topk=5,
            )

        self.assertEqual(index["document_count"], 26)
        self.assertGreaterEqual(len(evidence), 3)
        self.assertTrue(all(item.data_mode == "demo_snapshot" for item in evidence))
        self.assertEqual(debug["retrieval_mode"], "snapshot_bm25_rrf")
        self.assertFalse(debug["company_filter_applied"])
        self.assertIn("IR_DEMO_001", {item.document_id for item in evidence})


if __name__ == "__main__":
    unittest.main()
