import React from "react";
import { MetricStatistic } from "../api";
import { formatNumber, formatPercent } from "../utils/format";

interface Props {
  metrics: MetricStatistic[];
}

const niceNames: Record<string, string> = {
  uniques: "Daily Uniques",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
  bounce_rate: "Bounce Rate",
  avg_time_on_site: "Avg Time on Site",
};

export const KPIGrid: React.FC<Props> = ({ metrics }) => {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {metrics.map((metric) => (
        <div key={metric.metric} className="rounded border border-slate-200 bg-white p-4 shadow-sm">
          <div className="text-sm text-slate-500">{niceNames[metric.metric] ?? metric.metric}</div>
          <div className="mt-2 text-2xl font-semibold">
            {metric.metric.includes("rate") ? formatPercent(metric.value) : formatNumber(metric.value)}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            80% CI: [{formatNumber(metric.ci80.low)} – {formatNumber(metric.ci80.high)}]
          </div>
          <div className="text-xs text-slate-400">
            95% CI: [{formatNumber(metric.ci95.low)} – {formatNumber(metric.ci95.high)}]
          </div>
          {metric.has_anomaly && (
            <div className="mt-2 rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">Anomaly detected</div>
          )}
        </div>
      ))}
    </div>
  );
};
