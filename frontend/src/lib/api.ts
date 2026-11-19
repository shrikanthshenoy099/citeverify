/**
 * API client for CiteVerify backend.
 * All requests go through Next.js rewrites → http://localhost:8000
 */

const BASE = '/api'

export type DocumentStatus = 'pending' | 'processing' | 'done' | 'error'
export type VerdictLabel =
  | 'supported'
  | 'partly_supported'
  | 'unsupported'
  | 'contradictory'
  | 'possibly_outdated'
  | 'needs_review'

export interface VerdictItem {
  reference_id: string
  verdict: VerdictLabel
  confidence: number
  needs_human_review: boolean
  explanation: string
  flags: string[]
  evidence: null | {
    quote: string
    passage_id: string
    page: number | null
    section: string | null
  }
  confidence_breakdown: {
    retrieval: number
    llm_certainty: number
    text_match: number
    full_text: number
    numeric_match: number
  }
  source_trace: {
    doi: string | null
    url: string | null
    page: number | null
    section: string | null
  }
}

export interface ClaimItem {
  claim_id: string
  text: string
  page: number | null
  section: string | null
  claim_type: string
  citation_markers: string[]
  reference_ids: string[]
  numbers_mentioned: string[]
  flags: string[]
  verdicts: VerdictItem[]
}

export interface ReferenceItem {
  reference_id: string
  title: string | null
  authors: string[]
  year: number | null
  doi: string | null
  venue: string | null
  parse_confidence: number
}

export interface DocumentResults {
  doc_id: string
  status: DocumentStatus
  source_type: string
  num_pages: number | null
  warnings: string[]
  references: ReferenceItem[]
  claims: ClaimItem[]
}

export interface DocumentStatusResponse {
  doc_id: string
  status: DocumentStatus
  source_type: string
  num_pages: number | null
  warnings: string[]
  num_claims: number
  num_references: number
}

/** Upload a file or paste text. Returns {doc_id, status}. */
export async function uploadDocument(
  fileOrText: File | string
): Promise<{ doc_id: string; status: string }> {
  const form = new FormData()
  if (typeof fileOrText === 'string') {
    form.append('text', fileOrText)
  } else {
    form.append('file', fileOrText)
  }
  const res = await fetch(`${BASE}/documents`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/** Poll processing status. */
export async function getDocumentStatus(docId: string): Promise<DocumentStatusResponse> {
  const res = await fetch(`${BASE}/documents/${docId}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/** Fetch the full results once status === 'done'. */
export async function getDocumentResults(docId: string): Promise<DocumentResults> {
  const res = await fetch(`${BASE}/documents/${docId}/results`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/** Submit a human review. */
export async function submitReview(
  claimId: string,
  body: { action: string; new_verdict?: string; comment: string; reviewer: string }
): Promise<unknown> {
  const res = await fetch(`${BASE}/claims/${claimId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/** Export URL (open in new tab). */
export function exportUrl(docId: string, format: 'csv' | 'pdf'): string {
  return `${BASE}/documents/${docId}/export?format=${format}`
}
