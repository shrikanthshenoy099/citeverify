/**
 * Verdict badge colours.
 */
export const VERDICT_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  supported: { bg: "bg-green-100", text: "text-green-800", label: "Supported" },
  partly_supported: {
    bg: "bg-yellow-100",
    text: "text-yellow-800",
    label: "Partly supported",
  },
  unsupported: { bg: "bg-red-100", text: "text-red-800", label: "Unsupported" },
  contradictory: {
    bg: "bg-red-200",
    text: "text-red-900",
    label: "Contradictory",
  },
  possibly_outdated: {
    bg: "bg-orange-100",
    text: "text-orange-800",
    label: "Possibly outdated",
  },
  needs_review: {
    bg: "bg-gray-100",
    text: "text-gray-700",
    label: "Needs review",
  },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const style = VERDICT_STYLES[verdict] ?? {
    bg: "bg-gray-100",
    text: "text-gray-700",
    label: verdict,
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${style.bg} ${style.text}`}
    >
      {style.label}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colour =
    pct >= 70 ? "bg-green-500" : pct >= 45 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="flex-1 bg-gray-200 rounded-full h-1.5">
        <div
          className={`${colour} h-1.5 rounded-full transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

export function FlagList({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {flags.map((f) => (
        <span
          key={f}
          className="inline-block px-1.5 py-0.5 bg-gray-100 text-gray-500 text-xs rounded"
        >
          {f}
        </span>
      ))}
    </div>
  );
}
