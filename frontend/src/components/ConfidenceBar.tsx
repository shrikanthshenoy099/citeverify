/**
 * components/ConfidenceBar.tsx – visual confidence meter.
 */

interface Props {
  value: number; // 0–1
}

export function ConfidenceBar({ value }: Props) {
  const pct = Math.round(value * 100);
  const colour =
    pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 text-xs text-gray-600">
      <div className="flex-1 bg-gray-200 rounded-full h-2 overflow-hidden">
        <div
          className={`h-2 rounded-full transition-all ${colour}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono">{pct}%</span>
    </div>
  );
}
