/**
 * components/PdfHighlightViewer.tsx – renders a PDF page with evidence highlight.
 *
 * Uses react-pdf (pdfjs-dist) to render the page, then draws SVG rectangles
 * over the evidence bboxes.
 *
 * Coordinate system: PyMuPDF origin = top-left (same as browser), points.
 * Scale: rendered_width / page_width  (same factor applied to y).
 * No Y-flip needed because PyMuPDF and browser both use top-left origin.
 *
 * Fallback: when no PDF is available, or no bboxes, shows the quote text
 * in a highlighted box with the reason.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Evidence } from "@/lib/types";

// Lazy-load react-pdf only on the client
let Document: any = null;
let Page: any = null;
let pdfjs: any = null;

async function loadPdfJs() {
  if (Document) return;
  const mod = await import("react-pdf");
  Document = mod.Document;
  Page = mod.Page;
  pdfjs = mod.pdfjs;
  pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`;
}

interface Props {
  referenceId: string;
  evidence: Evidence;
}

export function PdfHighlightViewer({ referenceId, evidence }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [pdfAvailable, setPdfAvailable] = useState<boolean | null>(null);
  const [pageWidth, setPageWidth] = useState(600);
  const [renderScale, setRenderScale] = useState(1);
  const containerRef = useRef<HTMLDivElement>(null);

  // Load react-pdf lazily
  useEffect(() => {
    loadPdfJs().then(() => setLoaded(true));
  }, []);

  // Check if PDF is available from the backend
  useEffect(() => {
    fetch(`/api/sources/${referenceId}/pdf`, { method: "HEAD" })
      .then((r) => setPdfAvailable(r.ok))
      .catch(() => setPdfAvailable(false));
  }, [referenceId]);

  const pdfUrl = `/api/sources/${referenceId}/pdf`;
  const targetPage = (evidence.page ?? 1);

  const onPageLoad = useCallback(
    (page: { width: number; height: number }) => {
      const containerW = containerRef.current?.clientWidth ?? 600;
      const srcW = evidence.page_width ?? page.width;
      const scale = containerW / srcW;
      setPageWidth(containerW);
      setRenderScale(scale);
    },
    [evidence.page_width],
  );

  // No bboxes or PDF unavailable → show fallback
  if (pdfAvailable === false || evidence.bboxes.length === 0) {
    return (
      <div className="border border-gray-200 rounded bg-gray-50 p-3 text-xs text-gray-600">
        <p className="font-medium text-gray-500 mb-1">
          {pdfAvailable === false
            ? "PDF not available for this source."
            : "No location data available."}
        </p>
        {evidence.quote && (
          <blockquote className="border-l-4 border-yellow-400 pl-2 italic text-gray-700 bg-yellow-50 py-1 pr-2">
            &ldquo;{evidence.quote}&rdquo;
            {evidence.page != null && <span className="ml-1 not-italic text-gray-400">(p. {evidence.page})</span>}
          </blockquote>
        )}
      </div>
    );
  }

  if (!loaded || pdfAvailable === null) {
    return (
      <div className="border border-gray-200 rounded bg-gray-50 p-3 text-xs text-gray-400 animate-pulse">
        Loading PDF viewer…
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative border border-gray-200 rounded overflow-hidden bg-gray-50">
      <Document
        file={pdfUrl}
        loading={
          <div className="p-4 text-xs text-gray-400 animate-pulse">Loading PDF…</div>
        }
        error={
          <div className="p-4 text-xs text-red-500">Failed to load PDF.</div>
        }
      >
        <div className="relative inline-block w-full">
          <Page
            pageNumber={targetPage}
            width={pageWidth}
            onLoadSuccess={onPageLoad}
            renderTextLayer={false}
            renderAnnotationLayer={false}
          />
          {/* Highlight overlay */}
          <svg
            className="absolute inset-0 pointer-events-none"
            style={{ width: "100%", height: "100%" }}
            viewBox={`0 0 ${pageWidth} ${
              evidence.page_height ? evidence.page_height * renderScale : pageWidth * 1.414
            }`}
            preserveAspectRatio="none"
          >
            {evidence.bboxes.map((bbox, i) => (
              <rect
                key={i}
                x={bbox.x0 * renderScale}
                y={bbox.y0 * renderScale}
                width={(bbox.x1 - bbox.x0) * renderScale}
                height={(bbox.y1 - bbox.y0) * renderScale}
                fill="rgba(255,220,0,0.35)"
                stroke="rgba(200,160,0,0.8)"
                strokeWidth={1}
                rx={2}
              />
            ))}
          </svg>
        </div>
      </Document>
      <div className="px-2 py-1 text-xs text-gray-400 bg-white border-t border-gray-200">
        Page {targetPage}
        {evidence.section && ` · ${evidence.section}`}
        {" · "}
        <span className="italic">&ldquo;{evidence.quote?.slice(0, 80)}{(evidence.quote?.length ?? 0) > 80 ? "…" : ""}&rdquo;</span>
      </div>
    </div>
  );
}
