# CiteVerify – Scientific Claim and Citation Verification System

> **⚠ Disclaimer:** CiteVerify is designed to *assist* human reviewers.
> All outputs—verdicts, confidence scores, evidence quotes—are
> **never** a final academic judgment. Uncertainty, source links, and a
> human-review path are visible throughout the application.

---

## Table of Contents

1. [Project overview](#project-overview)
2. [Repository layout](#repository-layout)
3. [Quick start (all platforms)](#quick-start)
4. [Environment variables](#environment-variables)
5. [Module guide](#module-guide)
   - [M1 – Document Intelligence](#m1--document-intelligence)
   - [M2 – Source Retrieval](#m2--source-retrieval)
   - [M3 – Verification Engine](#m3--verification-engine)
   - [M4 – Product & Integration](#m4--product--integration)
6. [Data contracts](#data-contracts)
7. [Running tests](#running-tests)
8. [Git workflow](#git-workflow)
9. [Team: clone and start](#team-clone-and-start)

---

## Project overview

CiteVerify takes an academic document (PDF, DOCX, or pasted text), finds
checkable claims, detects their citations, retrieves the original cited papers
from open-access sources, and compares each claim against the paper's actual
text. It produces a claim-by-claim report with verdict, evidence, confidence
breakdown, source trace, flags, and a human-review panel.

**Pipeline:**
```
Upload/parse → Extract claims+citations → Retrieve original papers
            → Compare claim vs evidence → Report
```

---

## Repository layout

```
citeverify/
├── backend/
│   ├── app/                        # M4 – FastAPI, DB, orchestrator
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── orchestrator.py
│   │   ├── mocks.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   └── routers/
│   │       ├── documents.py
│   │       ├── claims.py
│   │       └── sources.py
│   └── citeverify_core/
│       ├── common/
│       │   ├── schemas.py          # Shared Pydantic v2 contracts (M4 creates)
│       │   ├── llm_client.py       # LLM adapter (M3 owns)
│       │   └── ocr.py              # OCR helper (M1 owns)
│       ├── doc_intel/              # M1 – Document Intelligence
│       │   └── parser.py
│       ├── retrieval/              # M2 – Source Retrieval
│       │   └── retriever.py
│       └── verification/           # M3 – Verification Engine
│           └── engine.py
├── frontend/                       # M4 – Next.js App Router + Tailwind
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx            # Upload / paste page
│   │   │   └── results/[docId]/
│   │   │       └── page.tsx        # Results page
│   │   ├── components/
│   │   │   ├── ClaimCard.tsx
│   │   │   ├── VerdictBadge.tsx
│   │   │   ├── FlagBadge.tsx
│   │   │   ├── ConfidenceBar.tsx
│   │   │   ├── ReviewPanel.tsx
│   │   │   └── ManualSourceUpload.tsx
│   │   └── lib/
│   │       ├── types.ts
│   │       └── api.ts
│   ├── package.json
│   └── next.config.js
├── data/
│   ├── uploads/        # (git-ignored) uploaded documents
│   ├── sources/        # (git-ignored) retrieved PDFs
│   ├── cache/          # (git-ignored) embeddings + chunk indices
│   └── mock/           # Committed canned data for testing
├── tests/
│   ├── test_schemas.py
│   └── test_mocks.py
├── requirements.txt
├── requirements-m1.txt
├── requirements-m2.txt
├── requirements-m3.txt
├── requirements-m4.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Quick start

### Prerequisites

- Python 3.11
- Node.js 18+ (for the frontend)
- Git

### 1 – Clone the repo

```powershell
git clone https://github.com/shrikanthshenoy099/citeverify.git
cd citeverify
```

### 2 – Create your `.env`

```powershell
# Windows (PowerShell / cmd)
copy .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

Edit `.env` and set `CONTACT_EMAIL` to your own email address.
Leave `USE_MOCKS=true` until your module is ready.

### 3 – Backend

#### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload --port 8000
```

#### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload --port 8000
```

> **PowerShell execution policy:** If `.\.venv\Scripts\Activate.ps1` is blocked,
> run this once and retry:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

The API is now at <http://localhost:8000>.
Interactive docs: <http://localhost:8000/docs>

**M4 health check** – after the server starts, verify:
```powershell
Invoke-RestMethod http://localhost:8000/health
# expected: @{status=ok; service=citeverify}
```
Or open <http://localhost:8000/health> in a browser.

> **First run note:** The embedding model (all-MiniLM-L6-v2, ~90 MB) is
> downloaded on first use by sentence-transformers. Do this early on good Wi-Fi.

### 4 – Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

The Next.js dev server proxies `/api/*` to `http://localhost:8000/api/*`
(see `next.config.js`) so no CORS configuration is needed.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | ✓ | `mock` | `mock` / `openai` / `ibm_bob` |
| `LLM_BASE_URL` | – | OpenAI | Override for local or IBM Bob endpoint |
| `LLM_API_KEY` | – | _(blank)_ | API key; leave blank if not needed |
| `LLM_MODEL` | – | `gpt-4o-mini` | Model name |
| `USE_MOCKS` | – | `true` | Use canned mocks instead of real modules |
| `CONTACT_EMAIL` | ✓ | – | Polite `mailto` for Crossref / OpenAlex |
| `S2_API_KEY` | – | _(blank)_ | Semantic Scholar (optional; raises rate limit) |
| `DATA_DIR` | – | `./data` | Root for uploads, sources, cache |

See `.env.example` for the full list including tunable paths.

---

## Module guide

### M1 – Document Intelligence

**Owner:** M1 | **Folder:** `backend/citeverify_core/doc_intel/`

**Public interface:**
```python
from citeverify_core.doc_intel.parser import parse_document

parsed: ParsedDocument = parse_document(
    file_path="/abs/path/to/file.pdf",   # or None
    raw_text="pasted text …",           # or None
    doc_id="uuid-string",
)
```

Responsibilities:
- Extract text from PDF (PyMuPDF), DOCX (python-docx), or plain text.
- OCR image-only pages via `common/ocr.py`; set `"ocr_text"` flag.
- Segment references with regex + LLM extraction via `llm_client`.
- Extract verifiable claims (numeric, factual, conclusion, methodological).
- Link citation markers to reference IDs.
- `page` is `null` for DOCX / pasted text.

**Dependencies:** `requirements-m1.txt`

---

### M2 – Source Retrieval

**Owner:** M2 | **Folder:** `backend/citeverify_core/retrieval/`

**Public interface:**
```python
from citeverify_core.retrieval.retriever import (
    retrieve_source, search_passages, locate_quote, ingest_pdf
)

source: Source = retrieve_source(reference)
passages: list[Passage] = search_passages(reference_id, query, k=5)
evidence: Evidence | None = locate_quote(reference_id, quote)
source: Source = ingest_pdf(reference_id, pdf_path)
```

Responsibilities:
- Query Crossref, OpenAlex, Unpaywall, Semantic Scholar (open access only).
- Download PDFs where available; extract and chunk text (~250 words / 50-word overlap).
- Embed chunks with sentence-transformers `all-MiniLM-L6-v2`.
- Store embeddings as `.npy` + JSON metadata under `data/cache/index/{reference_id}/`.
- `search_passages`: cosine similarity top-k=5; flag `low_retrieval_score` if top score < 0.35.
- `locate_quote`: fuzzy match (threshold ≥ 90); return `Evidence` with PyMuPDF bboxes.
- `ingest_pdf`: build index from user-uploaded PDF; set `manual_source` flag.

**Dependencies:** `requirements-m2.txt`

---

### M3 – Verification Engine

**Owner:** M3 | **Folder:** `backend/citeverify_core/verification/` and `common/llm_client.py`

**Public interface:**
```python
from citeverify_core.verification.engine import verify, reverify_for_reference
from citeverify_core.common.llm_client import get_llm_client

verdict: Verdict = verify(claim, reference, source)
verdicts: list[Verdict] = reverify_for_reference(reference_id, claims, reference, source)
```

`verify()` accepts three optional keyword overrides for testing:
- `search_passages_fn` — replaces the M2 `search_passages` call
- `locate_quote_fn`   — replaces the M2 `locate_quote` call
- `llm_client`        — replaces the default `get_llm_client()` result

**Pipeline steps (engine.py):**
1. Early exit if `source.matched == False` → `needs_review`, no LLM call, `reference_not_found` flag
2. Retrieve passages from M2 `search_passages`
3. Retrieval quality flags: score < 0.35 → `low_retrieval_score`; score < 0.175 → also `possibly_unrelated_citation`
4. Call LLM via `llm_client.complete_json`; up to 2 retries on `LLMSchemaError` → `llm_output_invalid` flag on exhaustion
5. Scope mismatch: LLM returns `scope_mismatch=true` → flag + cap `supported` → `partly_supported`
6. Special flags: `ocr_text` appends a caution note; `possibly_retracted` appends a retraction warning
7. `possibly_outdated` override: source older than 10 years AND `time_sensitive=true` → override verdict
8. Anti-hallucination: supporting quote verified with `locate_quote`; if not found in source or passages → `quote_not_verified` + downgrade `supported`/`partly_supported` → `needs_review`
9. Numeric mismatch: `numbers_mentioned` non-empty AND `numbers_match=false` → `number_not_found` + cap `supported` → `partly_supported`
10. Compute weighted confidence
11. `requires_human_review` gate (confidence, verdict, flags)
12. Build `SourceTrace` and return `Verdict`

**Confidence weights** (all in `verification/config.py`, overridable via `CV_` env vars):
| Component | Weight | Env var |
|---|---|---|
| retrieval | 0.20 | `CV_W_RETRIEVAL` |
| llm_certainty | 0.30 | `CV_W_LLM_CERTAINTY` |
| text_match | 0.20 | `CV_W_TEXT_MATCH` |
| full_text | 0.10 | `CV_W_FULL_TEXT` |
| numeric_match | 0.20 | `CV_W_NUMERIC_MATCH` |

**`needs_human_review = true` when:** confidence < 0.60, OR verdict in {needs_review, contradictory, possibly_outdated}, OR any flag in {quote_not_verified, number_not_found, scope_mismatch, possibly_retracted, ocr_text, abstract_only, full_text_unavailable}.

**abstract_only** sources: overall confidence capped at 0.50.

**LLM adapter (`common/llm_client.py`):**

| `LLM_PROVIDER` | Client | Notes |
|---|---|---|
| `mock` | `MockLLMClient` | No network, deterministic. Default. |
| `http` | `GenericHTTPLLMClient` | OpenAI-compatible endpoint; needs `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| `bob` | `BobLLMClient` | ⚠️ Stub only — awaiting IBM Bob API details |

**Prompts:** stored in `backend/citeverify_core/verification/prompts/system.txt` and `user.txt`. Edit these files to tune the LLM instructions without changing Python code.

**Evaluation harness:**
```bash
# From repo root (venv active, pythonpath not needed — script self-configures):
python backend/citeverify_core/verification/eval.py
# Expected: "Results: 20/20 passed  – ALL PASS"  (exit code 0)
```

The harness loads `data/mock/eval_set.json` (20 labeled cases) and runs `verify()` with injected stubs. All 20 cases must pass; any failure prints a detailed diff and exits with code 1.

**Running M3 tests:**
```bash
# From repo root:
pytest tests/m3/ -v
# 81 tests, all offline (no network, no GPU).
```

**Dependencies:** `requirements-m3.txt`

---

### M4 – Product & Integration

**Owner:** M4 | **Folders:** `backend/app/` and `frontend/`

REST API (all under `/api`):

| Method | Path | Description |
|---|---|---|
| `POST` | `/documents` | Upload PDF/DOCX (multipart) or `{text}` |
| `GET` | `/documents/{id}/status` | Poll pipeline status |
| `GET` | `/documents/{id}/results` | Claims + verdicts |
| `GET` | `/claims/{id}` | Single claim with verdicts |
| `POST` | `/claims/{id}/review` | Submit human review action |
| `GET` | `/claims/{id}/reviews` | List reviews for a claim |
| `GET` | `/sources/{ref_id}/pdf` | Stream source PDF |
| `POST` | `/references/{ref_id}/source` | Upload manual source PDF |
| `GET` | `/documents/{id}/export?format=csv\|pdf` | Export report |

---

## Module M2 – Source Retrieval

**Owner**: M2 team
**Branch**: `m2-retrieval`
**Commit prefix**: `[M2]`
**Files owned**:
- `backend/citeverify_core/retrieval/` (all files)
- `requirements-m2.txt`
- `tests/m2/`

### Public interface

```python
from citeverify_core.retrieval import retrieve_source, search_passages, locate_quote, ingest_pdf
```

| Function | Signature | Description |
|---|---|---|
| `retrieve_source` | `(reference: Reference) → Source` | Locate paper, download PDF, build index |
| `search_passages` | `(reference_id, query, k=5) → list[Passage]` | Top-k cosine similarity passages |
| `locate_quote` | `(reference_id, quote) → Evidence \| None` | Fuzzy-locate a quote + PDF bboxes |
| `ingest_pdf` | `(reference_id, pdf_path) → Source` | Index a reviewer-supplied PDF |

### Resolution pipeline

`retrieve_source` tries sources in this order, stopping at the first match:

1. **Crossref** – DOI-direct resolve, then title search
2. **OpenAlex** – title search (with abstract for non-PDF fallback)
3. **arXiv** – title search
4. **Unpaywall** – open-access PDF URL for a known DOI
5. **Semantic Scholar** – title/DOI search (optional `S2_API_KEY`)

No API keys required. All calls use `CONTACT_EMAIL` as the `mailto` parameter.

### Matching rules

| Condition | Verdict |
|---|---|
| `title_ratio ≥ 92` | matched (regardless of author/year) |
| `title_ratio ≥ 85` AND (first-author surname matches OR year ±1) | matched |
| Otherwise | not matched → flags: `title_mismatch`, `reference_not_found` |

### Chunking and indexing

- Sentence splitting: **pysbd** – never crosses page boundaries
- Chunk size: **~250 words**, **50-word overlap**
- Embedding model: `all-MiniLM-L6-v2` (configurable `EMBEDDING_MODEL`)
- Index format: `data/cache/index/{reference_id}/embeddings.npy` + `metadata.json`
- Search: **numpy cosine similarity**, top-k (configurable `TOP_K`, default 5)
- Low-retrieval flag: top score < 0.35 → `low_retrieval_score`

### OCR fallback

PDF pages with no text layer are passed to `common/ocr.py:ocr_pdf_page()`.
OCR'd sources receive `ocr_text` flag. `locate_quote` returns empty `bboxes` for OCR pages.

### Reviewer-supplied PDFs (`ingest_pdf`)

Called by M4 endpoint `POST /api/references/{reference_id}/source`.
Sets `manual_source` flag; OCR pages additionally get `ocr_text`. Overwrites any previous index.

### Retraction check (stretch)

After retrieval, M2 inspects the Crossref `update-to` and `relation` fields.
If a retraction notice is found, adds flag `possibly_retracted`. Silently skipped if DOI is absent.

### Flags set by M2

| Flag | Meaning |
|---|---|
| `reference_not_found` | No database returned a matching record |
| `doi_not_resolved` | Metadata found but no DOI in the record |
| `title_mismatch` | Title ratio below threshold |
| `year_mismatch` | Year differs by more than ±1 |
| `full_text_unavailable` | No open-access PDF found |
| `abstract_only` | Only an abstract was available |
| `ocr_text` | Some or all text came from OCR |
| `low_retrieval_score` | Top cosine score < 0.35 |
| `manual_source` | PDF was supplied by the reviewer |
| `possibly_retracted` | Crossref retraction notice found |

### Running M2 tests

```bash
# From the repo root (Python 3.11 venv active):
pip install -r requirements-m2.txt
pytest tests/m2/ -v
```

50 tests run fully offline (no network, no GPU).

### Configuration (`retrieval/config.py`)

All thresholds can be overridden via environment variables (see `.env.example`):
`EMBEDDING_MODEL`, `CHUNK_WORDS`, `CHUNK_OVERLAP_WORDS`, `TOP_K`,
`LOW_RETRIEVAL_THRESHOLD`, `TITLE_RATIO_MATCHED`, `TITLE_RATIO_SOLO`,
`YEAR_TOLERANCE`, `QUOTE_FUZZY_THRESHOLD`, `HTTP_TIMEOUT`, `OCR_DPI`.

---

## Data contracts

All Pydantic v2 models are in `backend/citeverify_core/common/schemas.py`.
**Field names are fixed.** A module owner must announce any change in team
chat before editing the file.

Key models: `Reference`, `Claim`, `ParsedDocument`, `Source`, `Passage`,
`Evidence`, `Verdict`, `Review`, `ConfidenceBreakdown`, `SourceTrace`, `BBox`.

Standard flags (string constants in `Flags` class):
`no_citation`, `reference_not_found`, `doi_not_resolved`, `title_mismatch`,
`author_mismatch`, `year_mismatch`, `abstract_only`, `full_text_unavailable`,
`quote_not_verified`, `number_not_found`, `possibly_unrelated_citation`,
`low_retrieval_score`, `scope_mismatch`, `llm_output_invalid`,
`ocr_text`, `possibly_retracted`, `manual_source`.

---

## Running tests

```bash
# macOS / Linux (from repo root, with venv active)
cd backend
pytest ../tests/ -v

# Windows (PowerShell)
cd backend
pytest ..\tests\ -v
```

Tests use `USE_MOCKS=true` by default.

---

## Git workflow

| Item | Rule |
|---|---|
| Branches | `m1-doc-intel` · `m2-retrieval` · `m3-verification` · `m4-product` |
| Commit prefix | `[M1] …` / `[M2] …` / `[M3] …` / `[M4] …` |
| Shared files | Announce in team chat before editing `schemas.py` or the README top section |
| Before push | `git pull --rebase origin main` → run your tests → push |
| Merge | Pull request or quick merge into `main` at agreed checkpoints; keep `main` runnable |
| **Never commit** | `.env`, venvs, `node_modules`, `data/uploads`, `data/sources`, `data/cache`, model files, `__pycache__` |
| **Do commit** | `data/mock/*.json`, small test documents, `.env.example` |

---

## Team: clone and start

### Step 1 – Clone and create your branch (Windows PowerShell)

Replace `BRANCH` with your branch name from the table below.

| Member | Branch |
|---|---|
| M1 | `m1-doc-intel` |
| M2 | `m2-retrieval` |
| M3 | `m3-verification` |
| M4 | `m4-product` |

```powershell
git clone https://github.com/shrikanthshenoy099/citeverify.git
cd citeverify
git checkout -b BRANCH
git push -u origin BRANCH
```

> **M3 note:** The owner's laptop already has the M3 work on `main`.
> Run `git checkout -b m3-verification` there once main is pushed.

### Step 2 – Set up Python 3.11

```powershell
copy .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If the activate script is blocked:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
Then retry `.\.venv\Scripts\Activate.ps1`.

Edit `.env` and set `CONTACT_EMAIL` to your own email address.

### Step 3 – Install dependencies

```powershell
pip install -r requirements.txt
```

### Step 4 – Run the backend

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

Verify: open <http://localhost:8000/health> — you should see `{"status":"ok","service":"citeverify"}`.

### Step 5 – Run the frontend (M4 only, or anyone who wants the UI)

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

### macOS / Linux equivalent

```bash
cp .env.example .env
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000
```

### Pre-create branches (M4 / repo owner does this once before teammates clone)

```powershell
git checkout -b m1-doc-intel; git push -u origin m1-doc-intel
git checkout -b m2-retrieval;  git push -u origin m2-retrieval
git checkout -b m3-verification; git push -u origin m3-verification
git checkout -b m4-product;    git push -u origin m4-product
git checkout main
```

### Extra jobs by member

| Member | Extra responsibility |
|---|---|
| **M4** | Confirm `http://localhost:8000/health` returns `{"status":"ok"}` after first run. |
| **M1** | `common/ocr.py` already exists — edit it in place, do **not** recreate. Announce any signature change in team chat. |
| **M2** | Never commit anything under `data/sources/` or `data/cache/`. |
| **M3 (owner)** | Ask organisers by 14:00 how IBM Bob exposes the model to the app — this is the only blocking item. |

### Integration

When a teammate merges to `main`:

```powershell
git pull origin main                 # pull updates
# optionally: set USE_MOCKS=false for that module in .env
cd backend
pytest ../tests/ -v                  # run tests
# report any contract mismatch to the owner — do NOT work around it
```

> When you open IBM Bob for the first time on your branch, start with this message
> before pasting the full prompt:
>
> *"The repo already contains `common/schemas.py`, `common/llm_client.py` and
> `common/ocr.py` (created by M3). Do NOT recreate or modify them. Read
> `schemas.py` first and build against it exactly. Create only your own
> module's folder and your own `requirements-mX.txt` file."*
