from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rag_finance.llm.trend_analyzer import analyze_trend
from rag_finance.profiles.loader import load_company_profiles
from rag_finance.retrieval.demo_index import build_demo_index
from rag_finance.retrieval.trend_pipeline import retrieve_trend_evidence
from rag_finance.signal.loader import load_signal


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_config(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Snapshot signal through the Trend Radar pipeline")
    parser.add_argument("--config", default="configs/trend_demo.yaml")
    parser.add_argument("--signal", default="data/sample_signals/us10y_drop.json")
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--rebuild-index", action="store_true")
    args = parser.parse_args()

    config = _load_config(args.config)
    paths = config["paths"]
    retrieval_config = config["retrieval"]
    llm_config = config["llm"]
    signal = load_signal(args.signal)

    index_path = Path(paths["demo_index_path"])
    if args.rebuild_index or not index_path.is_file():
        build_demo_index(paths["demo_corpus_dir"], index_path)

    evidence_snapshot = signal.evidence_snapshot or str(
        Path(paths["demo_evidence_dir"]) / f"{signal.signal_id.lower()}_evidence.json"
    )
    evidence, retrieval_debug = retrieve_trend_evidence(
        signal,
        index_path=index_path,
        keyword_dir=paths["trend_keywords_dir"],
        evidence_snapshot_path=evidence_snapshot,
        topk=int(retrieval_config.get("topk", 5)),
        rrf_k_const=int(retrieval_config.get("rrf_k_const", 60)),
        bm25_k1=float(retrieval_config.get("bm25_k1", 1.5)),
        bm25_b=float(retrieval_config.get("bm25_b", 0.75)),
    )
    profiles = load_company_profiles(paths["profiles_dir"])
    demo_mode = _is_true(os.environ.get("DEMO_MODE", "true"))
    cache_path = signal.cached_output or str(
        Path(paths["demo_outputs_dir"]) / f"{signal.signal_id.lower()}_analysis.json"
    )
    result = analyze_trend(
        signal,
        evidence,
        profiles,
        demo_mode=demo_mode,
        cache_path=cache_path,
        model=llm_config["model"],
        temperature=float(llm_config.get("temperature", 0.1)),
        max_tokens=int(llm_config.get("max_tokens", 1400)),
    )
    result["metadata"]["retrieval"] = retrieval_debug
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
