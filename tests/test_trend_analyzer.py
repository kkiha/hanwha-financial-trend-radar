from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_finance.llm.trend_analyzer import analyze_trend, build_trend_messages
from rag_finance.profiles.loader import load_company_profiles
from rag_finance.retrieval.demo_index import build_demo_index
from rag_finance.retrieval.trend_pipeline import retrieve_trend_evidence
from rag_finance.signal.loader import load_signal


class TrendAnalyzerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signal = load_signal("data/sample_signals/us10y_drop.json")
        build_demo_index("data/demo_corpus", "indexes/demo_trends/index.json")
        cls.evidence, _ = retrieve_trend_evidence(
            cls.signal,
            index_path="indexes/demo_trends/index.json",
            keyword_dir="trend_keywords",
            evidence_snapshot_path=cls.signal.evidence_snapshot,
            topk=5,
        )
        cls.profiles = load_company_profiles("profiles")

    def test_cached_analysis_is_validated_and_enriched(self) -> None:
        result = analyze_trend(
            self.signal,
            self.evidence,
            self.profiles,
            demo_mode=True,
            cache_path=self.signal.cached_output,
        )
        self.assertEqual(result["metadata"]["analysis_mode"], "cached_llm_output")
        self.assertEqual(len(result["companies"]), 3)
        self.assertGreaterEqual(len(result["evidence"]), 3)
        self.assertFalse(result["metadata"]["investment_advice"])

    def test_cached_path_injects_relevance_and_direction_from_profile(self) -> None:
        result = analyze_trend(
            self.signal,
            self.evidence,
            self.profiles,
            demo_mode=True,
            cache_path=self.signal.cached_output,
        )
        for company, impact in result["companies"].items():
            exposure = self.profiles[company]["market_exposures"][self.signal.category]
            self.assertEqual(impact["relevance"], exposure["relevance"].upper())
            self.assertEqual(impact["direction"], exposure["direction"].upper())
            self.assertEqual(impact["positive_factors"], exposure["positive_factors"])
            self.assertEqual(impact["watchpoints"], exposure["watchpoints"])

    def test_prompt_contains_json_and_safety_contracts(self) -> None:
        messages = build_trend_messages(self.signal, self.evidence, self.profiles)
        system = messages[0]["content"]
        self.assertIn("JSON 객체만", system)
        self.assertIn("투자 추천", system)
        self.assertIn("TODO_VERIFY", system)
        self.assertIn("demo_snapshot", messages[1]["content"])

    def test_prompt_does_not_ask_the_model_for_relevance_or_direction(self) -> None:
        messages = build_trend_messages(self.signal, self.evidence, self.profiles)
        contract = json.loads(messages[1]["content"])["output_contract"]
        for company in ("한화생명", "한화투자증권", "한화자산운용"):
            self.assertNotIn("relevance", contract["companies"][company])
            self.assertNotIn("direction", contract["companies"][company])
            self.assertIn("impact_summary", contract["companies"][company])

    def test_live_provider_path_parses_and_validates_json(self) -> None:
        payload = Path(self.signal.cached_output).read_text(encoding="utf-8")

        class FakeCompletions:
            called = False

            def create(self, **kwargs):
                self.called = True
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = analyze_trend(
            self.signal,
            self.evidence,
            self.profiles,
            demo_mode=False,
            client=client,
        )
        self.assertTrue(completions.called)
        self.assertEqual(result["metadata"]["analysis_mode"], "live_llm")
        sent_payload = json.loads(completions.kwargs["messages"][1]["content"])
        self.assertEqual(sent_payload["signal"]["signal_id"], "US10Y_SAMPLE")
        # Live and cached paths converge on the same Profile-injected schema.
        for company, impact in result["companies"].items():
            exposure = self.profiles[company]["market_exposures"][self.signal.category]
            self.assertEqual(impact["relevance"], exposure["relevance"].upper())
            self.assertEqual(impact["direction"], exposure["direction"].upper())
            self.assertEqual(impact["key_metrics"], exposure["key_metrics"])


if __name__ == "__main__":
    unittest.main()
