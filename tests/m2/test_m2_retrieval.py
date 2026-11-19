"""
M2 – pytest test suite for backend/citeverify_core/retrieval/.

Run from the repo root:
    pytest tests/m2/ -v

No network calls – everything is mocked or runs fully offline.
pyproject.toml sets pythonpath = ["backend"], so no manual sys.path needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup – fallback for editors that run this file directly.
# pytest finds the backend via pyproject.toml pythonpath = ["backend"].
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent  # tests/m2/../../  = repo root
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from citeverify_core.common.schemas import (
    BBox,
    Evidence,
    Passage,
    Reference,
    Source,
)
from citeverify_core.retrieval.chunker import Chunk, build_chunks
from citeverify_core.retrieval.fetchers import (
    arxiv_normalize,
    crossref_normalize,
    openalex_normalize,
    s2_normalize,
    unpaywall_pdf_url,
)
from citeverify_core.retrieval.matcher import (
    author_matches,
    is_matched,
    title_ratio,
    year_matches,
)
from citeverify_core.retrieval.pdf_handler import PageText, _is_valid_pdf


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture()
def sample_reference() -> Reference:
    return Reference(
        reference_id="ref_001",
        raw_text="Vaswani et al. (2017) Attention is all you need.",
        title="Attention is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        doi="10.5555/3295222.3295349",
        venue="NeurIPS",
        parse_confidence=0.95,
    )


@pytest.fixture()
def tmp_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect INDEX_DIR, SOURCES_DIR to tmp_path."""
    monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr("citeverify_core.retrieval.passage_search.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr("citeverify_core.retrieval.config.SOURCES_DIR", tmp_path / "sources")
    return tmp_path


# ===========================================================================
# 1. Matcher tests
# ===========================================================================

class TestMatcher:
    def test_exact_title_ratio(self):
        r = title_ratio("Attention is All You Need", "Attention is All You Need")
        assert r == 100.0

    def test_title_ratio_case_insensitive(self):
        r = title_ratio("BERT: Pre-training", "bert pre training")
        assert r >= 85

    def test_title_ratio_different_titles(self):
        r = title_ratio("Attention is All You Need", "Deep Learning for NLP")
        assert r < 50

    def test_year_matches_exact(self):
        assert year_matches(2017, 2017) is True

    def test_year_matches_tolerance(self):
        assert year_matches(2017, 2018) is True
        assert year_matches(2017, 2016) is True

    def test_year_outside_tolerance(self):
        assert year_matches(2010, 2017) is False

    def test_year_none(self):
        assert year_matches(None, 2017) is False
        assert year_matches(2017, None) is False

    def test_author_matches_first_surname(self):
        assert author_matches(["Vaswani, Ashish"], ["Ashish Vaswani"]) is True

    def test_author_no_match(self):
        assert author_matches(["LeCun, Yann"], ["Ashish Vaswani"]) is False

    def test_is_matched_full(self, sample_reference: Reference):
        matched, score = is_matched(
            sample_reference,
            "Attention is All You Need",
            ["Ashish Vaswani"],
            2017,
        )
        assert matched is True
        assert score >= 0.85

    def test_is_matched_title_only_above_92(self, sample_reference: Reference):
        matched, score = is_matched(
            sample_reference,
            "Attention is All You Need",
            [],
            None,
        )
        assert matched is True

    def test_is_matched_low_ratio(self, sample_reference: Reference):
        matched, _ = is_matched(
            sample_reference,
            "Deep Residual Learning for Image Recognition",
            [],
            2017,
        )
        assert matched is False

    def test_is_matched_no_title(self, sample_reference: Reference):
        ref = sample_reference.model_copy(update={"title": None})
        matched, score = is_matched(ref, "Attention is All You Need", [], 2017)
        assert matched is False
        assert score == 0.0


# ===========================================================================
# 2. Fetcher normalisation tests (offline – work with static dicts)
# ===========================================================================

class TestFetcherNormalisers:
    def test_crossref_normalize(self):
        work = {
            "title": ["Attention is All You Need"],
            "author": [
                {"given": "Ashish", "family": "Vaswani"},
                {"given": "Noam", "family": "Shazeer"},
            ],
            "published": {"date-parts": [[2017, 12, 4]]},
            "DOI": "10.5555/3295222.3295349",
            "container-title": ["Advances in Neural Information Processing Systems"],
        }
        m = crossref_normalize(work)
        assert m["title"] == "Attention is All You Need"
        assert "Ashish Vaswani" in m["authors"]
        assert m["year"] == 2017
        assert m["doi"] == "10.5555/3295222.3295349"
        assert m["source_database"] == "crossref"

    def test_crossref_normalize_missing_fields(self):
        work: dict[str, Any] = {}
        m = crossref_normalize(work)
        assert m["title"] == ""
        assert m["authors"] == []
        assert m["year"] is None

    def test_openalex_normalize(self):
        work = {
            "title": "Attention is All You Need",
            "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
            "publication_year": 2017,
            "doi": "https://doi.org/10.5555/3295222.3295349",
            "open_access": {"oa_url": "https://arxiv.org/pdf/1706.03762.pdf"},
        }
        m = openalex_normalize(work)
        assert m["doi"] == "10.5555/3295222.3295349"
        assert m["url"] == "https://arxiv.org/pdf/1706.03762.pdf"
        assert m["source_database"] == "openalex"

    def test_arxiv_normalize(self):
        import xml.etree.ElementTree as ET
        xml_str = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/1706.03762v5</id>
            <title>Attention Is All You Need</title>
            <published>2017-06-12T00:00:00Z</published>
            <author><name>Ashish Vaswani</name></author>
            <link type="application/pdf" href="https://arxiv.org/pdf/1706.03762v5"/>
          </entry>
        </feed>"""
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_str)
        entry = root.findall("atom:entry", ns)[0]
        raw = {"_entry": entry, "_ns": ns}
        m = arxiv_normalize(raw)
        assert "Attention" in m["title"]
        assert m["year"] == 2017
        assert "Ashish Vaswani" in m["authors"]
        assert m["url"] is not None
        assert m["source_database"] == "arxiv"

    def test_s2_normalize(self):
        work = {
            "title": "Attention is All You Need",
            "authors": [{"name": "Ashish Vaswani"}],
            "year": 2017,
            "externalIds": {"DOI": "10.5555/3295222.3295349"},
            "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
            "venue": "NeurIPS",
        }
        m = s2_normalize(work)
        assert m["doi"] == "10.5555/3295222.3295349"
        assert m["source_database"] == "semantic_scholar"

    def test_unpaywall_pdf_url_best_location(self):
        record = {
            "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf", "url": None}
        }
        assert unpaywall_pdf_url(record) == "https://example.com/paper.pdf"

    def test_unpaywall_pdf_url_fallback(self):
        record = {
            "best_oa_location": None,
            "oa_locations": [{"url_for_pdf": "https://example.com/paper2.pdf"}],
        }
        assert unpaywall_pdf_url(record) == "https://example.com/paper2.pdf"

    def test_unpaywall_pdf_url_none(self):
        assert unpaywall_pdf_url({}) is None


# ===========================================================================
# 3. Chunker tests
# ===========================================================================

class TestChunker:
    def _make_pages(self, texts: list[str]) -> list[PageText]:
        return [PageText(page_index=i, text=t, is_ocr=False) for i, t in enumerate(texts)]

    def test_basic_chunking(self):
        words = ["word"] * 300
        text = " ".join(words)
        pages = self._make_pages([text])
        chunks = build_chunks(pages, "ref_test")
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c.text.split()) <= 350

    def test_no_cross_page(self):
        pages = self._make_pages(["Word " * 300, "Other " * 300])
        chunks = build_chunks(pages, "ref_test")
        page_0_chunks = [c for c in chunks if c.page_index == 0]
        page_1_chunks = [c for c in chunks if c.page_index == 1]
        assert len(page_0_chunks) >= 1
        assert len(page_1_chunks) >= 1
        for c in page_0_chunks:
            assert "Other" not in c.text
        for c in page_1_chunks:
            assert "Word" not in c.text

    def test_empty_pages_skipped(self):
        pages = self._make_pages(["", "   ", "Real content here with some words."])
        chunks = build_chunks(pages, "ref_test")
        assert len(chunks) >= 1
        for c in chunks:
            assert c.text.strip()

    def test_chunk_ids_unique(self):
        pages = self._make_pages(["Word " * 300, "Other " * 300])
        chunks = build_chunks(pages, "ref_xyz")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_contains_reference_id(self):
        pages = self._make_pages(["Hello world. " * 50])
        chunks = build_chunks(pages, "myref")
        for c in chunks:
            assert c.reference_id == "myref"

    def test_ocr_flag_propagated(self):
        pages = [PageText(page_index=0, text="Some text " * 50, is_ocr=True)]
        chunks = build_chunks(pages, "ref_ocr")
        assert all(c.is_ocr for c in chunks)

    def test_overlap_produces_duplicate_words(self):
        words = " ".join([f"word{i}" for i in range(600)])
        pages = self._make_pages([words])
        chunks = build_chunks(pages, "ref_overlap")
        if len(chunks) >= 2:
            end_words = set(chunks[0].text.split()[-20:])
            start_words = set(chunks[1].text.split()[:20])
            assert end_words & start_words, "Expected some word overlap between consecutive chunks"


# ===========================================================================
# 4. BM25 Indexer tests (no model needed)
# ===========================================================================

class TestIndexer:
    def _build(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref_id: str, texts: list[str]) -> list[Chunk]:
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        chunks = [Chunk(f"{ref_id}_0_{i}", ref_id, 0, t, 0, False) for i, t in enumerate(texts)]
        indexer.build_index(chunks, ref_id)
        return chunks

    def test_build_and_load_index(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        chunks = [
            Chunk("ref1_0_0", "ref1", 0, "The quick brown fox jumps over the lazy dog.", 0, False),
            Chunk("ref1_0_1", "ref1", 0, "Machine learning is a subset of artificial intelligence.", 0, False),
        ]
        indexer.build_index(chunks, "ref1")
        result = indexer.load_index("ref1")
        assert result is not None
        corpus, metadata = result
        assert len(corpus) == 2
        assert len(metadata) == 2
        assert metadata[0]["chunk_id"] == "ref1_0_0"

    def test_bm25_search_returns_top_k(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.passage_search.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        chunks = [
            Chunk(f"ref2_0_{i}", "ref2", 0, f"Text chunk number {i} about topic.", 0, False)
            for i in range(10)
        ]
        indexer.build_index(chunks, "ref2")
        results = indexer.cosine_search("ref2", "text chunk topic", k=3)
        assert len(results) <= 3
        # cosine_search now returns RAW BM25 scores (unbounded non-negative floats)
        for meta, score in results:
            assert score >= 0.0

    def test_bm25_score_scale_documented(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verify per-query max normalisation in search_passages.

        cosine_search returns raw BM25 scores.
        search_passages normalises per-query: score / max_score_in_query → [0, 1].
        The best-matching passage always scores 1.0.
        """
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.passage_search.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        from citeverify_core.retrieval.passage_search import search_passages

        # Build a larger corpus so IDF > 0 for query terms
        chunks = [
            Chunk("sc_0", "sc", 0, "neural network deep learning gradient descent optimizer training", 0, False),
            Chunk("sc_1", "sc", 0, "banana apple orange fruit salad kitchen recipe cooking", 0, False),
            Chunk("sc_2", "sc", 0, "database sql query table row column index transaction", 0, False),
            Chunk("sc_3", "sc", 0, "music piano violin guitar symphony orchestra concert hall", 0, False),
            Chunk("sc_4", "sc", 0, "ocean wave beach sand coral reef tide current", 0, False),
        ]
        indexer.build_index(chunks, "sc")

        # Raw scores from cosine_search are unbounded; sc_0 must rank first
        raw_results = indexer.cosine_search("sc", "neural network deep learning", k=5)
        raw_scores = {m["chunk_id"]: s for m, s in raw_results}
        assert raw_scores["sc_0"] > 0.0, "sc_0 should have a positive raw score"
        assert raw_scores["sc_0"] > raw_scores.get("sc_1", 0.0), "Neural chunk must outscore fruit chunk"

        # search_passages applies per-query normalisation: best passage = 1.0
        passages = search_passages("sc", "neural network deep learning", k=5)
        assert len(passages) >= 1
        # The top passage must be normalised to 1.0
        assert passages[0].score == 1.0, f"Top passage should be 1.0, got {passages[0].score}"
        # All normalised scores must be in [0, 1]
        for p in passages:
            assert 0.0 <= p.score <= 1.0

        # _normalise_score unit test: raw / max_raw
        from citeverify_core.retrieval.indexer import _normalise_score
        assert _normalise_score(0.0, max_raw=5.0) == 0.0
        assert _normalise_score(5.0, max_raw=5.0) == 1.0
        assert _normalise_score(2.5, max_raw=5.0) == 0.5
        assert _normalise_score(0.0, max_raw=0.0) == 0.0  # degenerate

    def test_index_not_found_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        result = indexer.load_index("nonexistent_ref")
        assert result is None

    def test_index_exists_false_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        assert indexer.index_exists("missing_ref") is False


# ===========================================================================
# 5. passage_search.search_passages
# ===========================================================================

class TestSearchPassages:
    def _build_index(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref_id: str, texts: list[str]):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.passage_search.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import indexer
        chunks = [Chunk(f"{ref_id}_0_{i}", ref_id, 0, t, 0, False) for i, t in enumerate(texts)]
        indexer.build_index(chunks, ref_id)

    def test_returns_passages_up_to_k(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self._build_index(tmp_path, monkeypatch, "refA", [f"Machine learning chunk {i}" for i in range(10)])
        from citeverify_core.retrieval.passage_search import search_passages
        passages = search_passages("refA", "machine learning", k=3)
        assert len(passages) <= 3
        for p in passages:
            assert isinstance(p, Passage)
            assert p.reference_id == "refA"

    def test_no_index_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.passage_search.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval.passage_search import search_passages
        result = search_passages("ref_missing", "query")
        assert result == []

    def test_passage_scores_clamped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self._build_index(tmp_path, monkeypatch, "refB", ["Alpha beta gamma", "Delta epsilon zeta", "Eta theta iota"])
        from citeverify_core.retrieval.passage_search import search_passages
        for p in search_passages("refB", "alpha query", k=5):
            assert 0.0 <= p.score <= 1.0

    def test_numeric_query_ranked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A chunk containing '30%' should outscore one that doesn't, for a '30%' query."""
        texts = [
            "The model achieved 30% improvement over the baseline in accuracy.",
            "This paper discusses transformer architectures and self-attention mechanisms.",
            "Dataset collection and annotation methodology are described in this section.",
        ]
        self._build_index(tmp_path, monkeypatch, "refNum", texts)
        from citeverify_core.retrieval.passage_search import search_passages
        passages = search_passages("refNum", "30% improvement accuracy", k=5)
        assert len(passages) >= 1
        # The passage with "30" and "improvement" and "accuracy" should rank first
        assert "30" in passages[0].text or "improvement" in passages[0].text.lower()


# ===========================================================================
# 6. Retraction check
# ===========================================================================

class TestRetraction:
    def test_retracted_via_update_to(self):
        from citeverify_core.retrieval.retraction import _is_retracted
        work = {"update-to": [{"type": "retraction", "DOI": "10.xxx/retract"}]}
        assert _is_retracted(work) is True

    def test_retracted_via_relation(self):
        from citeverify_core.retrieval.retraction import _is_retracted
        work = {"relation": {"is-retracted-by": [{"id": "10.xxx/notice"}]}}
        assert _is_retracted(work) is True

    def test_no_retraction(self):
        from citeverify_core.retrieval.retraction import _is_retracted
        work = {"update-to": [{"type": "correction"}], "relation": {}}
        assert _is_retracted(work) is False

    def test_empty_work(self):
        from citeverify_core.retrieval.retraction import _is_retracted
        assert _is_retracted({}) is False

    def test_check_retraction_no_doi(self):
        from citeverify_core.retrieval.retraction import check_retraction
        source = Source(reference_id="r1", matched=True, match_score=0.9, title="Paper",
                        text_level="full_text", full_text_available=True, source_database="crossref")
        result = check_retraction(source)
        assert "possibly_retracted" not in result.flags

    def test_check_retraction_adds_flag(self, monkeypatch: pytest.MonkeyPatch):
        from citeverify_core.retrieval import retraction as ret_mod
        retracted_work = {"update-to": [{"type": "retraction", "DOI": "10.xxx/notice"}]}
        monkeypatch.setattr(ret_mod, "crossref_by_doi", lambda doi: retracted_work)
        source = Source(reference_id="r2", matched=True, match_score=0.9, title="Paper",
                        doi="10.xxx/paper", text_level="full_text", full_text_available=True,
                        source_database="crossref")
        result = ret_mod.check_retraction(source)
        assert "possibly_retracted" in result.flags


# ===========================================================================
# 7. ingest_pdf
# ===========================================================================

class TestIngestPdf:
    def test_ingest_pdf_full_text(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import ingest as ingest_mod
        fake_pages = [PageText(0, "Deep learning is a type of machine learning. " * 30, False)]
        monkeypatch.setattr(ingest_mod, "extract_pages", lambda path, ref_id: fake_pages)
        pdf_path = tmp_path / "paper.pdf"
        pdf_path.touch()
        source = ingest_mod.ingest_pdf("ref_manual", str(pdf_path))
        assert source.reference_id == "ref_manual"
        assert source.matched is True
        assert source.text_level == "full_text"
        assert source.full_text_available is True
        assert "manual_source" in source.flags
        assert "ocr_text" not in source.flags

    def test_ingest_pdf_ocr_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("citeverify_core.retrieval.indexer.INDEX_DIR", tmp_path / "index")
        monkeypatch.setattr("citeverify_core.retrieval.config.INDEX_DIR", tmp_path / "index")
        from citeverify_core.retrieval import ingest as ingest_mod
        fake_pages = [PageText(0, "Some OCR text. " * 30, is_ocr=True)]
        monkeypatch.setattr(ingest_mod, "extract_pages", lambda path, ref_id: fake_pages)
        pdf_path = tmp_path / "ocr.pdf"
        pdf_path.touch()
        source = ingest_mod.ingest_pdf("ref_ocr", str(pdf_path))
        assert "manual_source" in source.flags
        assert "ocr_text" in source.flags

    def test_ingest_pdf_missing_file(self, tmp_path: Path):
        from citeverify_core.retrieval.ingest import ingest_pdf
        with pytest.raises(FileNotFoundError):
            ingest_pdf("ref_missing", str(tmp_path / "nonexistent.pdf"))

    def test_ingest_pdf_no_text_gives_none_level(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from citeverify_core.retrieval import ingest as ingest_mod
        monkeypatch.setattr(ingest_mod, "extract_pages", lambda path, ref_id: [])
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.touch()
        source = ingest_mod.ingest_pdf("ref_empty", str(pdf_path))
        assert source.text_level == "none"
        assert source.full_text_available is False


# ===========================================================================
# 8. Schema contract tests
# ===========================================================================

class TestSchemas:
    def test_reference_roundtrip(self, sample_reference: Reference):
        d = sample_reference.model_dump()
        r2 = Reference.model_validate(d)
        assert r2.reference_id == sample_reference.reference_id

    def test_source_text_level_validation(self):
        with pytest.raises(Exception):
            Source(reference_id="x", matched=True, match_score=0.5,
                   title="T", text_level="invalid_level",  # type: ignore
                   full_text_available=False, source_database="crossref")

    def test_passage_score_clamped_to_zero_one(self):
        with pytest.raises(Exception):
            Passage(passage_id="p1", reference_id="r1", text="text", score=1.5)

    def test_evidence_empty_bboxes(self):
        e = Evidence(quote="some text", passage_id="p1")
        assert e.bboxes == []
        assert e.page is None

    def test_bbox_fields(self):
        b = BBox(x0=10.0, y0=20.0, x1=100.0, y1=50.0)
        assert b.x0 == 10.0
        assert b.y1 == 50.0


# ===========================================================================
# 9. get_pdf_path
# ===========================================================================

class TestGetPdfPath:
    def test_returns_none_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import citeverify_core.retrieval as ret_pkg
        monkeypatch.setattr(ret_pkg, "SOURCES_DIR", tmp_path / "sources")
        from citeverify_core.retrieval import get_pdf_path
        assert get_pdf_path("nonexistent") is None

    def test_returns_path_for_valid_pdf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        import citeverify_core.retrieval as ret_pkg
        monkeypatch.setattr(ret_pkg, "SOURCES_DIR", sources_dir)
        pdf = sources_dir / "ref_pdf.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        from citeverify_core.retrieval import get_pdf_path
        result = get_pdf_path("ref_pdf")
        assert result is not None
        assert result.endswith("ref_pdf.pdf")

    def test_returns_none_for_non_pdf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        import citeverify_core.retrieval as ret_pkg
        monkeypatch.setattr(ret_pkg, "SOURCES_DIR", sources_dir)
        pdf = sources_dir / "ref_html.pdf"
        pdf.write_bytes(b"<html><body>login page</body></html>")
        from citeverify_core.retrieval import get_pdf_path
        assert get_pdf_path("ref_html") is None


# ===========================================================================
# 10. PDF download: magic-byte validation
# ===========================================================================

class TestPdfMagicBytes:
    def test_valid_pdf_magic(self, tmp_path: Path):
        p = tmp_path / "good.pdf"
        p.write_bytes(b"%PDF-1.4 some content")
        assert _is_valid_pdf(p) is True

    def test_invalid_magic(self, tmp_path: Path):
        p = tmp_path / "bad.pdf"
        p.write_bytes(b"<html>login</html>")
        assert _is_valid_pdf(p) is False

    def test_missing_file(self, tmp_path: Path):
        assert _is_valid_pdf(tmp_path / "nonexistent.pdf") is False

    def test_html_response_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Simulate a paywall returning HTML: download_pdf must return None."""
        from citeverify_core.retrieval import pdf_handler as ph
        monkeypatch.setattr(ph, "SOURCES_DIR", tmp_path / "sources")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content = MagicMock(return_value=iter([b"<html>"]))

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session.timeout = 20

        monkeypatch.setattr(ph, "get_session", lambda: mock_session)

        result = ph.download_pdf("https://paywall.example.com/paper.pdf", "ref_paywalled")
        assert result is None


# ===========================================================================
# 11. Flag tests: author_mismatch, doi_not_resolved
# ===========================================================================

class TestFlags:
    def test_author_mismatch_flag(self):
        """_initial_flags should raise author_mismatch when first-author surnames differ."""
        from citeverify_core.retrieval.retrieve import _initial_flags
        ref = Reference(reference_id="x", raw_text="x", title="T",
                        authors=["LeCun, Yann"], year=2017, parse_confidence=0.9)
        meta = {"doi": "10.xxx/x", "year": 2017, "authors": ["Ashish Vaswani"], "title": "T"}
        flags = _initial_flags(ref, meta)
        assert "author_mismatch" in flags

    def test_no_author_mismatch_when_surnames_match(self):
        from citeverify_core.retrieval.retrieve import _initial_flags
        ref = Reference(reference_id="x", raw_text="x", title="T",
                        authors=["Vaswani, Ashish"], year=2017, parse_confidence=0.9)
        meta = {"doi": "10.xxx/x", "year": 2017, "authors": ["Ashish Vaswani"], "title": "T"}
        flags = _initial_flags(ref, meta)
        assert "author_mismatch" not in flags

    def test_year_mismatch_flag(self):
        from citeverify_core.retrieval.retrieve import _initial_flags
        ref = Reference(reference_id="x", raw_text="x", title="T",
                        authors=[], year=2010, parse_confidence=0.9)
        meta = {"doi": "10.xxx/x", "year": 2017, "authors": [], "title": "T"}
        flags = _initial_flags(ref, meta)
        assert "year_mismatch" in flags

    def test_doi_not_resolved_when_no_doi(self):
        from citeverify_core.retrieval.retrieve import _initial_flags
        ref = Reference(reference_id="x", raw_text="x", title="T",
                        authors=[], year=2017, parse_confidence=0.9)
        meta = {"doi": None, "year": 2017, "authors": [], "title": "T"}
        flags = _initial_flags(ref, meta)
        assert "doi_not_resolved" in flags

    def test_not_found_source_includes_doi_not_resolved(self, monkeypatch: pytest.MonkeyPatch):
        """When DOI lookup fails and no title found, doi_not_resolved must appear."""
        from citeverify_core.retrieval import retrieve as ret_mod
        # Stub all fetchers to return None
        monkeypatch.setattr(ret_mod, "crossref_by_doi", lambda doi: None)
        monkeypatch.setattr(ret_mod, "crossref_search_title", lambda t: None)
        monkeypatch.setattr(ret_mod, "openalex_search_title", lambda t: None)
        monkeypatch.setattr(ret_mod, "arxiv_search_title", lambda t: None)
        monkeypatch.setattr(ret_mod, "s2_search_title", lambda q: None)
        monkeypatch.setattr(ret_mod, "index_exists", lambda ref_id: False)

        ref = Reference(reference_id="ref_doi_fail", raw_text="x", title="Some Title",
                        doi="10.invalid/xyz", parse_confidence=0.5)
        source = ret_mod.retrieve_source(ref)
        assert source.matched is False
        assert "doi_not_resolved" in source.flags
        assert "reference_not_found" in source.flags


# ===========================================================================
# 12. data/mock/sources.json validation
# ===========================================================================

class TestMockSources:
    _MOCK_PATH = _REPO_ROOT / "data" / "mock" / "sources.json"

    def test_mock_sources_file_exists(self):
        assert self._MOCK_PATH.exists(), f"Missing: {self._MOCK_PATH}"

    def test_mock_sources_valid_json(self):
        data = json.loads(self._MOCK_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) > 0

    def test_mock_sources_all_valid_source_models(self):
        """Every object in sources.json must parse as a valid Source."""
        data = json.loads(self._MOCK_PATH.read_text(encoding="utf-8"))
        errors = []
        for i, obj in enumerate(data):
            try:
                Source.model_validate(obj)
            except Exception as exc:
                errors.append(f"Item {i} ({obj.get('reference_id', '?')}): {exc}")
        assert not errors, "sources.json validation errors:\n" + "\n".join(errors)

    def test_mock_sources_cover_key_scenarios(self):
        """sources.json must include at least: matched, unmatched, abstract_only."""
        data = json.loads(self._MOCK_PATH.read_text(encoding="utf-8"))
        sources = [Source.model_validate(obj) for obj in data]
        assert any(s.matched for s in sources), "Need at least one matched source"
        assert any(not s.matched for s in sources), "Need at least one unmatched source"
        text_levels = {s.text_level for s in sources}
        assert "abstract_only" in text_levels or "full_text" in text_levels


# ===========================================================================
# 13. Import smoke test
# ===========================================================================

class TestImports:
    def test_public_api_importable(self):
        from citeverify_core.retrieval import (
            get_pdf_path,
            ingest_pdf,
            locate_quote,
            retrieve_source,
            search_passages,
        )
        assert callable(retrieve_source)
        assert callable(search_passages)
        assert callable(locate_quote)
        assert callable(ingest_pdf)
        assert callable(get_pdf_path)

    def test_schemas_importable(self):
        from citeverify_core.common import schemas
        assert hasattr(schemas, "Source")
        assert hasattr(schemas, "Passage")
        assert hasattr(schemas, "Evidence")
        assert hasattr(schemas, "Reference")
