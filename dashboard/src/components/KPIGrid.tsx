import React from "react";
import { MetricStatistic } from "../api";
import { formatNumber, formatPercent } from "../utils/format";

interface Props {
  metrics: MetricStatistic[];
  values?: Record<string, number>;
  comparisonValues?: Record<string, number> | null;
  comparisonLabel?: string | null;
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

export const KPIGrid: React.FC<Props> = ({ metrics, values, comparisonValues, comparisonLabel }) => {
  const metricsByKey = metrics.reduce<Record<string, MetricStatistic>>((acc, metric) => {
    acc[metric.metric] = metric;
    return acc;
  }, {});

  const kpis = [
    { key: "pageviews", label: "Pageviews", format: formatNumber },
    { key: "uniques", label: "Unique Visitors", format: formatNumber },
    { key: "sessions", label: "Sessions", format: formatNumber },
    { key: "conversions", label: "Conversions", format: formatNumber },
    { key: "revenue", label: "Revenue", format: formatCurrency },
  ];

  return (
    <div className="border border-gray-200 bg-white">
      <div className="grid grid-cols-2 md:grid-cols-5">
        {kpis.map((kpi, index) => {
          const metric = metricsByKey[kpi.key];
          const rawValue = metric?.value ?? Number.NaN;
          const valueFromTotals = values?.[kpi.key] ?? Number.NaN;
          const value = Number.isFinite(valueFromTotals) ? valueFromTotals : rawValue;
          const display = Number.isFinite(value) ? kpi.format(value) : "N/A";
          const compareValue = comparisonValues?.[kpi.key];
          const delta =
            Number.isFinite(value) && Number.isFinite(compareValue) && (compareValue ?? 0) > 0
              ? (value - (compareValue ?? 0)) / (compareValue ?? 1)
              : Number.NaN;
          const deltaDisplay = Number.isFinite(delta)
            ? `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}%`
            : "—";
          const deltaClass = Number.isFinite(delta)
            ? delta >= 0
              ? "text-emerald-600"
              : "text-rose-600"
            : "text-gray-400";

          return (
            <div
              key={kpi.key}
              className={`px-4 py-3 ${index === 0 ? "" : "border-l border-gray-200"}`}
            >
              <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                {kpi.label}
              </div>
              <div className="mt-1 text-2xl text-[#111827]" style={fontNumeric}>
                {display}
              </div>
              {comparisonLabel && (
                <div className="mt-1">
                  <div className={`text-[10px] uppercase tracking-[0.2em] ${deltaClass}`} style={fontBody}>
                    {deltaDisplay}
                  </div>
                  <div className="mt-1 text-[10px] text-gray-400 normal-case tracking-normal" style={fontBody}>
                    {comparisonLabel}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
