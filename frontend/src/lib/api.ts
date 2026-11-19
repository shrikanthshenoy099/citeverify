/**
 * src/lib/api.ts – typed API client for the CiteVerify backend.
 * All requests go to /api (proxied to localhost:8000 by next.config.js).
 */

export const API_BASE = "/api";

// ── Types (mirror backend schemas) ──────────────────────────────────────────

export type SourceType = "pdf" | "docx" | "text";

export interface DocumentStatus {
  doc_id: string;
  status: "pending" | "processing" | "done" | "error";
  source_type: SourceType;
  num_pages: number | null;
  warnings: string[];
  created_at: string;
  updated_at: string;
  error_message?: string;
}

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

export interface VerdictOut {
  reference_id: string;
  verdict:
    | "supported"
    | "partly_supported"
    | "unsupported"
    | "contradictory"
    | "possibly_outdated"
    | "needs_review";
  explanation: string;
  confidence: number;
  needs_human_review: boolean;
  flags: string[];
  evidence?: {
    quote: string;
    passage_id: string;
    page: number | null;
    section: string | null;
  } | null;
  confidence_breakdown?: ConfidenceBreakdown | null;
  source_trace?: SourceTrace | null;
}

export interface ClaimOut {
  claim_id: string;
  text: string;
  page: number | null;
  section: string | null;
  claim_type: string;
  numbers_mentioned: string[];
  flags: string[];
  verdicts: VerdictOut[];
}

export interface DocumentResults {
  doc_id: string;
  status: string;
  source_type: SourceType;
  num_pages: number | null;
  warnings: string[];
  claims: ClaimOut[];
}

export interface ReviewRequest {
  reference_id: string;
  action: "accept" | "reject" | "comment" | "override";
  new_verdict?: string;
  comment: string;
  reviewer: string;
}

export interface ReviewResponse {
  review_id: string;
  claim_id: string;
  reference_id: string;
  action: string;
  new_verdict: string | null;
  comment: string;
  reviewer: string;
  timestamp: string;
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadFile(file: File): Promise<{ doc_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<{ doc_id: string }>("/documents", { method: "POST", body: form });
}

export async function uploadText(text: string): Promise<{ doc_id: string }> {
  const form = new FormData();
  form.append("text", text);
  return apiFetch<{ doc_id: string }>("/documents", { method: "POST", body: form });
}

export async function getStatus(docId: string): Promise<DocumentStatus> {
  return apiFetch<DocumentStatus>(`/documents/${docId}/status`);
}

export async function getResults(docId: string): Promise<DocumentResults> {
  return apiFetch<DocumentResults>(`/documents/${docId}/results`);
}

export async function submitReview(
  claimId: string,
  body: ReviewRequest
): Promise<ReviewResponse> {
  return apiFetch<ReviewResponse>(`/claims/${claimId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getReviews(claimId: string): Promise<ReviewResponse[]> {
  return apiFetch<ReviewResponse[]>(`/claims/${claimId}/reviews`);
}

export async function uploadSourcePdf(
  referenceId: string,
  file: File
): Promise<{ reference_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`/references/${referenceId}/source`, {
    method: "POST",
    body: form,
  });
}

export const exportUrl = (docId: string, format: "csv" | "pdf") =>
  `${API_BASE}/documents/${docId}/export?format=${format}`;
