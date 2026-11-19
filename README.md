# CiteVerify – Scientific Claim and Citation Verification System

> **Disclaimer**: CiteVerify *assists* human reviewers. Its output is never a final academic
> judgment. Every result includes a confidence score, source trace, and a `needs_human_review`
> flag. Treat all verdicts as a starting point for expert review, not a conclusion.

---

## Repository layout

```
citeverify/
  backend/
    app/                             # M4 – FastAPI, DB, orchestrator
    citeverify_core/
      common/
        schemas.py                   # Shared Pydantic v2 contracts (M4 owns)
        llm_client.py                # LLM adapter layer (M3 owns)
        ocr.py                       # OCR helper (M1 owns)
      doc_intel/                     # M1 – Document Intelligence
      retrieval/                     # M2 – Source Retrieval
      verification/                  # M3 – Verification Engine
  data/
    uploads/   (gitignored)
    sources/   (gitignored)
    cache/     (gitignored)
    mock/      (committed – small test fixtures)
  tests/
    m3/
  .env.example
  pyproject.toml
  requirements-m3.txt
  README.md
```

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd citeverify

# 2. Copy env template
cp .env.example .env
# Edit .env – fill in CONTACT_EMAIL at minimum

# 3. Create a virtual environment (Python 3.11)
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 4. Install M3 dependencies
pip install -r requirements-m3.txt

# 5. Run M3 tests
pytest tests/m3/ -v
```

---

## Module M3 – Verification Engine + LLM Adapter

**Owner**: M3 team  
**Branch**: `m3-verification`  
**Commit prefix**: `[M3]`  
**Files owned**:
- `backend/citeverify_core/common/llm_client.py`
- `backend/citeverify_core/verification/` (all files)
- `requirements-m3.txt`
- `tests/m3/`

### Public interface

```python
from citeverify_core.verification import verify, reverify_for_reference
```

#### `verify(claim, reference, source) -> Verdict`

Verifies a single `(Claim, Reference, Source)` triple.  
Internally: retrieves passages from M2 → builds LLM prompt → calls the LLM →
applies `possibly_outdated` override → computes weighted confidence → collects flags →
decides `needs_human_review`.

Safe to call multiple times on the same pair (idempotent).

#### `reverify_for_reference(reference_id, claims, reference, source) -> list[Verdict]`

Re-runs `verify()` for every claim that cites `reference_id`.  
Called by M4 after a manual source PDF is uploaded via
`POST /api/references/{reference_id}/source`.

---

### LLM client (`common/llm_client.py`)

| Provider | Env `LLM_PROVIDER` | Notes |
|---|---|---|
| `MockLLMClient` | `mock` (default) | No network; deterministic |
| `GenericHTTPLLMClient` | `http` | OpenAI-compatible endpoint |
| `BobLLMClient` | `bob` | ⚠️ Incomplete – awaiting IBM Bob API details |

**Selecting a provider**: set `LLM_PROVIDER` in `.env`.

```
# .env
LLM_PROVIDER=mock          # local development / tests
# LLM_PROVIDER=http        # real model
# LLM_BASE_URL=https://...
# LLM_API_KEY=sk-...
# LLM_MODEL=gpt-4o-mini
```

All callers use the single public call:

```python
from citeverify_core.common.llm_client import get_llm_client

llm = get_llm_client()
result: dict = llm.complete_json(system=..., user=..., schema=..., temperature=0)
```

---

### Configuration (`verification/config.py`)

All thresholds and weights are in `verification/config.py` and can be overridden
with environment variables (prefix `CV_`):

| Config | Default | Env var |
|---|---|---|
| Retrieval weight | 0.20 | `CV_W_RETRIEVAL` |
| LLM certainty weight | 0.30 | `CV_W_LLM_CERTAINTY` |
| Text-match weight | 0.20 | `CV_W_TEXT_MATCH` |
| Full-text weight | 0.10 | `CV_W_FULL_TEXT` |
| Numeric-match weight | 0.20 | `CV_W_NUMERIC_MATCH` |
| Human review threshold | 0.60 | `CV_HUMAN_REVIEW_THRESHOLD` |
| Abstract-only cap | 0.50 | `CV_ABSTRACT_ONLY_CAP` |
| Low-retrieval threshold | 0.35 | `CV_LOW_RETRIEVAL_THRESHOLD` |
| Quote fuzzy threshold | 90 | `CV_QUOTE_FUZZY_THRESHOLD` |
| Possibly-outdated years | 10 | `CV_POSSIBLY_OUTDATED_YEARS` |

---

### Flag handling

| Flag | Effect |
|---|---|
| `ocr_text` | `full_text` score → 0.7, forces `needs_human_review`, appends note to explanation |
| `possibly_retracted` | Forces `needs_human_review`, appends warning to explanation |
| `manual_source` | Treated as normal full-text source (no override) |
| `abstract_only` | Confidence capped at 0.50, forces `needs_human_review` |
| `number_not_found` | Added when claim has numbers but LLM reports they don't match |
| `quote_not_verified` | Added when `locate_quote` cannot fuzzy-match the supporting quote |
| `llm_output_invalid` | Added when LLM returns invalid JSON / schema mismatch |

---

### Running the tests

```bash
pytest tests/m3/ -v
```

50 tests covering:
- `MockLLMClient` behaviour and schema validation
- `get_llm_client()` provider selection and error handling
- Confidence computation (all text levels, caps, weights)
- `requires_human_review` triggers
- Prompt construction and LLM response parsing
- `possibly_outdated` override rule
- `verify()` happy path and all edge cases (OCR, retracted, outdated, no passages, etc.)
- `reverify_for_reference()` filtering

---

## Data contracts

All shared models are in `backend/citeverify_core/common/schemas.py` (owned by M4).
**Do not rename fields** without a team announcement.

Key models: `Reference`, `Claim`, `ParsedDocument`, `Source`, `Passage`, `Evidence`,
`Verdict`, `ConfidenceBreakdown`, `SourceTrace`, `Review`.

---

## Git workflow

- Each team member works on their own branch (`m1-doc-intel`, `m2-retrieval`,
  `m3-verification`, `m4-product`).
- Merge into `main` via PR at agreed checkpoints.
- Commit prefix: `[M1]`, `[M2]`, `[M3]`, `[M4]`.
- Before pushing: `git pull --rebase origin main` → run tests → push.
- **Never commit**: `.env`, venvs, `node_modules`, `data/uploads`, `data/sources`,
  `data/cache`, model files, `__pycache__`.

---

## Open items

- **BobLLMClient** (`common/llm_client.py`): IBM Bob's API shape is not yet confirmed.
  Set `LLM_PROVIDER=mock` or `LLM_PROVIDER=http` until it is resolved.
  See TODO comments in `llm_client.py`.
