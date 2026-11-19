"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { uploadDocument, submitText } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [tab, setTab] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setLoading(true);
    try {
      const { doc_id } = await uploadDocument(file);
      router.push(`/results/${doc_id}`);
    } catch (err) {
      setError(String(err));
      setLoading(false);
    }
  }

  async function handleTextSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const { doc_id } = await submitText(text);
      router.push(`/results/${doc_id}`);
    } catch (err) {
      setError(String(err));
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-2">Verify scientific claims</h1>
      <p className="text-gray-600 mb-6 text-sm">
        Upload a PDF or DOCX, or paste text. CiteVerify will extract checkable
        claims, locate the cited papers, and produce a claim-by-claim
        verification report.
      </p>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {(["file", "text"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "file" ? "Upload file" : "Paste text"}
          </button>
        ))}
      </div>

      {tab === "file" ? (
        <label className="block border-2 border-dashed border-gray-300 rounded-lg p-10 text-center cursor-pointer hover:border-blue-400 transition-colors">
          <input
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            onChange={handleFileUpload}
            disabled={loading}
          />
          <span className="text-4xl block mb-2">📄</span>
          <span className="text-gray-600 text-sm">
            Drop a PDF or DOCX here, or <span className="text-blue-600 underline">click to browse</span>
          </span>
          <span className="text-gray-400 text-xs block mt-1">Max 50 MB</span>
        </label>
      ) : (
        <form onSubmit={handleTextSubmit} className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the text of your paper here …"
            rows={10}
            className="w-full border border-gray-300 rounded-lg p-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
          <button
            type="submit"
            disabled={loading || !text.trim()}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Submitting…" : "Verify claims"}
          </button>
        </form>
      )}

      {loading && (
        <p className="mt-4 text-blue-600 text-sm animate-pulse">
          Uploading and queuing document…
        </p>
      )}
      {error && (
        <p className="mt-4 text-red-600 text-sm bg-red-50 border border-red-200 rounded p-3">
          {error}
        </p>
      )}
    </div>
  );
}
