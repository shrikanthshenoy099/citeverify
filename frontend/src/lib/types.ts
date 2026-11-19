/**
 * lib/types.ts – TypeScript types mirroring the Python Pydantic schemas.
 * Keep in sync with backend/citeverify_core/common/schemas.py.
 */

export type ClaimType = "numeric" | "factual" | "conclusion" | "methodological";

export type VerdictLabel =
  | "supported"
  | "partly_supported"
  | "unsupported"
  | "contradictory"
  | "possibly_outdated"
  | "needs_review";

export type TextLevel =
  | "full_text"
  | "abstract_only"
  | "metadata_only"
  | "none";

export type ReviewAction = "accept" | "reject" | "comment" | "override";

// ── Reference ────────────────────────────────────────────────────────────────

export interface Reference {
  reference_id: string;
  raw_text: string;
  title: string | null;
  authors: string[];
  year: number | null;
  doi: string | null;
  venue: string | null;
  parse_confidence: number;
}

// ── Claim ─────────────────────────────────────────────────────────────────────

export interface Claim {
  claim_id: string;
  doc_id: string;
  text: string;
  page: number | null;
  section: string | null;
  char_start: number;
  char_end: number;
  citation_markers: string[];
  reference_ids: string[];
  claim_type: ClaimType;
  numbers_mentioned: string[];
  context_before: string;
  context_after: string;
  flags: string[];
}

// ── Source ───────────────────────────────────────────────────────────────────

export interface Source {
  reference_id: string;
  matched: boolean;
  match_score: number;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
  url: string | null;
  pdf_path: string | null;
  text_level: TextLevel;
  full_text_available: boolean;
  source_database: string;
  flags: string[];
}

// ── BBox / Evidence ──────────────────────────────────────────────────────────

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Evidence {
  quote: string;
  passage_id: string;
  page: number | null;
  section: string | null;
  bboxes: BBox[];
  page_width: number | null;
  page_height: number | null;
}

// ── Verdict ──────────────────────────────────────────────────────────────────

export interface ConfidenceBreakdown {
  retrieval: number;
  llm_certainty: number;
  text_match: number;
  full_text: number;
  numeric_match: number;
}

export interface SourceTrace {
  doi: string | null;
  url: string | null;
  page: number | null;
  section: string | null;
}

export interface Verdict {
  claim_id: string;
  reference_id: string;
  verdict: VerdictLabel;
  explanation: string;
  evidence: Evidence | null;
  confidence: number;
  confidence_breakdown: ConfidenceBreakdown;
  source_trace: SourceTrace;
  flags: string[];
  needs_human_review: boolean;
}

// ── Review ───────────────────────────────────────────────────────────────────

export interface Review {
  review_id: string;
  claim_id: string;
  reference_id: string;
  action: ReviewAction;
  new_verdict: VerdictLabel | null;
  comment: string;
  reviewer: string;
  timestamp: string;
}

// ── API response shapes ───────────────────────────────────────────────────────

export interface ClaimWithVerdicts extends Claim {
  verdicts: Verdict[];
}

export interface DocumentResults {
  doc_id: string;
  status: string;
  claims: ClaimWithVerdicts[];
  references: Reference[];
}

export interface DocumentStatus {
  doc_id: string;
  status: string;
  error_message: string | null;
}

// ── Standard flags ────────────────────────────────────────────────────────────

export const FLAGS = {
  NO_CITATION: "no_citation",
  REFERENCE_NOT_FOUND: "reference_not_found",
  DOI_NOT_RESOLVED: "doi_not_resolved",
  TITLE_MISMATCH: "title_mismatch",
  AUTHOR_MISMATCH: "author_mismatch",
  YEAR_MISMATCH: "year_mismatch",
  ABSTRACT_ONLY: "abstract_only",
  FULL_TEXT_UNAVAILABLE: "full_text_unavailable",
  QUOTE_NOT_VERIFIED: "quote_not_verified",
  NUMBER_NOT_FOUND: "number_not_found",
  POSSIBLY_UNRELATED_CITATION: "possibly_unrelated_citation",
  LOW_RETRIEVAL_SCORE: "low_retrieval_score",
  SCOPE_MISMATCH: "scope_mismatch",
  LLM_OUTPUT_INVALID: "llm_output_invalid",
  OCR_TEXT: "ocr_text",
  POSSIBLY_RETRACTED: "possibly_retracted",
  MANUAL_SOURCE: "manual_source",
} as const;

export type FlagKey = keyof typeof FLAGS;
export type FlagValue = (typeof FLAGS)[FlagKey];
