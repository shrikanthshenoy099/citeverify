'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import {
  getDocumentStatus,
  getDocumentResults,
  exportUrl,
  submitReview,
  DocumentResults,
  VerdictItem,
  ClaimItem,
} from '@/lib/api'

const VERDICT_STYLES: Record<string, string> = {
  supported: 'bg-green-100 text-green-800 border-green-300',
  partly_supported: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  unsupported: 'bg-red-100 text-red-800 border-red-300',
  contradictory: 'bg-purple-100 text-purple-800 border-purple-300',
  possibly_outdated: 'bg-orange-100 text-orange-800 border-orange-300',
  needs_review: 'bg-gray-100 text-gray-700 border-gray-300',
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const cls = VERDICT_STYLES[verdict] ?? 'bg-gray-100 text-gray-700 border-gray-300'
  return (
    <span className={`inline-block border rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${cls}`}>
      {verdict.replace(/_/g, ' ')}
    </span>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-green-500' : pct >= 45 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-200 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  )
}

function ReviewForm({
  claimId,
  onDone,
}: {
  claimId: string
  onDone: () => void
}) {
  const [action, setAction] = useState('comment')
  const [newVerdict, setNewVerdict] = useState('')
  const [comment, setComment] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!reviewer.trim()) { setErr('Reviewer name required.'); return }
    setSubmitting(true)
    setErr(null)
    try {
      await submitReview(claimId, {
        action,
        new_verdict: action === 'override' ? newVerdict : undefined,
        comment,
        reviewer,
      })
      onDone()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mt-3 bg-gray-50 border border-gray-200 rounded p-3 space-y-2 text-sm">
      <div className="flex gap-2 flex-wrap">
        {['accept', 'reject', 'comment', 'override'].map(a => (
          <button
            key={a}
            onClick={() => setAction(a)}
            className={`px-2 py-1 rounded text-xs border ${action === a ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
          >
            {a}
          </button>
        ))}
      </div>
      {action === 'override' && (
        <select
          className="border rounded px-2 py-1 text-xs w-full"
          value={newVerdict}
          onChange={e => setNewVerdict(e.target.value)}
        >
          <option value="">— select new verdict —</option>
          {['supported','partly_supported','unsupported','contradictory','possibly_outdated','needs_review'].map(v => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      )}
      <textarea
        className="w-full border rounded px-2 py-1 text-xs h-14 resize-none"
        placeholder="Comment (optional)"
        value={comment}
        onChange={e => setComment(e.target.value)}
      />
      <input
        className="border rounded px-2 py-1 text-xs w-full"
        placeholder="Your name (required)"
        value={reviewer}
        onChange={e => setReviewer(e.target.value)}
      />
      {err && <p className="text-red-600 text-xs">{err}</p>}
      <button
        onClick={handleSubmit}
        disabled={submitting}
        className="bg-blue-600 disabled:bg-blue-300 text-white text-xs rounded px-3 py-1"
      >
        {submitting ? 'Submitting…' : 'Submit Review'}
      </button>
    </div>
  )
}

function ClaimCard({ claim }: { claim: ClaimItem }) {
  const [expanded, setExpanded] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
      {/* Claim text */}
      <p className="text-sm">{claim.text}</p>

      {/* Meta */}
      <div className="flex flex-wrap gap-2 text-xs text-gray-500">
        {claim.page && <span>p.{claim.page}</span>}
        {claim.section && <span>§ {claim.section}</span>}
        <span className="font-medium text-gray-700">{claim.claim_type}</span>
        {claim.flags.map(f => (
          <span key={f} className="bg-gray-100 border border-gray-200 rounded px-1">{f}</span>
        ))}
      </div>

      {/* Verdicts */}
      {claim.verdicts.length === 0 ? (
        <p className="text-xs text-gray-400 italic">No citations verified.</p>
      ) : (
        claim.verdicts.map((v: VerdictItem) => (
          <div key={v.reference_id} className="border border-gray-100 rounded p-2 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <VerdictBadge verdict={v.verdict} />
              <ConfidenceBar value={v.confidence} />
              {v.needs_human_review && (
                <span className="text-xs bg-amber-100 border border-amber-300 text-amber-800 rounded px-1 py-0.5">
                  ⚠ human review required
                </span>
              )}
            </div>
            <p className="text-xs text-gray-600">{v.explanation}</p>
            {v.evidence?.quote && (
              <blockquote className="text-xs italic border-l-2 border-blue-300 pl-2 text-gray-600">
                "{v.evidence.quote}"
              </blockquote>
            )}
            {v.source_trace.doi && (
              <a
                href={`https://doi.org/${v.source_trace.doi}`}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-600 underline"
              >
                doi:{v.source_trace.doi}
              </a>
            )}
          </div>
        ))
      )}

      {/* Review toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setReviewing(r => !r)}
          className="text-xs text-blue-600 underline"
        >
          {reviewing ? 'Cancel review' : 'Add review'}
        </button>
        {claim.verdicts.length > 0 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-xs text-gray-500 underline"
          >
            {expanded ? 'Hide details' : 'Show confidence breakdown'}
          </button>
        )}
      </div>

      {expanded && claim.verdicts.map(v => (
        <div key={v.reference_id + '_bd'} className="text-xs bg-gray-50 rounded p-2 space-y-1">
          <p className="font-medium">Confidence breakdown – {v.reference_id}</p>
          {Object.entries(v.confidence_breakdown).map(([k, val]) => (
            <div key={k} className="flex justify-between">
              <span className="text-gray-500">{k}</span>
              <span>{(val as number).toFixed(2)}</span>
            </div>
          ))}
        </div>
      ))}

      {reviewing && (
        <ReviewForm claimId={claim.claim_id} onDone={() => setReviewing(false)} />
      )}
    </div>
  )
}

export default function ResultsPage() {
  const { docId } = useParams<{ docId: string }>()
  const [results, setResults] = useState<DocumentResults | null>(null)
  const [status, setStatus] = useState<string>('pending')
  const [error, setError] = useState<string | null>(null)

  const poll = useCallback(async () => {
    try {
      const s = await getDocumentStatus(docId)
      setStatus(s.status)
      if (s.status === 'done') {
        const r = await getDocumentResults(docId)
        setResults(r)
      } else if (s.status === 'error') {
        setError('Pipeline failed. See backend logs.')
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [docId])

  useEffect(() => {
    poll()
    if (status === 'pending' || status === 'processing') {
      const id = setInterval(poll, 2000)
      return () => clearInterval(id)
    }
  }, [poll, status])

  if (error) {
    return <p className="text-red-600 bg-red-50 border border-red-200 rounded p-4">{error}</p>
  }

  if (!results) {
    return (
      <div className="space-y-3">
        <p className="text-gray-600">Processing… status: <strong>{status}</strong></p>
        <div className="animate-pulse h-4 bg-gray-200 rounded w-1/3" />
        <div className="animate-pulse h-4 bg-gray-200 rounded w-1/2" />
        <div className="animate-pulse h-4 bg-gray-200 rounded w-2/5" />
      </div>
    )
  }

  const needsReview = results.claims.flatMap(c => c.verdicts).filter(v => v.needs_human_review)

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold">Verification Report</h1>
          <p className="text-sm text-gray-500 font-mono">{docId}</p>
        </div>
        <div className="flex gap-2">
          <a
            href={exportUrl(docId, 'csv')}
            className="text-xs bg-white border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
          >
            ↓ CSV
          </a>
          <a
            href={exportUrl(docId, 'pdf')}
            className="text-xs bg-white border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
          >
            ↓ PDF
          </a>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
        <strong>⚠ Research assistant only.</strong> This report must not be treated as a final
        academic judgment. {needsReview.length > 0 && (
          <span>{needsReview.length} verdict(s) require human review.</span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 text-center">
        {[
          ['Claims', results.claims.length],
          ['References', results.references.length],
          ['Need review', needsReview.length],
        ].map(([label, val]) => (
          <div key={String(label)} className="bg-white border border-gray-200 rounded-lg py-4">
            <div className="text-2xl font-bold">{val}</div>
            <div className="text-xs text-gray-500 mt-1">{label}</div>
          </div>
        ))}
      </div>

      {/* Warnings */}
      {results.warnings.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-3 text-xs space-y-1">
          <p className="font-medium text-yellow-900">Processing warnings:</p>
          {results.warnings.map((w, i) => (
            <p key={i} className="font-mono text-yellow-800">{w}</p>
          ))}
        </div>
      )}

      {/* Claims */}
      <div className="space-y-3">
        {results.claims.length === 0 ? (
          <p className="text-gray-500 italic text-sm">No checkable claims found.</p>
        ) : (
          results.claims.map(claim => <ClaimCard key={claim.claim_id} claim={claim} />)
        )}
      </div>
    </div>
  )
}
