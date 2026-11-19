/**
 * lib/api.ts – Typed API client for the CiteVerify backend.
 *
 * Uses the Next.js rewrite (/api/* → http://localhost:8000/api/*) so no
 * CORS headers are needed in development.
 */

import type {
  ClaimWithVerdicts,
  DocumentResults,
  DocumentStatus,
  Review,
  ReviewAction,
  VerdictLabel,
} from "./types";

const BASE = "/api";

// ── helpers ──────────────────────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Documents ─────────────────────────────────────────────────────────────────

/** Upload a PDF/DOCX file. Returns { doc_id, status }. */
export async function uploadDocument(file: File): Promise<{ doc_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/documents`, { method: "POST", body: form });
  return handleResponse(res);
}

/** Submit pasted text. Returns { doc_id, status }. */
export async function submitText(text: string): Promise<{ doc_id: string; status: string }> {
  const form = new FormData();
  form.append("text", text);
  const res = await fetch(`${BASE}/documents`, { method: "POST", body: form });
  return handleResponse(res);
}

/** Poll document status. */
export async function getDocumentStatus(docId: string): Promise<DocumentStatus> {
  const res = await fetch(`${BASE}/documents/${docId}/status`);
  return handleResponse(res);
}

/** Fetch full results (claims + verdicts). */
export async function getDocumentResults(docId: string): Promise<DocumentResults> {
  const res = await fetch(`${BASE}/documents/${docId}/results`);
  return handleResponse(res);
}

/** Trigger CSV export; returns a Blob. */
export async function exportCsv(docId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/documents/${docId}/export?format=csv`);
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  return res.blob();
}

/** Trigger PDF export; returns a Blob. */
export async function exportPdf(docId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/documents/${docId}/export?format=pdf`);
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  return res.blob();
}

// ── Claims ────────────────────────────────────────────────────────────────────

export async function getClaim(claimId: string): Promise<ClaimWithVerdicts> {
  const res = await fetch(`${BASE}/claims/${claimId}`);
  return handleResponse(res);
}

// ── Reviews ───────────────────────────────────────────────────────────────────

export interface ReviewPayload {
  reference_id: string;
  action: ReviewAction;
  new_verdict?: VerdictLabel | null;
  comment?: string;
  reviewer: string;
}

export async function postReview(
  claimId: string,
  payload: ReviewPayload,
): Promise<{ review_id: string; timestamp: string }> {
  const res = await fetch(`${BASE}/claims/${claimId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse(res);
}

export async function getReviews(claimId: string): Promise<Review[]> {
  const res = await fetch(`${BASE}/claims/${claimId}/reviews`);
  return handleResponse(res);
}

// ── Sources ───────────────────────────────────────────────────────────────────

export async function uploadManualSource(
  referenceId: string,
  file: File,
): Promise<{ reference_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/references/${referenceId}/source`, {
    method: "POST",
    body: form,
  });
  return handleResponse(res);
}
