"""
doc_intel/config.py – tuneable defaults for M1.

Import this module; never hard-code these values in logic files.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
# Pages with fewer than this many extractable characters trigger OCR.
OCR_MIN_CHARS_THRESHOLD: int = 30
# Never OCR beyond this many pages (performance guard).
OCR_MAX_PAGES: int = 40
# DPI for page pixmap rendering.
OCR_DPI: int = 200

# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------
# parse_confidence given to references that the regex splitter was uncertain about.
REF_LOW_CONFIDENCE: float = 0.40
# parse_confidence for LLM-enriched references (regex found boundary cleanly).
REF_HIGH_CONFIDENCE: float = 0.80
# Further reduce confidence when ref text came from OCR.
REF_OCR_CONFIDENCE_PENALTY: float = 0.20

# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------
# Minimum sentence length (chars) to be considered a claim candidate.
CLAIM_MIN_CHARS: int = 30
# How many sentences of context to include before/after a claim.
CONTEXT_SENTENCES: int = 1

# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------
# Temperature used for all LLM calls within M1.
LLM_TEMPERATURE: float = 0.0

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_ROOT: Path = Path(__file__).resolve().parents[4] / "data"
UPLOADS_DIR: Path = DATA_ROOT / "uploads"
