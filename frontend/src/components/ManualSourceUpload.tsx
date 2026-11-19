/**
 * components/ManualSourceUpload.tsx – "Upload the cited paper yourself" button.
 * Shown for claims whose source has flags: reference_not_found,
 * full_text_unavailable, or abstract_only.
 */

"use client";

import { useRef, useState } from "react";
import { uploadManualSource } from "@/lib/api";
import { FLAGS } from "@/lib/types";

interface Props {
  referenceId: string;
  flags: string[];
  onComplete: () => void;
}

const SHOW_FOR_FLAGS = new Set([
  FLAGS.REFERENCE_NOT_FOUND,
  FLAGS.FULL_TEXT_UNAVAILABLE,
  FLAGS.ABSTRACT_ONLY,
]);

export function ManualSourceUpload({ referenceId, flags, onComplete }: Props) {
  const shouldShow = flags.some((f) => SHOW_FOR_FLAGS.has(f));
  const [uploading, setUploading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!shouldShow) return null;

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadManualSource(referenceId, file);
      setDone(true);
      onComplete();
    } catch (err) {
      setError(String(err));
    } finally {
      setUploading(false);
    }
  }

  if (done) {
    return (
      <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1 mt-2">
        ✓ PDF uploaded. Re-verification is running in the background – refresh in a moment.
      </p>
    );
  }

  return (
    <div className="mt-2">
      <label className="cursor-pointer">
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={handleChange}
          disabled={uploading}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="text-xs text-blue-600 underline hover:text-blue-800 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload the cited paper yourself"}
        </button>
      </label>
      {error && <p className="text-red-600 text-xs mt-1">{error}</p>}
    </div>
  );
}
