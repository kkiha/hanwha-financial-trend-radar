from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from rag_finance.ingestion.demo_corpus import load_demo_corpus


INDEX_VERSION = 1
TOKEN_PATTERN = re.compile(r"[a-z]+(?:\d+[a-z]*)?|\d+(?:\.\d+)?|[가-힣]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text or "")]


def build_demo_index(corpus_dir: str | Path, index_path: str | Path) -> dict[str, Any]:
    documents = load_demo_corpus(corpus_dir)
    indexed_documents: list[dict[str, Any]] = []
    for document in documents:
        payload = document.to_dict()
        tokens = tokenize(" ".join((document.title, document.content)))
        payload["term_frequencies"] = dict(Counter(tokens))
        payload["document_length"] = len(tokens)
        indexed_documents.append(payload)

    index = {
        "index_version": INDEX_VERSION,
        "index_type": "snapshot_bm25_rrf",
        "data_mode": "demo_snapshot",
        "source_corpus": str(Path(corpus_dir).as_posix()),
        "document_count": len(indexed_documents),
        "documents": indexed_documents,
    }
    destination = Path(index_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_demo_index(index_path: str | Path) -> dict[str, Any]:
    path = Path(index_path)
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Demo index not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid demo index JSON: {path}: {exc}") from exc
    if index.get("index_version") != INDEX_VERSION:
        raise ValueError(f"Unsupported demo index version: {index.get('index_version')}")
    if index.get("data_mode") != "demo_snapshot":
        raise ValueError("Demo index must declare data_mode=demo_snapshot")
    if not isinstance(index.get("documents"), list) or not index["documents"]:
        raise ValueError("Demo index contains no documents")
    return index
