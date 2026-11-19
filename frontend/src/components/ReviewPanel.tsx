"use client";

import { useState } from "react";
import { submitReview } from "@/lib/api";
import type { ReviewRequest } from "@/lib/api";

const ACTIONS = [
  { value: "accept", label: "Accept verdict" },
  { value: "reject", label: "Reject verdict" },
  { value: "comment", label: "Add comment" },
  { value: "override", label: "Override verdict" },
] as const;

const VERDICTS = [
  "supported",
  "partly_supported",
  "unsupported",
  "contradictory",
  "possibly_outdated",
  "needs_review",
] as const;

interface Props {
  claimId: string;
  referenceId: string;
  onDone: () => void;
}

export default function ReviewPanel({ claimId, referenceId, onDone }: Props) {
  const [action, setAction] = useState<ReviewRequest["action"]>("accept");
  const [newVerdict, setNewVerdict] = useState("supported");
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!reviewer.trim()) {
      setError("Please enter your name.");
      return;
    }
    setSubmitting(true);
    try {
      await submitReview(claimId, {
        reference_id: referenceId,
        action,
        new_verdict: action === "override" ? newVerdict : undefined,
        comment,
        reviewer: reviewer.trim(),
      });
      setDone(true);
      setTimeout(onDone, 1200);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Submission failed.");
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">
        ✓ Review submitted.
      </p>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3 text-sm"
    >
      <p className="font-medium text-amber-800">Submit review</p>

      <div>
        <label className="text-xs text-gray-600 block mb-1">Action</label>
        <select
          value={action}
          onChange={(e) =>
            setAction(e.target.value as ReviewRequest["action"])
          }
          className="border border-gray-300 rounded px-2 py-1 text-sm w-full"
        >
          {ACTIONS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
      </div>

      {action === "override" && (
        <div>
          <label className="text-xs text-gray-600 block mb-1">
            New verdict
          </label>
          <select
            value={newVerdict}
            onChange={(e) => setNewVerdict(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-sm w-full"
          >
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </div>
      )}

      <div>
        <label className="text-xs text-gray-600 block mb-1">
          Comment (optional)
        </label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm resize-none"
          placeholder="Notes for the team…"
        />
      </div>

      <div>
        <label className="text-xs text-gray-600 block mb-1">
          Your name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1 text-sm w-full"
          placeholder="Dr. Smith"
        />
      </div>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">
          {error}
        </p>
      )}

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onDone}
          className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 border border-gray-300 rounded"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="text-xs bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white px-4 py-1.5 rounded font-medium transition-colors"
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </div>
    </form>
  );
}
