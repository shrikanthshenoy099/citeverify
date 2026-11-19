"""
tests/m1/fixtures/create_sample_docs.py
Run once to create the sample PDF and DOCX in tests/m1/fixtures/.
Requires: PyMuPDF, python-docx (already in requirements-m1.txt).
"""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).parent

SAMPLE_TEXT = """\
Abstract

Deep learning has revolutionized natural language processing [1].
Transformer architectures outperform recurrent models on most benchmarks [2].
The model accuracy increased by 15% compared to the baseline (Smith et al., 2020).

Introduction

Recent work demonstrates that pre-training on large corpora improves downstream performance [1, 2].
A particular study found that a learning app improved test scores by 30%.
Therefore, we conclude that transfer learning is effective for low-resource tasks.

Methods

We trained the model using the Adam optimiser with a learning rate of 0.001.
The dataset contains 50,000 annotated sentences collected from scientific articles.
Evaluation was performed on the standard benchmark dataset using F1 score.

Results

Results demonstrate a 20% improvement in F1 score over the previous state-of-the-art [2].
The proposed approach achieves 94.3% accuracy on the held-out test set.
Error rates were reduced by a factor of 2 compared to the baseline method.

References
[1] LeCun, Y., Bengio, Y., Hinton, G. (2015). "Deep learning." Nature, 521, 436-444. doi:10.1038/nature14539
[2] Vaswani, A., Shazeer, N., Parmar, N. et al. (2017). "Attention is all you need." NeurIPS. doi:10.5555/3295222.3295349
"""

GROUND_TRUTH = {
    "_description": "Ground-truth for sample_paper.{pdf,docx,txt}",
    "expected_reference_count": 2,
    "expected_references": [
        {
            "doi": "10.1038/nature14539",
            "title": "Deep learning.",
            "year": 2015
        },
        {
            "doi": "10.5555/3295222.3295349",
            "title": "Attention is all you need.",
            "year": 2017
        }
    ],
    "expected_citation_markers": {
        "Deep learning has revolutionized": ["[1]"],
        "Transformer architectures": ["[2]"],
        "Smith et al., 2020": ["(Smith et al., 2020)"],
        "pre-training on large corpora": ["[1]", "[2]"],
        "20% improvement": ["[2]"]
    },
    "expected_claims_containing": [
        {"text_fragment": "30%", "claim_type": "numeric", "numbers_mentioned_includes": "30%"},
        {"text_fragment": "15%", "claim_type": "numeric", "numbers_mentioned_includes": "15%"},
        {"text_fragment": "transfer learning is effective", "claim_type": "conclusion"},
        {"text_fragment": "Adam optimiser", "claim_type": "numeric"},
        {"text_fragment": "50,000 annotated sentences", "claim_type": "methodological"},
        {"text_fragment": "20% improvement", "claim_type": "numeric", "numbers_mentioned_includes": "20%"},
    ],
    "expected_warnings_pasted_text": ["reference_list_not_found"],
    "note_reference_list_not_found": "Only appears when no REFERENCES header present. Sample text HAS a header so this warning should NOT appear for sample_paper.txt"
}


def create_txt() -> None:
    dest = HERE / "sample_paper.txt"
    dest.write_text(SAMPLE_TEXT, encoding="utf-8")
    print(f"Created {dest}")


def create_pdf() -> None:
    try:
        import fitz
    except ImportError:
        print("PyMuPDF not available – skipping PDF creation")
        return

    dest = HERE / "sample_paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Write text at a readable size
    page.insert_text((50, 50), SAMPLE_TEXT, fontsize=10)
    doc.save(str(dest))
    doc.close()
    print(f"Created {dest}")


def create_docx() -> None:
    try:
        import docx
    except ImportError:
        print("python-docx not available – skipping DOCX creation")
        return

    dest = HERE / "sample_paper.docx"
    doc = docx.Document()

    current_heading = None
    for line in SAMPLE_TEXT.splitlines():
        line = line.strip()
        if not line:
            continue
        # Simple heading detection: single short line, all words capitalized
        words = line.split()
        if len(words) <= 3 and all(w[0].isupper() for w in words if w) and not any(c in line for c in ".,;[]()"):
            doc.add_heading(line, level=1)
            current_heading = line
        else:
            doc.add_paragraph(line)

    doc.save(str(dest))
    print(f"Created {dest}")


def create_ground_truth() -> None:
    dest = HERE / "ground_truth.json"
    dest.write_text(json.dumps(GROUND_TRUTH, indent=2), encoding="utf-8")
    print(f"Created {dest}")


if __name__ == "__main__":
    HERE.mkdir(parents=True, exist_ok=True)
    create_txt()
    create_pdf()
    create_docx()
    create_ground_truth()
    print("Done.")
