import type { FC } from "react";

import type { BreakdownMetricKey, TimePartingDayType } from "../api";
import { dayOfWeekLabels, hourOfDayLabels } from "../constants";
import { fontBody, fontMeta, fontMetric } from "../styles/typography";
import type { BreakdownTableRow } from "../types";
import { getBreakdownMetricValue } from "../utils/breakdowns";
import { formatMetricValue, formatPercent } from "../utils/format";

const shortDayOfWeekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

const getHourIndexFromLabel = (label: string): number => {
  const numeric = Number(label);
  if (Number.isFinite(numeric) && numeric >= 0 && numeric <= 23) return numeric;
  const normalized = label.trim().toLowerCase();
  const exactIndex = hourOfDayLabels.findIndex((hour) => hour.toLowerCase() === normalized);
  if (exactIndex >= 0) return exactIndex;
  return -1;
};

const getDayIndexFromLabel = (label: string): number => {
  const normalized = label.trim().toLowerCase();
  const exactIndex = dayOfWeekLabels.findIndex((day) => day.toLowerCase() === normalized);
  if (exactIndex >= 0) return exactIndex;
  const shortIndex = shortDayOfWeekLabels.findIndex((day) => day.toLowerCase() === normalized.slice(0, 3));
  if (shortIndex >= 0) return shortIndex;
  const numeric = Number(label);
  if (Number.isFinite(numeric) && numeric >= 0 && numeric <= 6) return numeric;
  return -1;
};

const formatHourRange = (hourIndex: number): string => {
  const start = hourOfDayLabels[hourIndex] ?? `${hourIndex}:00`;
  const end = hourOfDayLabels[(hourIndex + 1) % 24] ?? `${(hourIndex + 1) % 24}:00`;
  return `${start} - ${end}`;
};

