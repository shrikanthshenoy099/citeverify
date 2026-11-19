/**
 * components/ReviewPanel.tsx – human reviewer action panel.
 * Reads reviewer name from localStorage (no login required).
 */

"use client";

import { useEffect, useState } from "react";
import { postReview, getReviews } from "@/lib/api";
import type { Review, ReviewAction, VerdictLabel } from "@/lib/types";

const VERDICT_OPTIONS: VerdictLabel[] = [
  "supported",
  "partly_supported",
  "unsupported",
  "contradictory",
  "possibly_outdated",
  "needs_review",
];

interface Props {
  claimId: string;
  referenceId: string;
}

export function ReviewPanel({ claimId, referenceId }: Props) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [action, setAction] = useState<ReviewAction>("comment");
  const [newVerdict, setNewVerdict] = useState<VerdictLabel | "">("");
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load reviewer name from localStorage
  useEffect(() => {
    const saved = typeof window !== "undefined"
      ? window.localStorage.getItem("citeverify_reviewer") ?? ""
      : "";
    setReviewer(saved);
    getReviews(claimId).then(setReviews).catch(() => {});
  }, [claimId]);

  function saveReviewer(name: string) {
    setReviewer(name);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("citeverify_reviewer", name);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reviewer.trim()) {
      setError("Please enter your name before submitting a review.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await postReview(claimId, {
        reference_id: referenceId,
        action,
        new_verdict: action === "override" && newVerdict ? newVerdict : null,
        comment,
        reviewer: reviewer.trim(),
      });
      setComment("");
      const updated = await getReviews(claimId);
      setReviews(updated);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-4 border-t border-gray-200 pt-4">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
        Human Review
      </h4>

      {/* Existing reviews */}
      {reviews.length > 0 && (
        <ul className="space-y-2 mb-4">
          {reviews.map((r) => (
            <li key={r.review_id} className="text-xs bg-gray-50 border border-gray-200 rounded p-2">
              <span className="font-medium">{r.reviewer}</span>
              {" · "}
              <span className="text-gray-500">{r.action}</span>
              {r.new_verdict && (
                <span className="text-gray-500"> → {r.new_verdict}</span>
              )}
              {r.comment && <span className="block text-gray-600 mt-0.5">{r.comment}</span>}
              <span className="block text-gray-400 mt-0.5">{new Date(r.timestamp).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Review form */}
      <form onSubmit={handleSubmit} className="space-y-2">
        <input
          type="text"
          placeholder="Your name"
          value={reviewer}
          onChange={(e) => saveReviewer(e.target.value)}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <div className="flex gap-2">
          <select
            value={action}
            onChange={(e) => setAction(e.target.value as ReviewAction)}
            className="border border-gray-300 rounded px-2 py-1 text-xs"
          >
            <option value="accept">Accept</option>
            <option value="reject">Reject</option>
            <option value="comment">Comment</option>
            <option value="override">Override verdict</option>
          </select>
          {action === "override" && (
            <select
              value={newVerdict}
              onChange={(e) => setNewVerdict(e.target.value as VerdictLabel)}
              className="border border-gray-300 rounded px-2 py-1 text-xs"
            >
              <option value="">Select new verdict…</option>
              {VERDICT_OPTIONS.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          )}
        </div>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional comment…"
          rows={2}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {error && <p className="text-red-600 text-xs">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="bg-blue-600 text-white px-3 py-1 rounded text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "Saving…" : "Submit review"}
        </button>
      </form>
    </div>
  );
}
