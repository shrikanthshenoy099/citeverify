"use client";

import { useState } from "react";
import { uploadFile, uploadText } from "@/lib/api";
import { useRouter } from "next/navigation";

export default function UploadPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let result: { doc_id: string };
      if (mode === "file") {
        if (!file) { setError("Please select a file."); setLoading(false); return; }
        result = await uploadFile(file);
      } else {
        if (!text.trim()) { setError("Please enter some text."); setLoading(false); return; }
        result = await uploadText(text);
      }
      router.push(`/results/${result.doc_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed.");
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Verify a Document</h1>
      <p className="text-gray-500 text-sm mb-6">
        Upload a PDF or DOCX, or paste text. CiteVerify will extract claims,
        find the cited papers, and produce a verification report for your
        review.
      </p>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-5">
        {(["file", "text"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium border transition-colors ${
              mode === m
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
            }`}
          >
            {m === "file" ? "Upload file" : "Paste text"}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {mode === "file" ? (
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-blue-400 transition-colors">
            <input
              type="file"
              accept=".pdf,.docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
              id="file-input"
            />
            <label htmlFor="file-input" className="cursor-pointer">
              <div className="text-gray-400 text-sm">
                {file ? (
                  <span className="text-blue-600 font-medium">{file.name}</span>
                ) : (
                  <>
                    <span className="text-blue-600 font-medium">
                      Click to browse
                    </span>{" "}
                    or drag a PDF / DOCX here
                  </>
                )}
              </div>
            </label>
          </div>
        ) : (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder="Paste your academic text here…"
            className="w-full border border-gray-300 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        )}

        {error && (
          <p className="text-red-600 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition-colors"
        >
          {loading ? "Uploading…" : "Verify document"}
        </button>
      </form>
    </div>
  );
}
