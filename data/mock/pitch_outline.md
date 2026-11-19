# CiteVerify – Pitch Outline

## Angle: Academic Trust Through Honest Uncertainty

---

### 1. The Problem (60 seconds)

**Premise:** Science relies on citations being accurate. But they often aren't.

- Studies show 20-30% of citations contain errors (misquotation, wrong number, wrong paper).
- Manual verification of every citation is prohibitively slow – a single literature review
  can cite hundreds of papers.
- Retractions and misrepresentations propagate silently through citation chains.
- Reviewers, editors, and readers have no practical tool to spot-check claims quickly.

**The gap:** Automation exists for plagiarism. Nothing reliable exists for *citation accuracy*.

---

### 2. What CiteVerify Does (90 seconds)

Upload a paper → CiteVerify:

1. **Extracts** every verifiable claim and its citation.
2. **Retrieves** the original cited paper from open-access databases (Crossref, OpenAlex,
   Unpaywall, Semantic Scholar).
3. **Compares** the claim against the paper's actual text using NLP + a language model.
4. **Reports** verdict, evidence quote, confidence, source trace, and flags – claim by claim.

**Key outputs:**
- Verdict: Supported / Partly Supported / Unsupported / Contradictory / Possibly Outdated / Needs Review
- Confidence breakdown: retrieval quality, LLM certainty, text match, full-text availability, numeric match
- Highlighted PDF viewer showing exactly *where* in the source the evidence was found
- Human review panel: accept, reject, override, comment – full audit trail

---

### 3. What Makes This Different (60 seconds)

**Honest uncertainty is a feature, not a bug.**

Every other AI tool hides its uncertainty. CiteVerify surfaces it:

- Confidence is decomposed into 5 interpretable components.
- Every result carries "Not a final academic judgment" at every level.
- Low-confidence verdicts are flagged automatically for human review.
- The reviewer's decision is recorded with their name and timestamp.
- Sources with only abstract-level coverage are capped at 50% confidence.

**Evidence traceability:**
- Every verdict links back to the exact DOI, URL, page number, and section.
- Bounding-box highlights in the original PDF show the exact evidence.
- If the system can't find a paper, the reviewer can upload it themselves.

---

### 4. Trust Architecture (45 seconds)

| Layer | Mechanism |
|---|---|
| Data | Only legal open-access sources; no paywall circumvention |
| Model | LLM via controlled adapter; never direct SDK calls |
| Output | Verdict ≠ truth; it is a ranked signal for human review |
| Review | Full audit trail: reviewer name, action, timestamp, override history |
| Export | CSV and PDF reports carry disclaimer on every row/page |
| Flags | 17 standard flags including `possibly_retracted`, `ocr_text`, `manual_source` |

---

### 5. Use Cases

| Audience | Use case |
|---|---|
| **Journal editors** | Pre-review citation spot-check; flag suspicious claims before peer review |
| **Systematic reviewers** | Verify citation accuracy across dozens of included papers |
| **PhD supervisors** | Check student theses for citation drift before submission |
| **Science journalists** | Verify claims in preprints before reporting |
| **Replication researchers** | Identify claims worth targeting for replication |

---

### 6. Demo Flow (live, 3 minutes)

1. Upload a demo PDF with four planted claim types:
   - ✅ Correctly cited numeric claim (42% mortality reduction)
   - 🟡 Partly supported claim (statistic exists but overstated)
   - ❌ Fabricated citation (paper exists but says nothing of the kind)
   - ⚠ Uncited statistic (no citation → `no_citation` flag)
2. Watch the stage-by-stage progress bar: Parsing → Retrieving → Verifying → Done.
3. Summary dashboard: counts per verdict, human review queue.
4. Expand a claim card: show evidence quote, PDF highlight, confidence breakdown.
5. Submit a "Reject" review with a comment; show it persists in history.
6. Export the CSV; open it in Excel to show the disclaimer row and all columns.

---

### 7. Limitations (be upfront)

- Accuracy depends on what text is available. Abstract-only sources are capped at 50% confidence.
- The LLM can be wrong; it must always be paired with human review.
- Coverage is limited to open-access papers. Paywalled full text is not retrieved.
- OCR on scanned PDFs introduces noise (flagged as `ocr_text`).
- Possibly-retracted detection is a flag, not confirmed retraction lookup (future work).

---

### 8. Roadmap (30 seconds)

| Priority | Item |
|---|---|
| Short-term | Retraction Watch API integration |
| Short-term | Batch processing (folder of papers) |
| Medium-term | Author disambiguation for reference matching |
| Medium-term | Cross-claim consistency check (same paper cited differently) |
| Long-term | Integration with journal submission systems |

---

### 9. The Ask

CiteVerify is built on a foundation of *honest uncertainty* and *human-in-the-loop* design.
We are not replacing peer review. We are making it faster, more consistent, and more traceable.

> *"If you can't show me where in the paper the number comes from, the claim is unverified."*

---

*CiteVerify – Automated analysis to assist human review. Not a final academic judgment.*
