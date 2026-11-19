"""
demo_cache.py – Pre-fetch and index sources for the demo document's references.

Run ONCE before the demo (on good wifi) to avoid live network calls during the presentation:

    cd citeverify_repo
    python demo_cache.py

The script reads data/mock/sources.json to find reference_ids that have a known
DOI or URL, then calls retrieve_source() for each.  Results (PDFs and BM25 indexes)
are stored under data/sources/ and data/cache/ respectively.

Env required: CONTACT_EMAIL (set in .env).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap – allow running from the repo root directly
# ---------------------------------------------------------------------------
_REPO = Path(__file__).parent
sys.path.insert(0, str(_REPO / "backend"))

from citeverify_core.common.schemas import Reference
from citeverify_core.retrieval import retrieve_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo_cache")

# ---------------------------------------------------------------------------
# Demo references – edit this list to match your demo document's references.
# These are drawn from data/mock/sources.json for the default demo.
# ---------------------------------------------------------------------------
DEMO_REFERENCES: list[dict] = [
    {
        "reference_id": "demo_ref_vaswani2017",
        "raw_text": "Vaswani et al. (2017). Attention Is All You Need. NeurIPS.",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
        "doi": "10.5555/3295222.3295349",
        "venue": "NeurIPS",
        "parse_confidence": 0.95,
    },
    {
        "reference_id": "demo_ref_devlin2019",
        "raw_text": "Devlin et al. (2019). BERT. NAACL.",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang"],
        "year": 2019,
        "doi": "10.18653/v1/N19-1423",
        "venue": "NAACL",
        "parse_confidence": 0.92,
    },
    {
        "reference_id": "demo_ref_he2016",
        "raw_text": "He et al. (2016). Deep Residual Learning. CVPR.",
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He", "Xiangyu Zhang"],
        "year": 2016,
        "doi": "10.1109/CVPR.2016.90",
        "venue": "CVPR",
        "parse_confidence": 0.90,
    },
]


def run() -> None:
    total = len(DEMO_REFERENCES)
    succeeded = 0
    failed = 0

    logger.info("Starting demo cache pre-fetch for %d references.", total)

    for i, ref_dict in enumerate(DEMO_REFERENCES, 1):
        ref = Reference(**ref_dict)
        logger.info("[%d/%d] Fetching: %s", i, total, ref.title or ref.reference_id)
        t0 = time.perf_counter()
        try:
            source = retrieve_source(ref)
            elapsed = time.perf_counter() - t0
            status = "✓" if source.matched else "✗"
            logger.info(
                "  %s matched=%s text_level=%s flags=%s (%.1fs)",
                status, source.matched, source.text_level, source.flags, elapsed,
            )
            if source.matched:
                succeeded += 1
            else:
                failed += 1
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("  EXCEPTION for %s: %s (%.1fs)", ref.reference_id, exc, elapsed)
            failed += 1

    logger.info(
        "Done. %d/%d succeeded, %d failed.",
        succeeded, total, failed,
    )
    if failed:
        logger.warning(
            "%d reference(s) failed. The demo will fall back to metadata-only for those.",
            failed,
        )


if __name__ == "__main__":
    run()
