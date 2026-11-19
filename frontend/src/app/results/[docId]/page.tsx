"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { getDocumentStatus, getDocumentResults, exportCsv } from "@/lib/api";
import type { ClaimWithVerdicts, DocumentResults, VerdictLabel } from "@/lib/types";
import { ClaimCard } from "@/components/ClaimCard";
import { VerdictBadge } from "@/components/VerdictBadge";

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["done", "error"]);

const PIPELINE_STAGES = ["pending", "parsing", "retrieving", "verifying", "done"] as const;

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Counts per verdict label across all verdicts in results */
function countVerdicts(claims: ClaimWithVerdicts[]) {
  const counts: Partial<Record<VerdictLabel, number>> = {};
  let needsReview = 0;
  for (const c of claims) {
    for (const v of c.verdicts) {
      counts[v.verdict] = (counts[v.verdict] ?? 0) + 1;
      if (v.needs_human_review) needsReview++;
    }
  }
  return { counts, needsReview };
}

function StageBar({ status }: { status: string }) {
  const idx = PIPELINE_STAGES.indexOf(status as typeof PIPELINE_STAGES[number]);
  const labels: Record<string, string> = {
    pending: "Queued",
    parsing: "Parsing document",
    retrieving: "Retrieving sources",
    verifying: "Verifying claims",
    done: "Complete",
  };
  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 mb-6">
      <div className="flex items-center gap-1 mb-2 flex-wrap">
        {PIPELINE_STAGES.map((stage, i) => (
          <div key={stage} className="flex items-center gap-1">
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium transition-colors ${
                stage === status
                  ? "bg-blue-600 text-white animate-pulse"
                  : i < idx
                  ? "bg-blue-200 text-blue-800"
                  : "bg-gray-100 text-gray-400"
              }`}
            >
              {labels[stage]}
            </span>
            {i < PIPELINE_STAGES.length - 1 && (
              <span className="text-gray-300 text-xs">→</span>
            )}
          </div>
        ))}
      </div>
      <div className="w-full bg-blue-100 rounded-full h-1.5">
        <div
          className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
          style={{ width: `${Math.max(5, (Math.max(0, idx) / (PIPELINE_STAGES.length - 1)) * 100)}%` }}
        />
      </div>
    </div>
  );
}

function SummaryCards({
  claims,
  needsReview,
  counts,
}: {
  claims: ClaimWithVerdicts[];
  needsReview: number;
  counts: Partial<Record<VerdictLabel, number>>;
}) {
  const verdictOrder: VerdictLabel[] = [
    "supported", "partly_supported", "unsupported",
    "contradictory", "possibly_outdated", "needs_review",
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      <div className="bg-white border border-gray-200 rounded-lg p-3">
        <div className="text-2xl font-bold text-gray-900">{claims.length}</div>
        <div className="text-xs text-gray-500 mt-0.5">Claims found</div>
      </div>
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
        <div className="text-2xl font-bold text-amber-700">{needsReview}</div>
        <div className="text-xs text-amber-600 mt-0.5">Needs human review</div>
      </div>
      {verdictOrder.filter((v) => counts[v]).map((v) => (
        <div key={v} className="bg-white border border-gray-200 rounded-lg p-3 flex items-center gap-2">
          <div className="text-xl font-bold text-gray-900">{counts[v]}</div>
          <VerdictBadge verdict={v} />
        </div>
      ))}
    </div>
  );
}

type FilterState = {
  verdict: VerdictLabel | "all";
  needsReview: "all" | "yes" | "no";
  flag: string;
  reviewed: "all" | "yes" | "no";
  search: string;
};

export default function ResultsPage() {
  const { docId } = useParams<{ docId: string }>();
  const [status, setStatus] = useState<string>("pending");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [results, setResults] = useState<DocumentResults | null>(null);
  const [exporting, setExporting] = useState<"csv" | "print" | null>(null);
  const [filters, setFilters] = useState<FilterState>({
    verdict: "all",
    needsReview: "all",
    flag: "",
    reviewed: "all",
    search: "",
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchResults = useCallback(async () => {
    try {
      const data = await getDocumentResults(docId);
      setResults(data);
      setStatus(data.status);
    } catch {
      // results not ready yet – fine
    }
  }, [docId]);

  // Poll status and also fetch partial results during pipeline
  useEffect(() => {
    intervalRef.current = setInterval(async () => {
      try {
        const s = await getDocumentStatus(docId);
        setStatus(s.status);
        setErrorMsg(s.error_message ?? null);
        // Fetch partial results at every poll so table updates incrementally
        fetchResults();
        if (TERMINAL_STATUSES.has(s.status)) {
          clearInterval(intervalRef.current!);
        }
      } catch {
        clearInterval(intervalRef.current!);
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [docId, fetchResults]);

  async function handleExportCsv() {
    setExporting("csv");
    try {
      const blob = await exportCsv(docId);
      downloadBlob(blob, `citeverify-${docId}.csv`);
    } catch (err) {
      alert(`Export failed: ${err}`);
    } finally {
      setExporting(null);
    }
  }

  function handlePrint() {
    window.print();
  }

  // Collect all unique flags across verdicts for the flag filter dropdown
  const allFlags = results
    ? Array.from(new Set(results.claims.flatMap((c) => [
        ...c.flags,
        ...c.verdicts.flatMap((v) => v.flags),
      ]))).sort()
    : [];

  // Apply filters
  const filteredClaims: ClaimWithVerdicts[] = (results?.claims ?? []).filter((claim) => {
    if (filters.search) {
      const q = filters.search.toLowerCase();
      if (
        !claim.text.toLowerCase().includes(q) &&
        !claim.citation_markers.join(" ").toLowerCase().includes(q)
      )
        return false;
    }
    if (filters.needsReview === "yes" && !claim.verdicts.some((v) => v.needs_human_review))
      return false;
    if (filters.needsReview === "no" && claim.verdicts.some((v) => v.needs_human_review))
      return false;
    if (filters.verdict !== "all" && !claim.verdicts.some((v) => v.verdict === filters.verdict))
      return false;
    if (filters.flag && !claim.flags.includes(filters.flag) &&
        !claim.verdicts.some((v) => v.flags.includes(filters.flag)))
      return false;
    return true;
  });

  const { counts, needsReview } = results
    ? countVerdicts(results.claims)
    : { counts: {}, needsReview: 0 };

  return (
    <>
      {/* Print-only disclaimer */}
      <div className="hidden print:block text-xs text-center border border-gray-300 rounded p-2 mb-4">
        Automated analysis to assist human review. Not a final academic judgment.
        Results must be independently verified.
      </div>

      <div className="print:hidden">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold">Verification results</h1>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{docId}</p>
          </div>
          {results && status === "done" && (
            <div className="flex gap-2">
              <button
                onClick={handleExportCsv}
                disabled={exporting !== null}
                className="text-xs bg-white border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50"
              >
                {exporting === "csv" ? "Exporting…" : "Export CSV"}
              </button>
              <button
                onClick={handlePrint}
                className="text-xs bg-white border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
              >
                Print / Save as PDF
              </button>
            </div>
          )}
        </div>

        {/* Stage progress bar */}
        {!TERMINAL_STATUSES.has(status) && <StageBar status={status} />}

        {status === "error" && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-6 text-sm text-red-700">
            <strong>Pipeline error:</strong> {errorMsg ?? "Unknown error."}
          </div>
        )}

        {/* Disclaimer */}
        <div className="bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-800 mb-4">
          Automated analysis to assist human review. <strong>Not a final academic judgment.</strong>{" "}
          Confidence scores are not a guarantee of accuracy.
        </div>
      </div>

      {/* Results — visible during pipeline too (partial) */}
      {results && (
        <>
          {/* Summary cards */}
          <SummaryCards claims={results.claims} needsReview={needsReview} counts={counts} />

          {/* Filters */}
          <div className="flex flex-wrap gap-2 mb-4 print:hidden">
            <input
              type="search"
              placeholder="Search claims…"
              value={filters.search}
              onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs flex-1 min-w-[180px] focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <select
              value={filters.verdict}
              onChange={(e) => setFilters((f) => ({ ...f, verdict: e.target.value as FilterState["verdict"] }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs"
            >
              <option value="all">All verdicts</option>
              <option value="supported">Supported</option>
              <option value="partly_supported">Partly supported</option>
              <option value="unsupported">Unsupported</option>
              <option value="contradictory">Contradictory</option>
              <option value="possibly_outdated">Possibly outdated</option>
              <option value="needs_review">Needs review</option>
            </select>
            <select
              value={filters.needsReview}
              onChange={(e) => setFilters((f) => ({ ...f, needsReview: e.target.value as FilterState["needsReview"] }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs"
            >
              <option value="all">Any review status</option>
              <option value="yes">Needs human review</option>
              <option value="no">No review needed</option>
            </select>
            {allFlags.length > 0 && (
              <select
                value={filters.flag}
                onChange={(e) => setFilters((f) => ({ ...f, flag: e.target.value }))}
                className="border border-gray-300 rounded px-2 py-1 text-xs"
              >
                <option value="">Any flag</option>
                {allFlags.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            )}
            {(filters.search || filters.verdict !== "all" || filters.needsReview !== "all" || filters.flag) && (
              <button
                onClick={() => setFilters({ verdict: "all", needsReview: "all", flag: "", reviewed: "all", search: "" })}
                className="text-xs text-gray-500 hover:text-gray-700 underline"
              >
                Clear filters
              </button>
            )}
          </div>

          <div className="text-xs text-gray-500 mb-3">
            Showing {filteredClaims.length} of {results.claims.length} claim{results.claims.length !== 1 ? "s" : ""}
            {status !== "done" && <span className="ml-2 text-blue-500 animate-pulse">· pipeline still running…</span>}
          </div>

          <div className="space-y-3">
            {filteredClaims.map((claim) => (
              <ClaimCard
                key={claim.claim_id}
                claim={claim}
                references={results.references}
                onRefresh={fetchResults}
              />
            ))}
          </div>

          {filteredClaims.length === 0 && (
            <p className="text-gray-500 text-sm mt-6 text-center">
              {results.claims.length === 0
                ? "No verifiable claims were found in this document."
                : "No claims match the current filters."}
            </p>
          )}
        </>
      )}

      {/* Print styles */}
      <style>{`
        @media print {
          .print\\:hidden { display: none !important; }
          .print\\:block { display: block !important; }
          body { background: white; }
          .border { border-color: #e5e7eb !important; }
        }
      `}</style>
    </>
  );
}
