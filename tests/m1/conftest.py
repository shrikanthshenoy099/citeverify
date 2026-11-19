"""
tests/m1/conftest.py – shared fixtures for M1 doc_intel tests.
"""

from __future__ import annotations

import os

import pytest

# Force mock LLM for all M1 tests (avoids network calls in ref_parser)
os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.schemas import ParsedDocument, Reference, Claim, Flags


SAMPLE_TEXT_WITH_REFS = """\
Deep learning has achieved remarkable results in natural language processing [1].
The model accuracy increased by 15% compared to the baseline (Smith et al., 2020).
Therefore, we conclude that transformer architectures outperform recurrent models [2].
The dataset contains 50,000 annotated sentences collected from scientific articles.

REFERENCES
[1] LeCun, Y., Bengio, Y., Hinton, G. (2015). "Deep learning." Nature, 521, 436–444. doi:10.1038/nature14539
[2] Vaswani, A., Shazeer, N., Parmar, N. et al. (2017). "Attention is all you need." NeurIPS. doi:10.5555/3295222.3295349
"""

SAMPLE_TEXT_NO_REFS = """\
Sentence segmentation is a core NLP task.
It involves splitting text into individual sentences.
Various tools exist for English sentence boundary detection.
"""

SAMPLE_TEXT_AUTHOR_YEAR = """\
Recent studies have demonstrated significant improvements in accuracy (Johnson 2021).
The proposed method achieves a 20% reduction in error rate (Brown & Lee, 2019).

References
Johnson, A. (2021). "Improving accuracy in NLP." Journal of AI Research.
Brown, T., Lee, K. (2019). "Error rate reduction." Machine Learning, 42(3).
"""


@pytest.fixture()
def text_with_refs() -> str:
    return SAMPLE_TEXT_WITH_REFS


@pytest.fixture()
def text_no_refs() -> str:
    return SAMPLE_TEXT_NO_REFS


@pytest.fixture()
def text_author_year() -> str:
    return SAMPLE_TEXT_AUTHOR_YEAR
