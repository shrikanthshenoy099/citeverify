/**
 * components/ClaimCard.tsx – expandable card for a claim and its verdicts.
 *
 * Shows: claim text + context, citation markers, matched publication details,
 * evidence quote (with page/section), verdict + explanation, confidence
 * breakdown (5 components) with "not a guarantee" notice, source trace,
 * flags with plain-English descriptions, special notices for key flags,
 * PDF highlight viewer, human review panel, manual source upload.
 */

"use client";

import { useState } from "react";
import type { ClaimWithVerdicts, Reference, Verdict } from "@/lib/types";
import { VerdictBadge } from "./VerdictBadge";
import { FlagBadge } from "./FlagBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { ReviewPanel } from "./ReviewPanel";
import { ManualSourceUpload } from "./ManualSourceUpload";
import { PdfHighlightViewer } from "./PdfHighlightViewer";
import { FLAGS } from "@/lib/types";

interface Props {
  claim: ClaimWithVerdicts;
  references?: Reference[];
  onRefresh: () => void;
}

export function ClaimCard({ claim, references = [], onRefresh }: Props) {
  const [expanded, setExpanded] = useState(false);

  const topVerdict = claim.verdicts[0] ?? null;
  const needsReview = claim.verdicts.some((v) => v.needs_human_review);

  return (
    <div
      className={`border rounded-lg bg-white overflow-hidden transition-shadow ${
        needsReview ? "border-amber-300" : "border-gray-200"
      }`}
    >
      {/* Header – always visible */}
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className="mt-0.5 text-gray-400 text-xs" aria-hidden>
          {expanded ? "▼" : "▶"}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 leading-snug">{claim.text}</p>
          <div className="flex flex-wrap items-center gap-1.5 mt-1">
            {topVerdict && <VerdictBadge verdict={topVerdict.verdict} />}
            {topVerdict && (
              <span className="text-xs text-gray-400">
                {Math.round(topVerdict.confidence * 100)}% confidence
              </span>
            )}
            {needsReview && (
              <span className="text-xs bg-amber-100 text-amber-800 border border-amber-200 rounded px-1.5 py-0.5">
                Needs human review
              </span>
            )}
            {claim.flags.map((f) => (
              <FlagBadge key={f} flag={f} />
            ))}
          </div>
          {(claim.page != null || claim.section) && (
            <span className="text-xs text-gray-400 mt-0.5 block">
              {claim.page != null && `Page ${claim.page}`}
              {claim.page != null && claim.section && " · "}
              {claim.section}
            </span>
          )}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-4">
          {/* Context highlight */}
          <div className="text-xs bg-gray-50 rounded p-2 leading-relaxed font-mono">
            <span className="text-gray-400">{claim.context_before} </span>
            <mark className="bg-yellow-200 text-gray-900 rounded px-0.5">{claim.text}</mark>
            <span className="text-gray-400"> {claim.context_after}</span>
          </div>

          {/* Citation markers */}
          {claim.citation_markers.length > 0 && (
            <div className="text-xs text-gray-600">
              <span className="font-medium">Citation markers: </span>
              {claim.citation_markers.map((m) => (
                <span key={m} className="inline-block bg-gray-100 rounded px-1 mr-1">{m}</span>
              ))}
            </div>
          )}

          {/* Per-(claim, reference) verdicts */}
          {claim.verdicts.length === 0 ? (
            <p className="text-xs text-gray-500 italic">
              No verdicts yet – pipeline may still be running.
            </p>
          ) : (
            claim.verdicts.map((v) => {
              const ref = references.find((r) => r.reference_id === v.reference_id);
              return (
                <VerdictDetail
                  key={v.reference_id}
                  verdict={v}
                  reference={ref ?? null}
                  claimFlags={claim.flags}
                  onRefresh={onRefresh}
                />
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

function VerdictDetail({
  verdict,
  reference,
  claimFlags,
  onRefresh,
}: {
  verdict: Verdict;
  reference: Reference | null;
  claimFlags: string[];
  onRefresh: () => void;
}) {
  const allFlags = Array.from(new Set([...verdict.flags, ...claimFlags]));
  const [showPdf, setShowPdf] = useState(false);

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-3">
      {/* Reference / verdict header */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-mono text-gray-500">{verdict.reference_id}</span>
        <VerdictBadge verdict={verdict.verdict} />
        {verdict.needs_human_review && (
          <span className="text-xs bg-amber-100 text-amber-700 border border-amber-200 rounded px-1.5 py-0.5">
            ⚠ Human review needed
          </span>
        )}
      </div>

      {/* Matched publication details */}
      {reference && (
        <div className="text-xs bg-blue-50 border border-blue-100 rounded p-2 space-y-0.5">
          <div className="font-semibold text-gray-800">{reference.title ?? "(no title)"}</div>
          {reference.authors.length > 0 && (
            <div className="text-gray-600">{reference.authors.join(", ")}</div>
          )}
          <div className="text-gray-500 flex gap-3 flex-wrap">
            {reference.year && <span>{reference.year}</span>}
            {reference.venue && <span>{reference.venue}</span>}
            {reference.doi && (
              <a
                href={`https://doi.org/${reference.doi}`}
                target="_blank"
                rel="noreferrer"
                className="text-blue-600 hover:underline"
              >
                DOI: {reference.doi}
              </a>
            )}
          </div>
        </div>
      )}

      {/* Verdict explanation */}
      <p className="text-sm text-gray-800">{verdict.explanation}</p>

      {/* Evidence quote */}
      {verdict.evidence?.quote ? (
        <blockquote className="border-l-4 border-blue-300 pl-3 text-xs text-gray-700 italic bg-blue-50 py-1 pr-2 rounded-r">
          &ldquo;{verdict.evidence.quote}&rdquo;
          {verdict.evidence.page != null && (
            <span className="ml-1 text-gray-400 not-italic">
              (p.&nbsp;{verdict.evidence.page}
              {verdict.evidence.section ? `, ${verdict.evidence.section}` : ""})
            </span>
          )}
        </blockquote>
      ) : (
        <p className="text-xs text-gray-400 italic">No direct quote located in source.</p>
      )}

      {/* PDF highlight viewer toggle */}
      {verdict.evidence && (
        <div>
          <button
            onClick={() => setShowPdf((s) => !s)}
            className="text-xs text-blue-600 underline hover:text-blue-800"
          >
            {showPdf ? "Hide PDF viewer" : "View in PDF"}
          </button>
          {showPdf && (
            <div className="mt-2">
              <PdfHighlightViewer
                referenceId={verdict.reference_id}
                evidence={verdict.evidence}
              />
            </div>
          )}
        </div>
      )}

      {/* Confidence breakdown */}
      <ConfidenceSection verdict={verdict} />

      {/* Source trace */}
      <div className="text-xs text-gray-500 flex gap-3 flex-wrap">
        {verdict.source_trace.doi && (
          <a
            href={`https://doi.org/${verdict.source_trace.doi}`}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            DOI: {verdict.source_trace.doi}
          </a>
        )}
        {verdict.source_trace.url && !verdict.source_trace.doi && (
          <a
            href={verdict.source_trace.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline"
          >
            Source link ↗
          </a>
        )}
        {verdict.source_trace.page != null && (
          <span>Source page: {verdict.source_trace.page}</span>
        )}
        {verdict.source_trace.section && (
          <span>Section: {verdict.source_trace.section}</span>
        )}
      </div>

      {/* Flags */}
      {allFlags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {allFlags.map((f) => (
            <FlagBadge key={f} flag={f} />
          ))}
        </div>
      )}

      {/* Special flag notices */}
      <FlagNotices flags={allFlags} />

      {/* Manual source upload */}
      <ManualSourceUpload
        referenceId={verdict.reference_id}
        flags={allFlags}
        onComplete={onRefresh}
      />

      {/* Human review */}
      <ReviewPanel claimId={verdict.claim_id} referenceId={verdict.reference_id} />
    </div>
  );
}

function ConfidenceSection({ verdict }: { verdict: Verdict }) {
  const bd = verdict.confidence_breakdown;
  const components = [
    { label: "Retrieval match", value: bd.retrieval },
    { label: "LLM certainty", value: bd.llm_certainty },
    { label: "Text match", value: bd.text_match },
    { label: "Full text", value: bd.full_text },
    { label: "Numeric match", value: bd.numeric_match },
  ];
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-600">
          Confidence: {Math.round(verdict.confidence * 100)}%
        </p>
        <span className="text-xs text-gray-400 italic">
          Not a guarantee of accuracy
        </span>
      </div>
      <div className="bg-gray-200 rounded-full h-2 overflow-hidden">
        <div
          className={`h-2 rounded-full ${
            verdict.confidence >= 0.7
              ? "bg-green-500"
              : verdict.confidence >= 0.4
              ? "bg-yellow-500"
              : "bg-red-500"
          }`}
          style={{ width: `${Math.round(verdict.confidence * 100)}%` }}
        />
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-gray-500 hover:text-gray-700 select-none">
          Breakdown
        </summary>
        <div className="mt-1.5 space-y-1 pl-2 border-l border-gray-200">
          {components.map(({ label, value }) => (
            <div key={label} className="flex items-center gap-2">
              <span className="w-28 text-gray-500 shrink-0">{label}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                <div
                  className="bg-blue-400 h-1.5 rounded-full"
                  style={{ width: `${Math.round(value * 100)}%` }}
                />
              </div>
              <span className="w-8 text-right text-gray-600">{Math.round(value * 100)}%</span>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

function FlagNotices({ flags }: { flags: string[] }) {
  const notices: { flag: string; icon: string; msg: string; style: string }[] = [
    {
      flag: FLAGS.OCR_TEXT,
      icon: "🔍",
      msg: "Text was read by OCR. It may contain errors; verify the original document.",
      style: "bg-purple-50 border-purple-200 text-purple-800",
    },
    {
      flag: FLAGS.POSSIBLY_RETRACTED,
      icon: "⛔",
      msg: "This paper may have been retracted. Check Retraction Watch before trusting this result.",
      style: "bg-red-50 border-red-200 text-red-800",
    },
    {
      flag: FLAGS.MANUAL_SOURCE,
      icon: "📄",
      msg: "Source PDF was uploaded manually by a reviewer, not fetched automatically.",
      style: "bg-blue-50 border-blue-200 text-blue-800",
    },
    {
      flag: FLAGS.ABSTRACT_ONLY,
      icon: "📋",
      msg: "Only the abstract was available. Confidence is capped at 50%.",
      style: "bg-yellow-50 border-yellow-200 text-yellow-800",
    },
    {
      flag: FLAGS.FULL_TEXT_UNAVAILABLE,
      icon: "🔒",
      msg: "Full text could not be retrieved. Upload the PDF above to improve accuracy.",
      style: "bg-orange-50 border-orange-200 text-orange-800",
    },
  ];

  const active = notices.filter((n) => flags.includes(n.flag));
  if (active.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {active.map(({ flag, icon, msg, style }) => (
        <div
          key={flag}
          className={`text-xs border rounded px-2 py-1.5 flex items-start gap-1.5 ${style}`}
        >
          <span>{icon}</span>
          <span>{msg}</span>
        </div>
      ))}
    </div>
  );
}
