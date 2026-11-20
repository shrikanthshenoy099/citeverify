"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const SAMPLE_TEXT = `Results

BERT obtained a new state-of-the-art GLUE score of 80.5% [1].
BERT-large has 500 million parameters [1].

References
[1] Devlin, J., Chang, M., Lee, K., Toutanova, K. BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. NAACL 2019.`;

export default function HomePage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    let active = true;
    const checkHealth = async () => {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!active) return;
        setBackendStatus(res.ok ? "online" : "offline");
      } catch {
        if (active) setBackendStatus("offline");
      }
    };
    checkHealth();
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!text.trim()) {
      setError("Please paste draft text and references before verifying.");
      return;
    }

    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("text", text);

      const res = await fetch("/api/documents", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Request failed with status ${res.status}`);
      }

      const data = await res.json();
      const docId = data.doc_id ?? data.id ?? data.document_id;

      if (!docId) {
        throw new Error("Backend responded without a document ID.");
      }

      router.push(`/results/${encodeURIComponent(String(docId))}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit document.");
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Bar */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-indigo-500/20 border border-indigo-400/40 flex items-center justify-center text-indigo-300 font-bold text-sm">
              CV
            </div>
            <div>
              <span className="font-semibold tracking-tight text-white">CiteVerify</span>
              <span className="ml-2 text-xs text-slate-400 hidden sm:inline">
                Citation &amp; Claim Verification
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span
              className={`h-2 w-2 rounded-full ${
                backendStatus === "online"
                  ? "bg-emerald-400"
                  : backendStatus === "checking"
                  ? "bg-amber-400 animate-pulse"
                  : "bg-rose-400"
              }`}
            />
            <span className="text-slate-300">
              API:{" "}
              {backendStatus === "online"
                ? "Connected"
                : backendStatus === "checking"
                ? "Checking..."
                : "Unreachable"}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-5xl w-full mx-auto px-6 py-10">
        <div className="max-w-2xl mb-8">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
            Verify citations and claims before you publish.
          </h1>
          <p className="mt-3 text-slate-400 text-sm sm:text-base leading-relaxed">
            Paste a section of academic or technical writing along with its references.
            CiteVerify extracts claims, matches sources, and highlights unsupported statements.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 sm:p-6 shadow-xl space-y-5"
        >
          <div className="flex items-center justify-between gap-4">
            <label htmlFor="doc-text" className="text-sm font-medium text-slate-200">
              Document Text &amp; References
            </label>
            <button
              type="button"
              onClick={() => {
                setText(SAMPLE_TEXT);
                setError(null);
              }}
              className="text-xs font-medium text-indigo-400 hover:text-indigo-300 transition"
            >
              Load sample text
            </button>
          </div>

          <textarea
            id="doc-text"
            rows={11}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste your paragraph and numbered/formatted references here..."
            className="w-full rounded-xl bg-slate-950 border border-slate-800 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 outline-none p-4 text-sm text-slate-100 placeholder:text-slate-500 font-mono leading-relaxed"
          />

          {error && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
              {error}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-4 pt-1">
            <p className="text-xs text-slate-400">
              Submits form data to <code className="text-slate-300">/api/documents</code>
            </p>
            <div className="flex items-center gap-3">
              {text && (
                <button
                  type="button"
                  onClick={() => {
                    setText("");
                    setError(null);
                  }}
                  className="px-4 py-2.5 rounded-xl text-sm font-medium text-slate-300 hover:bg-slate-800 transition"
                >
                  Clear
                </button>
              )}
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white transition cursor-pointer"
              >
                {submitting ? "Submitting..." : "Verify Citations"}
              </button>
            </div>
          </div>
        </form>
      </main>
    </div>
  );
}