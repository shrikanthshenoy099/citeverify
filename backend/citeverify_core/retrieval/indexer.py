"""
M2 – Embedding index builder and loader.

Stores:
  data/cache/index/{reference_id}/embeddings.npy   – float32 array (N, D)
  data/cache/index/{reference_id}/metadata.json    – list of chunk dicts

Search: cosine similarity via numpy.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from .chunker import Chunk
from .config import EMBEDDING_MODEL, INDEX_DIR, TOP_K, LOW_RETRIEVAL_THRESHOLD

logger = logging.getLogger(__name__)

_model: "SentenceTransformer | None" = None


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for embedding. "
                "Install it with: pip install sentence-transformers"
            ) from exc
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _index_dir(reference_id: str) -> Path:
    p = INDEX_DIR / reference_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Build / save index
# ---------------------------------------------------------------------------

def build_index(chunks: list[Chunk], reference_id: str) -> None:
    """Embed all *chunks* and save index to disk.

    Overwrites any existing index for this reference.
    """
    if not chunks:
        logger.warning("No chunks provided for %s; index not built.", reference_id)
        return

    model = _get_model()
    texts = [c.text for c in chunks]
    logger.info("Embedding %d chunks for %s…", len(texts), reference_id)
    embeddings: np.ndarray = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    # Normalise for cosine similarity via dot product
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    embeddings = (embeddings / norms).astype(np.float32)

    idx_dir = _index_dir(reference_id)
    np.save(str(idx_dir / "embeddings.npy"), embeddings)

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
    (idx_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Index saved for %s (%d chunks, dim=%d)", reference_id, len(chunks), embeddings.shape[1])


# ---------------------------------------------------------------------------
# Load index
# ---------------------------------------------------------------------------

def load_index(reference_id: str) -> tuple[np.ndarray, list[dict]] | None:
    """Load embeddings array and metadata list for *reference_id*.

    Returns None if the index does not exist.
    """
    idx_dir = INDEX_DIR / reference_id
    emb_path = idx_dir / "embeddings.npy"
    meta_path = idx_dir / "metadata.json"
    if not emb_path.exists() or not meta_path.exists():
        return None
    embeddings = np.load(str(emb_path))
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    return embeddings, metadata


def index_exists(reference_id: str) -> bool:
    """Return True if a valid index exists for *reference_id*."""
    idx_dir = INDEX_DIR / reference_id
    return (idx_dir / "embeddings.npy").exists() and (idx_dir / "metadata.json").exists()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def cosine_search(
    reference_id: str,
    query: str,
    k: int = TOP_K,
) -> list[tuple[dict, float]]:
    """Return top-*k* (metadata_dict, score) pairs for *query*.

    Returns an empty list if the index is not built or the query fails.
    Low-retrieval flag determination is left to the caller.
    """
    index = load_index(reference_id)
    if index is None:
        logger.warning("No index found for %s", reference_id)
        return []

    embeddings, metadata = index
    model = _get_model()
    try:
        q_emb: np.ndarray = model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
        norm = np.linalg.norm(q_emb)
        if norm > 0:
            q_emb = q_emb / norm
        scores: np.ndarray = embeddings @ q_emb.astype(np.float32)
        top_indices = np.argsort(scores)[::-1][:k]
        return [(metadata[i], float(np.clip(scores[i], 0.0, 1.0))) for i in top_indices]
    except Exception as exc:
        logger.error("cosine_search failed for %s: %s", reference_id, exc)
        return []
