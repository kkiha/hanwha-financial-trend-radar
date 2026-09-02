from __future__ import annotations

import unittest
from pathlib import Path


class ExistingRetrievalContractTest(unittest.TestCase):
    def test_company_retrieval_entrypoint_is_preserved(self) -> None:
        source = Path("rag_finance/retrieval/pipeline.py").read_text(encoding="utf-8")
        self.assertIn("def retrieve_with_keywords(", source)


if __name__ == "__main__":
    unittest.main()
