"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  getStatus,
  getResults,
  exportUrl,
  type DocumentResults,
  type DocumentStatus,
} from "@/lib/api";
import ClaimCard from "@/components/ClaimCard";
import Link from "next/link";

const POLL_INTERVAL_MS = 2000;

export default function ResultsPage() {
  const params = useParams();
  const docId = params.docId as string;

  const [status, setStatus] = useState<DocumentStatus | null>(null);
  const [results, setResults] = useState<DocumentResults | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  // Polling for status
  useEffect(() => {
    if (!docId) return;

    const poll = async () => {
      try {
        const s = await getStatus(docId);
        setStatus(s);

        if (s.status === "done") {
          if (intervalRef.current) clearInterval(intervalRef.current);
          const r = await getResults(docId);
          setResults(r);
        } else if (s.status === "error") {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load.");
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    };

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [docId]);

  const needsReviewCount =
    results?.claims.reduce(
      (n, c) => n + (c.verdicts.some((v) => v.needs_human_review) ? 1 : 0),
      0
    ) ?? 0;

  return (
    <div>
      {/* Back link */}
      <Link href="/" className="text-sm text-blue-500 hover:underline mb-4 block">
        ← Upload another document
      </Link>

      <h1 className="text-xl font-semibold mb-1">Verification Report</h1>
      <p className="text-xs text-gray-400 font-mono mb-4">{docId}</p>

      {/* Status bar */}
      {status && (
        <div
          className={`rounded-lg px-4 py-3 mb-5 text-sm flex items-center justify-between ${
            status.status === "done"
              ? "bg-green-50 border border-green-200 text-green-800"
              : status.status === "error"
              ? "bg-red-50 border border-red-200 text-red-800"
              : "bg-blue-50 border border-blue-200 text-blue-800"
          }`}
        >
          <span>
            {status.status === "pending" && "⏳ Queued…"}
            {status.status === "processing" && "⚙️  Processing…"}
            {status.status === "done" &&
              `✓ Done — ${results?.claims.length ?? 0} claims found${
                status.num_pages ? ` across ${status.num_pages} pages` : ""
              }`}
            {status.status === "error" &&
              `✗ Error: ${status.error_message ?? "unknown"}`}
          </span>

          {status.status === "done" && (
            <div className="flex gap-2">
              <a
                href={exportUrl(docId, "csv")}
                className="text-xs underline"
              >
                Export CSV
              </a>
              <a
                href={exportUrl(docId, "pdf")}
                className="text-xs underline"
              >
                Export PDF
              </a>
            </div>
          )}
        </div>
      )}

      {/* Warnings */}
      {status?.warnings && status.warnings.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded px-4 py-3 mb-4">
          <p className="text-xs font-medium text-yellow-800 mb-1">Warnings</p>
          <ul className="text-xs text-yellow-700 list-disc pl-4 space-y-0.5">
            {status.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Human review summary */}
      {results && needsReviewCount > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded px-4 py-3 mb-5 text-sm text-amber-800">
          <strong>{needsReviewCount}</strong> claim
          {needsReviewCount !== 1 ? "s" : ""} require human review. Claims
          marked below — click to expand and submit your review.
        </div>
      )}

      {/* Loading spinner */}
      {!results && !error && (
        <div className="text-center py-16">
          <div className="inline-block w-8 h-8 border-4 border-blue-200 border-t-blue-500 rounded-full animate-spin" />
          <p className="text-sm text-gray-400 mt-3">Processing…</p>
        </div>
      )}

      {error && (
        <p className="text-red-600 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </p>
      )}

      {/* Claims list */}
      {results && results.claims.length === 0 && (
        <p className="text-gray-500 text-sm">
          No checkable claims were found in this document.
        </p>
      )}

      {results &&
        results.claims.map((claim) => (
          <ClaimCard
            key={claim.claim_id}
            claimId={claim.claim_id}
            claimText={claim.text}
            page={claim.page}
            section={claim.section}
            claimType={claim.claim_type}
            flags={claim.flags}
            verdicts={claim.verdicts}
          />
        ))}
    </div>
  );
}
