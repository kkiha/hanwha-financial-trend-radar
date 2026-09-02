from __future__ import annotations

import json

from app.dashboard_data import COMPANY_ORDER, SIGNAL_CATALOG, load_dashboard_payload
from rag_finance.llm.trend_analyzer import analyze_trend
from rag_finance.profiles.loader import load_company_profiles
from rag_finance.retrieval.demo_index import build_demo_index
from rag_finance.retrieval.trend_pipeline import retrieve_trend_evidence
from rag_finance.signal.loader import load_signal


def main() -> None:
    index_path = "indexes/demo_trends/index.json"
    index = build_demo_index("data/demo_corpus", index_path)
    profiles = load_company_profiles("profiles")
    summaries: list[dict] = []

    for signal_id, entry in SIGNAL_CATALOG.items():
        signal = load_signal(entry["signal_path"])
        if signal.signal_id != signal_id:
            raise ValueError(f"Catalog ID mismatch: {signal_id} != {signal.signal_id}")
        evidence, debug = retrieve_trend_evidence(
            signal,
            index_path=index_path,
            keyword_dir="trend_keywords",
            evidence_snapshot_path=entry["evidence_path"],
            topk=5,
        )
        result = analyze_trend(
            signal,
            evidence,
            profiles,
            demo_mode=True,
            cache_path=entry["cache_path"],
        )
        dashboard = load_dashboard_payload(signal_id)
        if dashboard["errors"]:
            raise ValueError(f"Dashboard artifact errors for {signal_id}: {dashboard['errors']}")
        if len(evidence) < 3:
            raise ValueError(f"Insufficient evidence for {signal_id}: {len(evidence)}")
        path_sets = {
            tuple(result["companies"][company]["transmission_paths"])
            for company in COMPANY_ORDER
        }
        if len(path_sets) != len(COMPANY_ORDER):
            raise ValueError(f"Company transmission paths are not distinct for {signal_id}")
        summaries.append(
            {
                "signal_id": signal_id,
                "category": signal.category,
                "evidence_count": len(evidence),
                "company_count": len(result["companies"]),
                "retrieval_mode": debug["retrieval_mode"],
                "analysis_mode": result["metadata"]["analysis_mode"],
            }
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "index_document_count": index["document_count"],
                "signals": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
