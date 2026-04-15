import React from "react";
import { formatNumber, formatPercent } from "../utils/format";

interface Props {
  values: Record<string, number>;
  comparisonValues?: Record<string, number> | null;
  comparisonLabel?: string | null;
  selectedMetric?: string;
  onSelectMetric?: (metric: string) => void;
}

const fontBody: React.CSSProperties = {
  fontFamily: '"Inter", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
};
const fontNumeric: React.CSSProperties = {
  fontFamily:
    '"Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
};

const formatCurrency = (value: number): string =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const formatDuration = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const rounded = Math.round(seconds);
  const minutes = Math.floor(rounded / 60);
  const secs = rounded % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
  }
  return `${minutes}m ${secs.toString().padStart(2, "0")}s`;
};

const formatMetricValue = (metric: string, value: number) => {
  if (!Number.isFinite(value)) return "—";
  if (metric === "revenue") return formatCurrency(value);
  if (metric === "visit_duration") return formatDuration(value);
  if (metric.includes("rate")) return formatPercent(value);
  if (metric === "avg_pages_per_visit") return value.toFixed(2);
  return formatNumber(value);
};

const cards = [
  { key: "pageviews", label: "Pageviews" },
  { key: "uniques", label: "Unique Visitors" },
  { key: "sessions", label: "Sessions" },
  { key: "conversions", label: "Conversions" },
  { key: "revenue", label: "Revenue" },
  { key: "avg_pages_per_visit", label: "Avg. Pages / Visit" },
  { key: "visit_duration", label: "Visit Duration" },
  { key: "bounce_rate", label: "Bounce Rate" },
];

export const KPIGrid: React.FC<Props> = ({
  values,
  comparisonValues,
  comparisonLabel,
  selectedMetric,
  onSelectMetric,
}) => (
  <div className="border border-[#D9E2E8] bg-white">
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8">
      {cards.map((card) => {
        const value = values[card.key];
        const compareValue = comparisonValues?.[card.key];
        const delta =
          Number.isFinite(value) && Number.isFinite(compareValue) && (compareValue ?? 0) > 0
            ? (value - (compareValue ?? 0)) / (compareValue ?? 1)
            : Number.NaN;
        const deltaDisplay = Number.isFinite(delta)
          ? `${delta >= 0 ? "↑" : "↓"} ${Math.abs(delta * 100).toFixed(1)}%`
          : "—";
        const deltaClass = Number.isFinite(delta)
          ? delta >= 0
            ? "text-[#0A5F6F]"
            : "text-[#8B2635]"
          : "text-gray-400";
        const isActive = selectedMetric === card.key;

        return (
          <button
            key={card.key}
            type="button"
            onClick={() => onSelectMetric?.(card.key)}
            className={`flex min-h-[108px] flex-col justify-between border-b border-r px-3 py-3 text-left transition-colors ${
              isActive ? "bg-[#E8F5F5]" : "bg-white hover:bg-[#F9FAFB]"
            }`}
          >
            <div className={`text-[10px] uppercase tracking-[0.18em] ${isActive ? "text-[#0A5F6F]" : "text-gray-500"}`} style={fontBody}>
              {card.label}
            </div>
            <div>
              <div className="text-xl text-[#1F2937]" style={fontNumeric}>
                {formatMetricValue(card.key, value)}
              </div>
              <div className={`mt-1 text-[11px] ${deltaClass}`} style={fontBody}>
                {deltaDisplay}
              </div>
              {comparisonLabel && (
                <div className="mt-1 text-[10px] text-gray-400 normal-case tracking-normal" style={fontBody}>
                  {comparisonLabel}
                </div>
              )}
            </div>
          </button>
        );
      })}
    </div>
  </div>
);