export const TimePartingHeatmap: FC<{
  hourRows: BreakdownTableRow[];
  dayRows: BreakdownTableRow[];
  primaryMetric: BreakdownMetricKey;
  dayType: TimePartingDayType;
  setDayType: (value: TimePartingDayType) => void;
  emptyState: string;
  error?: string | null;
  rangeLabel: string;
}> = ({ hourRows, dayRows, primaryMetric, dayType, setDayType, emptyState, error, rangeLabel }) => {
  const hourValues = Array.from({ length: 24 }, () => 0);
  const dayValues = Array.from({ length: 7 }, () => 0);

  hourRows.forEach((row) => {
    const index = getHourIndexFromLabel(row.label);
    if (index >= 0) hourValues[index] = getBreakdownMetricValue(row, primaryMetric);
  });
  dayRows.forEach((row) => {
    const index = getDayIndexFromLabel(row.label);
    if (index >= 0) dayValues[index] = getBreakdownMetricValue(row, primaryMetric);
  });

  const visibleDayIndexes =
    dayType === "weekday" ? [0, 1, 2, 3, 4] : dayType === "weekend" ? [5, 6] : [0, 1, 2, 3, 4, 5, 6];
  const maxHour = Math.max(...hourValues, 0);
  const maxDay = Math.max(...dayValues, 0);
  const totalHour = hourValues.reduce((sum, value) => sum + value, 0);
  const totalDay = visibleDayIndexes.reduce((sum, dayIndex) => sum + dayValues[dayIndex], 0);
  const hasData = maxHour > 0 || maxDay > 0;
  const peakHourIndex = hourValues.reduce((best, value, index) => (value > hourValues[best] ? index : best), 0);
  const peakDayIndex = visibleDayIndexes.reduce(
    (best, dayIndex) => (dayValues[dayIndex] > dayValues[best] ? dayIndex : best),
    visibleDayIndexes[0] ?? 0
  );
  const topHourIndexes = hourValues
    .map((value, index) => ({ index, value }))
    .sort((a, b) => b.value - a.value || a.index - b.index)
    .slice(0, 8)
    .map((item) => item.index);
  const tableHourIndexes = Array.from(new Set([...topHourIndexes, peakHourIndex])).sort(
    (a, b) => hourValues[b] - hourValues[a] || a - b
  );

  const renderMetricRow = ({
    label,
    value,
    total,
    max,
    isPeak,
  }: {
    label: string;
    value: number;
    total: number;
    max: number;
    isPeak: boolean;
  }) => {
    const share = total > 0 ? value / total : 0;
    const width = max > 0 ? Math.max(3, (value / max) * 100) : 0;
    return (
      <tr key={label} className={isPeak ? "bg-[var(--surface-highlight)]" : undefined} title={isPeak ? "Highest value in this group" : undefined}>
        <td className={`py-2.5 pr-3 text-[12px] ${isPeak ? "font-semibold text-[#111827]" : "text-[#374151]"}`} style={fontBody}>
          {label}
        </td>
        <td className="py-2.5 pr-3 text-right text-[12px] text-[#111827] metric-number" style={fontMetric}>
          {formatMetricValue(primaryMetric, value)}
        </td>
        <td className="py-2.5 text-right text-[12px] text-[#6B7280] metric-number" style={fontMetric}>
          {formatPercent(share)}
        </td>
        <td className="hidden py-2.5 pl-3 sm:table-cell">
          <div className="h-1.5 rounded-full bg-[#EEF2F7]">
            <div className="h-1.5 rounded-full bg-[#6B63FF]" style={{ width: `${width}%` }} />
          </div>
        </td>
      </tr>
    );
  };

  return (
    <div className="min-h-[280px] rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
            When visitors arrive
          </div>
          <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
            {rangeLabel} · {metricLabel(primaryMetric)}
          </div>
        </div>
        <div className="flex items-center gap-1 rounded-md bg-[#F1F3F6] p-0.5 text-[11px]" style={fontBody}>
          {([
            ["all", "All"],
            ["weekday", "Weekdays"],
            ["weekend", "Weekends"],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={
                dayType === value
                  ? "rounded bg-white px-2.5 py-1 font-semibold text-[#1F2937] shadow-sm"
                  : "px-2.5 py-1 font-semibold text-[#7B8190] hover:text-[#1F2937]"
              }
              onClick={() => setDayType(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {error ? (
        <div className="py-10 text-xs text-[#8B2635]" style={fontBody}>
          {error}
        </div>
      ) : !hasData ? (
        <div className="py-10 text-xs text-gray-400" style={fontBody}>
          {emptyState}
        </div>
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
            <div>
              <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontMeta}>
                Top hours
              </div>
              <table className="w-full table-fixed border-collapse">
                <thead>
                  <tr className="border-b border-[var(--color-border-subtle)] text-[10px] uppercase tracking-[0.14em] text-[#9CA3AF]" style={fontMeta}>
                    <th className="py-2 pr-3 text-left font-semibold">Hour</th>
                    <th className="py-2 pr-3 text-right font-semibold">Count</th>
                    <th className="py-2 text-right font-semibold">Share</th>
                    <th className="hidden py-2 pl-3 text-left font-semibold sm:table-cell">Relative</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border-subtle)]">
                  {tableHourIndexes.map((hourIndex) =>
                    renderMetricRow({
                      label: formatHourRange(hourIndex),
                      value: hourValues[hourIndex],
                      total: totalHour,
                      max: maxHour,
                      isPeak: hourIndex === peakHourIndex,
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div>
              <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontMeta}>
                By day
              </div>
              <table className="w-full table-fixed border-collapse">
                <thead>
                  <tr className="border-b border-[var(--color-border-subtle)] text-[10px] uppercase tracking-[0.14em] text-[#9CA3AF]" style={fontMeta}>
                    <th className="py-2 pr-3 text-left font-semibold">Day</th>
                    <th className="py-2 pr-3 text-right font-semibold">Count</th>
                    <th className="py-2 text-right font-semibold">Share</th>
                    <th className="hidden py-2 pl-3 text-left font-semibold sm:table-cell">Relative</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border-subtle)]">
                  {visibleDayIndexes.map((dayIndex) =>
                    renderMetricRow({
                      label: dayOfWeekLabels[dayIndex],
                      value: dayValues[dayIndex],
                      total: totalDay,
                      max: maxDay,
                      isPeak: dayIndex === peakDayIndex,
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

const metricLabel = (metric: BreakdownMetricKey): string => {
  if (metric === "uniques") return "Visitors";
  return metric.slice(0, 1).toUpperCase() + metric.slice(1);
};
