from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_finance.retrieval.demo_index import build_demo_index


def _load_config(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the deterministic Snapshot BM25/RRF demo index")
    parser.add_argument("--config", default="configs/trend_demo.yaml")
    args = parser.parse_args()
    config = _load_config(args.config)
    paths = config["paths"]
    index = build_demo_index(paths["demo_corpus_dir"], paths["demo_index_path"])
    print(
        f"[build_demo_index] type={index['index_type']} "
        f"documents={index['document_count']} path={paths['demo_index_path']}"
    )


if __name__ == "__main__":
    main()
