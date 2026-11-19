/**
 * components/VerdictBadge.tsx – colour-coded badge for a verdict label.
 *
 * Colour spec (audit C11):
 *   supported      → green
 *   partly_supported → amber (not yellow)
 *   unsupported    → red
 *   contradictory  → dark red
 *   possibly_outdated → blue
 *   needs_review   → gray
 */

import type { VerdictLabel } from "@/lib/types";

const STYLES: Record<VerdictLabel, string> = {
  supported:        "bg-green-100 text-green-800 border-green-200",
  partly_supported: "bg-amber-100 text-amber-800 border-amber-200",
  unsupported:      "bg-red-100 text-red-700 border-red-200",
  contradictory:    "bg-red-900 text-red-100 border-red-800",
  possibly_outdated:"bg-blue-100 text-blue-800 border-blue-200",
  needs_review:     "bg-gray-100 text-gray-700 border-gray-300",
};

const LABELS: Record<VerdictLabel, string> = {
  supported:        "Supported",
  partly_supported: "Partly supported",
  unsupported:      "Unsupported",
  contradictory:    "Contradictory",
  possibly_outdated:"Possibly outdated",
  needs_review:     "Needs review",
};

export function VerdictBadge({ verdict }: { verdict: VerdictLabel }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${STYLES[verdict]}`}
    >
      {LABELS[verdict]}
    </span>
  );
}
