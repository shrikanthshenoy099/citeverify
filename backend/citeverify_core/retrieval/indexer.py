"""
M2 – BM25 index builder and searcher.

Storage layout (unchanged from cosine version; M3 / M4 see the same interface):
  data/cache/index/{reference_id}/bm25_corpus.json  – tokenised corpus list
  data/cache/index/{reference_id}/metadata.json     – list of chunk dicts

Search: BM25Okapi from rank-bm25.

## Score scale (important for M3)
BM25 raw scores are non-negative floats with **no fixed upper bound** – they depend
on corpus size, term frequency, document length, and k1/b parameters.  Raw scores
are NOT 0-1 cosine similarities.

Normalisation applied here:
  score_norm = raw_score / (raw_score + 1)   [hyperbolic normalisation]

This maps [0, +inf) monotonically into [0, 1) with the following properties:
  - Score 0  → 0.0  (no term overlap at all)
  - Score 1  → 0.5
  - Score 10 → 0.91
  - Score ∞  → 1.0  (theoretical limit, never reached)

A passage with score_norm < 0.35 (LOW_RETRIEVAL_THRESHOLD) means very weak BM25
match – typically fewer than 2–3 overlapping content words.  M3 should treat
this the same as a low cosine score and add the ``low_retrieval_score`` flag.

The embeddings.npy file is NOT written by this implementation.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

from .chunker import Chunk
from .config import INDEX_DIR, LOW_RETRIEVAL_THRESHOLD, TOP_K

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> list[str]:
    """Lower-case, split on non-alphanumeric, return non-empty tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


# ---------------------------------------------------------------------------
# Directory helper
# ---------------------------------------------------------------------------

def _index_dir(reference_id: str) -> Path:
    p = INDEX_DIR / reference_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Build / save index
# ---------------------------------------------------------------------------

def build_index(chunks: list[Chunk], reference_id: str) -> None:
    """Tokenise all *chunks* and save BM25 corpus to disk.

    Overwrites any existing index for this reference.
    """
    if not chunks:
        logger.warning("No chunks provided for %s; index not built.", reference_id)
        return

    idx_dir = _index_dir(reference_id)

    corpus = [_tokenise(c.text) for c in chunks]
    (idx_dir / "bm25_corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False), encoding="utf-8"
    )

    metadata = [
        {
            "chunk_id": c.chunk_id,
            "reference_id": c.reference_id,
            "page_index": c.page_index,
            "text": c.text,
            "is_ocr": c.is_ocr,
            "section": c.section,
        }
        for c in chunks
    ]
    (idx_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("BM25 index saved for %s (%d chunks)", reference_id, len(chunks))


# ---------------------------------------------------------------------------
# Load index
# ---------------------------------------------------------------------------

def load_index(reference_id: str) -> tuple[list[list[str]], list[dict]] | None:
    """Load tokenised corpus and metadata for *reference_id*.

    Returns None if the index does not exist.
    """
    idx_dir = INDEX_DIR / reference_id
    corpus_path = idx_dir / "bm25_corpus.json"
    meta_path = idx_dir / "metadata.json"
    if not corpus_path.exists() or not meta_path.exists():
        return None
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    return corpus, metadata


def index_exists(reference_id: str) -> bool:
    """Return True if a valid BM25 index exists for *reference_id*."""
    idx_dir = INDEX_DIR / reference_id
    return (idx_dir / "bm25_corpus.json").exists() and (idx_dir / "metadata.json").exists()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _normalise_score(raw: float) -> float:
    """Map BM25 raw score [0, +inf) to [0, 1) via hyperbolic normalisation.

    score_norm = raw / (raw + 1)

    This is monotone, so ranking is preserved.  See module docstring for
    the mapping table and what the threshold 0.35 means in practice.
    """
    return raw / (raw + 1.0) if raw > 0 else 0.0


def cosine_search(
    reference_id: str,
    query: str,
    k: int = TOP_K,
) -> list[tuple[dict, float]]:
    """Return top-*k* (metadata_dict, score_norm) pairs for *query*.

    ``score_norm`` is the hyperbolic-normalised BM25 score in [0, 1).
    Returns an empty list if the index is not built or the query fails.
    """
    index = load_index(reference_id)
    if index is None:
        logger.warning("No BM25 index found for %s", reference_id)
        return []

    corpus, metadata = index
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise ImportError(
            "rank-bm25 is required for passage search. "
            "Install it with: pip install rank-bm25"
        ) from exc

    try:
        bm25 = BM25Okapi(corpus)
        query_tokens = _tokenise(query)
        if not query_tokens:
            # Degenerate query – return first k chunks at score 0
            return [(metadata[i], 0.0) for i in range(min(k, len(metadata)))]
        raw_scores: list[float] = bm25.get_scores(query_tokens).tolist()
        # Sort by raw score descending, take top-k
        top_indices = sorted(range(len(raw_scores)), key=lambda i: raw_scores[i], reverse=True)[:k]
        return [(metadata[i], _normalise_score(raw_scores[i])) for i in top_indices]
    except Exception as exc:
        logger.error("BM25 search failed for %s: %s", reference_id, exc)
        return []
