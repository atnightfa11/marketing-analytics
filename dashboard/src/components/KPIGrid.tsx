import React from "react";
import { fontBody, fontMetric } from "../styles/typography";
import { formatMetricValue } from "../utils/format";

interface Props {
  values: Record<string, number>;
  comparisonValues?: Record<string, number> | null;
  comparisonLabel?: string | null;
  currentRangeLabel?: string | null;
  comparisonRangeLabel?: string | null;
  showDetailedComparison?: boolean;
  selectedMetric?: string;
  onSelectMetric?: (metric: string) => void;
  error?: string | null;
}

const cards = [
  { key: "uniques", label: "Visitors", tier: "primary" as const },
  { key: "sessions", label: "Sessions", tier: "primary" as const },
  { key: "conversions", label: "Conversions", tier: "primary" as const },
  { key: "revenue", label: "Revenue", tier: "primary" as const },
  { key: "avg_pages_per_visit", label: "Pages per Visit", tier: "secondary" as const },
  { key: "pageviews", label: "Pageviews", tier: "primary" as const },
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
  error,
}) => (
  <div className="overflow-hidden rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
    {error && (
      <div className="border-b border-[#FECACA] bg-[#FFF7F7] px-4 py-2 text-[12px] text-[#8B2635]" style={fontBody}>
        {error}
      </div>
    )}
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
            ? "text-[#4338ca]"
            : "text-[#8B2635]"
          : "text-gray-400";
        const isActive = selectedMetric === card.key;
        const showComparisonRows = showDetailedComparison && Boolean(currentRangeLabel && comparisonRangeLabel);

        return (
          <button
            key={card.key}
            type="button"
            onClick={() => onSelectMetric?.(card.key)}
            className={`flex ${showComparisonRows ? "min-h-[122px]" : "min-h-[76px]"} flex-col justify-between border-b border-r border-[var(--color-border-subtle)] px-4 py-3 text-left transition-colors last:border-r-0 xl:border-b-0 ${
              isActive ? "bg-[#fbfbff]" : "bg-white hover:bg-[#F9FAFB]"
            }`}
          >
            <div className="min-w-0">
              <div
                className={`label-tight truncate font-bold ${isActive ? "text-[#5b55ff]" : "text-[#7B8190]"}`}
                style={fontBody}
                title={card.label}
              >
                {card.label}
              </div>
            </div>
            <div className="min-w-0">
              <div
                className="metric-number truncate text-[21px] font-semibold leading-tight text-[#111827]"
                style={fontMetric}
                title={formatMetricValue(card.key, value)}
              >
                {formatMetricValue(card.key, value)}
              </div>
              {showComparisonRows ? (
                <>
                  <div className="mt-0.5 truncate text-[10px] text-[#6B7280] normal-case tracking-normal" style={fontBody}>
                    {currentRangeLabel}
                  </div>
                  <div className="mt-2 flex items-baseline gap-1.5">
                    <div
                      className="min-w-0 truncate text-sm font-medium text-[#4B5563] metric-number leading-tight"
                      style={fontMetric}
                      title={formatMetricValue(card.key, compareValue ?? Number.NaN)}
                    >
                      {formatMetricValue(card.key, compareValue ?? Number.NaN)}
                    </div>
                    <span className={`shrink-0 text-[10px] ${deltaClass} metric-number whitespace-nowrap`} style={fontMetric}>
                      {deltaDisplay}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-[#9CA3AF] normal-case tracking-normal" style={fontBody}>
                    {comparisonRangeLabel}
                  </div>
                </>
              ) : (
                <>
                  <div className="mt-1 flex min-w-0 items-center gap-1 text-[11px] leading-tight">
                    <span className={`${deltaClass} metric-number shrink-0`} style={fontMetric}>
                      {deltaDisplay}
                    </span>
                    {comparisonLabel && (
                      <span className="truncate text-[10px] text-gray-400 normal-case tracking-normal" style={fontBody}>
                        {comparisonLabel}
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          </button>
        );
      })}
    </div>
  </div>
);
