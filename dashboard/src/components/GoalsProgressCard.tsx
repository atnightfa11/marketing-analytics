import type { FC } from "react";

import { metricLabels } from "../constants";
import { fontBody, fontMetric } from "../styles/typography";
import type { MetricGoal } from "../types";
import { formatMetricValue } from "../utils/format";

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const goalValueKey = (goal: Pick<MetricGoal, "metric" | "conversionType">) =>
  goal.metric === "conversions" && goal.conversionType ? `conversions:${goal.conversionType}` : goal.metric;
const goalDisplayLabel = (goal: Pick<MetricGoal, "metric" | "conversionType">) =>
  goal.metric === "conversions" && goal.conversionType
    ? `Conversions · ${goal.conversionType}`
    : metricLabels[goal.metric] ?? goal.metric;

export const GoalsProgressCard: FC<{
  goals: MetricGoal[];
  values: Record<string, number>;
  dayCount: number;
  rangeLabel: string;
  siteId: string;
}> = ({ goals, values, dayCount, rangeLabel, siteId }) => (
  <div className="min-h-[280px] rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
    <div className="mb-4 flex items-start justify-between gap-2">
      <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
        Goals
      </div>
      <a
        href={`/site/${encodeURIComponent(siteId)}/settings`}
        className="text-[11px] font-semibold text-[#5b55ff] hover:text-[#4338ca]"
        style={fontBody}
      >
        + Add goal
      </a>
    </div>
    {goals.length === 0 ? (
      <div className="py-10 text-xs text-gray-400" style={fontBody}>
        Goals set in Settings will show here with pacing against the selected period.
      </div>
    ) : (
      <div className="space-y-4">
        {goals.slice(0, 4).map((goal) => {
          const currentValue = values[goalValueKey(goal)] ?? Number.NaN;
          const targetForWindow = goal.target * (Math.max(1, dayCount) / Math.max(1, goal.periodDays));
          const progressPct =
            Number.isFinite(currentValue) && Number.isFinite(targetForWindow) && targetForWindow > 0
              ? clamp(currentValue / targetForWindow, 0, 1.25)
              : 0;
          const gap = Number.isFinite(currentValue) && Number.isFinite(targetForWindow) ? currentValue - targetForWindow : Number.NaN;
          const statusClass = Number.isFinite(gap) && gap >= 0 ? "bg-emerald-50 text-emerald-700" : "bg-[#FFF1F2] text-[#8B2635]";
          const statusLabel = Number.isFinite(gap)
            ? gap >= 0
              ? "On pace"
              : "Behind"
            : "Needs data";
          return (
            <div key={goalValueKey(goal)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold text-[#374151]" style={fontBody}>
                    {goalDisplayLabel(goal)}
                  </div>
                  <div className="mt-0.5 text-[11px] text-[#7B8190]" style={fontBody}>
                    {"Target for selected period \u00b7 "}{formatMetricValue(goal.metric, targetForWindow)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="metric-number text-[13px] font-semibold text-[#111827]" style={fontMetric}>
                    {formatMetricValue(goal.metric, currentValue)}
                  </div>
                  <span className={`mt-1 inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold ${statusClass}`} style={fontBody}>
                    {statusLabel}
                  </span>
                </div>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#EEF1F4]">
                <div
                  className="h-full rounded-full bg-[#5b55ff]"
                  style={{ width: `${Math.min(100, progressPct * 100)}%` }}
                />
              </div>
            </div>
          );
        })}
        <div className="pt-1 text-right text-[11px] text-[#7B8190]" style={fontBody}>
          {"Period \u00b7 "}{rangeLabel}
        </div>
      </div>
    )}
  </div>
);
