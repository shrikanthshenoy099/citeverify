/**
 * components/FlagBadge.tsx – plain-language badge for standard flags.
 * Includes special plain-English explanations for new flags (ocr_text,
 * possibly_retracted, manual_source) as required by M4 spec.
 */

import { FLAGS } from "@/lib/types";

interface FlagInfo {
  label: string;
  title: string;
  style: string;
}

const FLAG_INFO: Record<string, FlagInfo> = {
  [FLAGS.OCR_TEXT]: {
    label: "OCR text",
    title: "Text was read by OCR and may contain errors.",
    style: "bg-purple-100 text-purple-800 border-purple-200",
  },
  [FLAGS.POSSIBLY_RETRACTED]: {
    label: "Possibly retracted",
    title: "This paper may have been retracted. Verify on Retraction Watch.",
    style: "bg-red-100 text-red-800 border-red-200",
  },
  [FLAGS.MANUAL_SOURCE]: {
    label: "Manual source",
    title: "This PDF was uploaded manually by a reviewer, not fetched automatically.",
    style: "bg-blue-100 text-blue-800 border-blue-200",
  },
  [FLAGS.ABSTRACT_ONLY]: {
    label: "Abstract only",
    title: "Only the abstract was available; full text was not retrieved.",
    style: "bg-yellow-100 text-yellow-800 border-yellow-200",
  },
  [FLAGS.FULL_TEXT_UNAVAILABLE]: {
    label: "Full text unavailable",
    title: "Could not retrieve the full text of this paper.",
    style: "bg-orange-100 text-orange-800 border-orange-200",
  },
  [FLAGS.REFERENCE_NOT_FOUND]: {
    label: "Reference not found",
    title: "No matching paper was found in open-access databases.",
    style: "bg-red-100 text-red-800 border-red-200",
  },
  [FLAGS.LOW_RETRIEVAL_SCORE]: {
    label: "Low retrieval score",
    title: "The retrieved source may not be the correct paper.",
    style: "bg-orange-100 text-orange-800 border-orange-200",
  },
  [FLAGS.QUOTE_NOT_VERIFIED]: {
    label: "Quote unverified",
    title: "The exact quote could not be located in the source text.",
    style: "bg-yellow-100 text-yellow-800 border-yellow-200",
  },
  [FLAGS.NUMBER_NOT_FOUND]: {
    label: "Number not found",
    title: "A specific number from the claim was not found in the source.",
    style: "bg-yellow-100 text-yellow-800 border-yellow-200",
  },
  [FLAGS.SCOPE_MISMATCH]: {
    label: "Scope mismatch",
    title: "The claim scope differs from what the source actually says.",
    style: "bg-orange-100 text-orange-800 border-orange-200",
  },
  [FLAGS.LLM_OUTPUT_INVALID]: {
    label: "LLM error",
    title: "The language model returned an invalid response; human review required.",
    style: "bg-red-100 text-red-800 border-red-200",
  },
};

export function FlagBadge({ flag }: { flag: string }) {
  const info = FLAG_INFO[flag];
  if (!info) {
    // Unknown flag – render a plain grey badge
    return (
      <span className="inline-block px-2 py-0.5 text-xs rounded border bg-gray-100 text-gray-600 border-gray-200">
        {flag}
      </span>
    );
  }
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs rounded border ${info.style}`}
      title={info.title}
    >
      {info.label}
    </span>
  );
}
