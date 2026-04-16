import React from "react";
import { formatNumber, formatPercent } from "../utils/format";

interface Props {
  values: Record<string, number>;
  comparisonValues?: Record<string, number> | null;
  comparisonLabel?: string | null;
  currentRangeLabel?: string | null;
  comparisonRangeLabel?: string | null;
  showDetailedComparison?: boolean;
  selectedMetric?: string;
  onSelectMetric?: (metric: string) => void;
}

const fontBody: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
};
const fontMetric: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
  fontVariantNumeric: "tabular-nums lining-nums",
  fontFeatureSettings: '"tnum" 1, "lnum" 1',
  letterSpacing: "0em",
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
  { key: "pageviews", label: "Pageviews", tier: "primary" as const },
  { key: "uniques", label: "Unique Visitors", tier: "primary" as const },
  { key: "sessions", label: "Sessions", tier: "primary" as const },
  { key: "conversions", label: "Conversions", tier: "primary" as const },
  { key: "revenue", label: "Revenue", tier: "primary" as const },
  { key: "avg_pages_per_visit", label: "Avg. Pages / Visit", tier: "secondary" as const },
  { key: "visit_duration", label: "Visit Duration", tier: "secondary" as const },
  { key: "bounce_rate", label: "Bounce Rate", tier: "secondary" as const },
];

export const KPIGrid: React.FC<Props> = ({
  values,
  comparisonValues,
  comparisonLabel,
  currentRangeLabel,
  comparisonRangeLabel,
  showDetailedComparison = false,
  selectedMetric,
  onSelectMetric,
}) => (
  <div className="border border-[var(--color-border-subtle)] bg-white">
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
        const isPrimary = card.tier === "primary";
        const showComparisonRows = showDetailedComparison && Boolean(currentRangeLabel && comparisonRangeLabel);

        return (
          <button
            key={card.key}
            type="button"
            onClick={() => onSelectMetric?.(card.key)}
            className={`flex ${showComparisonRows ? "min-h-[132px]" : "min-h-[96px]"} flex-col justify-between border-b border-r border-[var(--color-border-subtle)] px-4 py-2 text-left transition-colors ${
              isActive ? "bg-[#E8F5F5]" : "bg-white hover:bg-[#F9FAFB]"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className={`label-tight ${isActive ? "text-[#0A5F6F]" : "text-gray-500"}`} style={fontBody}>
                {card.label}
              </div>
              {showComparisonRows && (
                <div className={`text-[10px] ${deltaClass} metric-number whitespace-nowrap`} style={fontMetric}>
                  {deltaDisplay}
                </div>
              )}
            </div>
            <div>
              <div
                className={`${isPrimary ? "text-[var(--type-kpi-primary)] font-semibold text-[#111827]" : "text-[var(--type-kpi-secondary)] font-medium text-[#374151]"} metric-number leading-tight`}
                style={fontMetric}
              >
                {formatMetricValue(card.key, value)}
              </div>
              {showComparisonRows ? (
                <>
                  <div className="mt-1 text-[10px] text-gray-500 normal-case tracking-normal" style={fontBody}>
                    {currentRangeLabel}
                  </div>
                  <div
                    className={`mt-3 ${isPrimary ? "text-xl font-semibold text-[#6B7280]" : "text-base font-medium text-[#6B7280]"} metric-number leading-tight`}
                    style={fontMetric}
                  >
                    {formatMetricValue(card.key, compareValue ?? Number.NaN)}
                  </div>
                  <div className="mt-1 text-[10px] text-gray-400 normal-case tracking-normal" style={fontBody}>
                    {comparisonRangeLabel}
                  </div>
                </>
              ) : (
                <>
                  <div className={`mt-1 text-[11px] ${deltaClass} metric-number leading-tight`} style={fontMetric}>
                    {deltaDisplay}
                  </div>
                  {comparisonLabel && (
                    <div className="mt-1 text-[10px] text-gray-400 normal-case tracking-normal" style={fontBody}>
                      {comparisonLabel}
                    </div>
                  )}
                </>
              )}
            </div>
          </button>
        );
      })}
    </div>
  </div>
);
