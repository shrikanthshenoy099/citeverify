"""
M2 – Text chunker.

Splits a list of PageText records into overlapping ~250-word chunks.
Chunks NEVER cross page boundaries (as required).
Each chunk carries page_index and section (None unless provided).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator

import pysbd

from .config import CHUNK_OVERLAP_WORDS, CHUNK_WORDS
from .pdf_handler import PageText

logger = logging.getLogger(__name__)

_segmenter = pysbd.Segmenter(language="en", clean=False)


@dataclass
class Chunk:
    chunk_id: str          # "{reference_id}_{page_index}_{chunk_index}"
    reference_id: str
    page_index: int        # 0-based
    text: str
    start_word: int        # offset within the page (informational)
    is_ocr: bool
    section: str | None = None


def _sentences(text: str) -> list[str]:
    """Split *text* into sentences using pysbd."""
    try:
        return _segmenter.segment(text)
    except Exception as exc:
        logger.warning("pysbd segmentation failed: %s", exc)
        return text.split(". ")


def _word_count(text: str) -> int:
    return len(text.split())


def _chunk_sentences(
    sentences: list[str],
    target_words: int,
    overlap_words: int,
) -> Iterator[tuple[list[str], int]]:
    """Yield (sentence_group, start_word_offset) with the given overlap.

    Parameters
    ----------
    sentences:
        Pre-split sentence list for one page.
    target_words:
        Approximate target size per chunk in words.
    overlap_words:
        How many words from the end of the previous chunk to include.
    """
    if not sentences:
        return

    current: list[str] = []
    current_words = 0
    carry: list[str] = []  # sentences to prepend from previous chunk
    carry_words = 0
    word_offset = 0

    for sent in sentences:
        sw = _word_count(sent)
        # If this single sentence exceeds the target, emit it alone.
        if not current and sw > target_words:
            yield [sent], word_offset
            word_offset += sw
            carry = []
            carry_words = 0
            continue

        current.append(sent)
        current_words += sw

        if current_words >= target_words:
            yield carry + current, word_offset
            # Build carry for next chunk: take sentences from the tail of current
            # until we have ~overlap_words
            new_carry: list[str] = []
            new_carry_words = 0
            for s in reversed(current):
                s_words = _word_count(s)
                if new_carry_words + s_words <= overlap_words:
                    new_carry.insert(0, s)
                    new_carry_words += s_words
                else:
                    break
            word_offset += current_words - new_carry_words
            carry = new_carry
            carry_words = new_carry_words
            current = []
            current_words = 0

    if current:
        yield carry + current, word_offset


def build_chunks(
    pages: list[PageText],
    reference_id: str,
    sections: dict[int, str] | None = None,
) -> list[Chunk]:
    """Convert page texts into overlapping chunks.

    Parameters
    ----------
    pages:
        Output of pdf_handler.extract_pages().
    reference_id:
        Used to construct chunk IDs.
    sections:
        Optional mapping page_index -> section name.
    """
    chunks: list[Chunk] = []
    for pt in pages:
        if not pt.text.strip():
            continue
        sentences = _sentences(pt.text)
        section = (sections or {}).get(pt.page_index)
        chunk_index = 0
        for sent_group, start_word in _chunk_sentences(sentences, CHUNK_WORDS, CHUNK_OVERLAP_WORDS):
            text = " ".join(sent_group)
            chunk = Chunk(
                chunk_id=f"{reference_id}_{pt.page_index}_{chunk_index}",
                reference_id=reference_id,
                page_index=pt.page_index,
                text=text,
                start_word=start_word,
                is_ocr=pt.is_ocr,
                section=section,
            )
            chunks.append(chunk)
            chunk_index += 1

    logger.debug("Built %d chunks for %s", len(chunks), reference_id)
    return chunks
