"use client";

import { useState } from "react";
import type { VerdictOut } from "@/lib/api";
import { VerdictBadge, ConfidenceBar, FlagList } from "@/components/VerdictBadge";
import ReviewPanel from "@/components/ReviewPanel";

interface Props {
  claimId: string;
  claimText: string;
  page: number | null;
  section: string | null;
  claimType: string;
  flags: string[];
  verdicts: VerdictOut[];
}

export default function ClaimCard({
  claimId,
  claimText,
  page,
  section,
  claimType,
  flags,
  verdicts,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [reviewingRef, setReviewingRef] = useState<string | null>(null);

  const needsReview = verdicts.some((v) => v.needs_human_review);

  return (
    <div
      className={`border rounded-lg bg-white overflow-hidden mb-4 ${
        needsReview ? "border-amber-300" : "border-gray-200"
      }`}
    >
      {/* Header */}
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded((x) => !x)}
      >
        <span className="mt-0.5 text-gray-400 text-xs select-none">
          {expanded ? "▾" : "▸"}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-800 leading-snug line-clamp-2">
            {claimText}
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-1.5">
            <span className="text-xs text-gray-400">
              {section ?? "§ unknown"}{page != null ? ` · p.${page}` : ""}
              {" · "}
              <span className="italic">{claimType}</span>
            </span>
            {verdicts.map((v) => (
              <VerdictBadge key={v.reference_id} verdict={v.verdict} />
            ))}
            {needsReview && (
              <span className="text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">
                Human review needed
              </span>
            )}
          </div>
          <FlagList flags={flags} />
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-4">
          {verdicts.map((v) => (
            <div key={v.reference_id} className="space-y-2">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <VerdictBadge verdict={v.verdict} />
                  <span className="text-xs text-gray-500 font-mono">
                    {v.reference_id}
                  </span>
                </div>
                <ConfidenceBar value={v.confidence} />
              </div>

              <p className="text-sm text-gray-700">{v.explanation}</p>

              {/* Evidence quote */}
              {v.evidence?.quote && (
                <blockquote className="text-sm italic text-gray-600 border-l-4 border-blue-200 pl-3 py-1 bg-blue-50 rounded-r">
                  &ldquo;{v.evidence.quote}&rdquo;
                  {v.evidence.page != null && (
                    <span className="not-italic text-xs text-gray-400 ml-2">
                      p.{v.evidence.page}
                      {v.evidence.section ? ` · ${v.evidence.section}` : ""}
                    </span>
                  )}
                </blockquote>
              )}

              {/* Source trace */}
              {v.source_trace?.doi && (
                <p className="text-xs text-gray-400">
                  Source:{" "}
                  <a
                    href={`https://doi.org/${v.source_trace.doi}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 underline"
                  >
                    {v.source_trace.doi}
                  </a>
                </p>
              )}

              <FlagList flags={v.flags} />

              {v.needs_human_review && (
                <div className="mt-2">
                  {reviewingRef === v.reference_id ? (
                    <ReviewPanel
                      claimId={claimId}
                      referenceId={v.reference_id}
                      onDone={() => setReviewingRef(null)}
                    />
                  ) : (
                    <button
                      onClick={() => setReviewingRef(v.reference_id)}
                      className="text-xs bg-amber-50 border border-amber-300 text-amber-700 hover:bg-amber-100 px-3 py-1.5 rounded transition-colors"
                    >
                      Submit review
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
