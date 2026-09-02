from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rag_finance.entities.trend_maps import build_trend_queries, load_trend_keywords
from rag_finance.retrieval.demo_index import load_demo_index, tokenize
from rag_finance.retrieval.rrf import rrf_fusion
from rag_finance.signal.schema import Evidence, Signal


def _bm25_scores(
    documents: list[dict[str, Any]],
    query: str,
    *,
    k1: float,
    b: float,
) -> list[float]:
    query_terms = list(dict.fromkeys(tokenize(query)))
    count = len(documents)
    avg_length = sum(int(doc.get("document_length", 0)) for doc in documents) / max(count, 1)
    document_frequency = {
        term: sum(1 for doc in documents if term in doc.get("term_frequencies", {}))
        for term in query_terms
    }
    scores: list[float] = []
    for document in documents:
        frequencies = document.get("term_frequencies", {})
        length = int(document.get("document_length", 0))
        score = 0.0
        for term in query_terms:
            frequency = int(frequencies.get(term, 0))
            if frequency <= 0:
                continue
            df = document_frequency[term]
            idf = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1.0 - b + b * length / max(avg_length, 1.0))
            score += idf * frequency * (k1 + 1.0) / denominator
        scores.append(score)
    return scores


def _keyword_scores(documents: list[dict[str, Any]], keywords: list[str]) -> list[float]:
    lowered_keywords = [keyword.lower() for keyword in keywords if keyword]
    scores: list[float] = []
    for document in documents:
        text = f"{document.get('title', '')} {document.get('content', '')}".lower()
        scores.append(float(sum(1 for keyword in lowered_keywords if keyword in text)))
    return scores


def _rank_map(documents: list[dict[str, Any]], scores: list[float]) -> dict[tuple[str, str], int]:
    order = sorted(range(len(documents)), key=lambda idx: (-scores[idx], documents[idx]["document_id"]))
    return {
        (documents[idx]["document_id"], "0"): rank
        for rank, idx in enumerate(order)
        if scores[idx] > 0
    }


def _load_evidence_overrides(path: str | Path | None, signal_id: str) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    evidence_path = Path(path)
    if not evidence_path.is_file():
        return {}
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if payload.get("signal_id") != signal_id:
        raise ValueError(f"Evidence snapshot signal mismatch: {evidence_path}")
    if payload.get("data_mode") != "demo_snapshot":
        raise ValueError(f"Evidence snapshot must declare data_mode=demo_snapshot: {evidence_path}")
    return {
        item["document_id"]: item
        for item in payload.get("evidence", [])
        if isinstance(item, dict) and item.get("document_id")
    }


def retrieve_trend_evidence(
    signal: Signal,
    *,
    index_path: str | Path,
    keyword_dir: str | Path,
    evidence_snapshot_path: str | Path | None = None,
    topk: int = 5,
    rrf_k_const: int = 60,
    bm25_k1: float = 1.5,
    bm25_b: float = 0.75,
) -> tuple[list[Evidence], dict[str, Any]]:
    """Retrieve snapshot evidence without company extraction or entity filtering."""
    index = load_demo_index(index_path)
    category_documents = [
        document for document in index["documents"] if document.get("category") == signal.category
    ]
    if not category_documents:
        return [], {"note": "no documents for category", "category": signal.category}

    keyword_map = load_trend_keywords(keyword_dir, signal.category)
    bm25_query, soft_query = build_trend_queries(signal, keyword_map)
    bm25_scores = _bm25_scores(category_documents, bm25_query, k1=bm25_k1, b=bm25_b)
    keyword_scores = _keyword_scores(
        category_documents,
        keyword_map["hard_keywords"] + keyword_map["soft_keywords"] + tokenize(soft_query),
    )
    ranks = {
        "bm25": _rank_map(category_documents, bm25_scores),
        "trend_keywords": _rank_map(category_documents, keyword_scores),
    }
    fused = rrf_fusion(ranks, k_const=rrf_k_const)
    ordered = sorted(
        range(len(category_documents)),
        key=lambda idx: (
            -fused.get((category_documents[idx]["document_id"], "0"), 0.0),
            -bm25_scores[idx],
            category_documents[idx]["document_id"],
        ),
    )
    overrides = _load_evidence_overrides(evidence_snapshot_path, signal.signal_id)

    evidence: list[Evidence] = []
    for idx in ordered:
        document = category_documents[idx]
        key = (document["document_id"], "0")
        score = fused.get(key, 0.0)
        if score <= 0:
            continue
        override = overrides.get(document["document_id"], {})
        content = str(document.get("content", "")).strip()
        excerpt = str(override.get("excerpt") or content[:360]).strip()
        evidence.append(
            Evidence(
                document_id=document["document_id"],
                title=str(override.get("title") or document["title"]),
                source=str(override.get("source") or document["source"]),
                date=str(override.get("date") or document["published_at"]),
                url=str(override.get("url") or document["url"]),
                excerpt=excerpt,
                category=document["category"],
                data_mode=document["data_mode"],
                score=round(score, 8),
            )
        )
        if len(evidence) >= topk:
            break

    debug = {
        "retrieval_mode": "snapshot_bm25_rrf",
        "company_filter_applied": False,
        "category": signal.category,
        "corpus_candidates": len(category_documents),
        "returned": len(evidence),
        "hard_keywords": keyword_map["hard_keywords"],
        "soft_keywords": keyword_map["soft_keywords"],
        "index_path": str(index_path),
    }
    return evidence, debug
