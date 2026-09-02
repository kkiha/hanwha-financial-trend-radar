from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SnapshotDocument:
    document_id: str
    title: str
    source: str
    published_at: str
    url: str
    category: str
    data_mode: str
    snapshot_notice: str
    content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path) -> "SnapshotDocument":
        required = (
            "document_id", "title", "source", "published_at", "url",
            "category", "data_mode", "snapshot_notice", "content",
        )
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            raise ValueError(f"Missing fields {missing} in demo document: {path}")
        if data["data_mode"] != "demo_snapshot":
            raise ValueError(f"Demo document must declare data_mode=demo_snapshot: {path}")
        return cls(**{key: str(data[key]).strip() for key in required})

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def load_demo_corpus(root: str | Path, category: str | None = None) -> list[SnapshotDocument]:
    corpus_root = Path(root)
    search_root = corpus_root / category if category else corpus_root
    if not search_root.is_dir():
        raise FileNotFoundError(f"Demo corpus directory not found: {search_root}")

    documents: list[SnapshotDocument] = []
    seen_ids: set[str] = set()
    for path in sorted(search_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid demo document JSON: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Demo document must be a JSON object: {path}")
        document = SnapshotDocument.from_dict(payload, path)
        if category and document.category != category:
            continue
        if document.document_id in seen_ids:
            raise ValueError(f"Duplicate document_id: {document.document_id}")
        seen_ids.add(document.document_id)
        documents.append(document)

    if not documents:
        raise ValueError(f"No demo documents found under: {search_root}")
    return documents
