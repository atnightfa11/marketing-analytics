import { Fragment, type FC } from "react";

import type { BreakdownMetricKey, TimePartingDayType } from "../api";
import { dayOfWeekLabels, hourOfDayLabels } from "../constants";
import { fontBody, fontMeta } from "../styles/typography";
import type { BreakdownTableRow } from "../types";
import { getBreakdownMetricValue } from "../utils/breakdowns";

const shortDayOfWeekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const hourTickIndexes = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22] as const;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

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
  const hasData = maxHour > 0 || maxDay > 0;
  let peakLabel = "No peak yet";
  let peakValue = 0;

  const getIntensity = (dayIndex: number, hourIndex: number) => {
    const hourShare = maxHour > 0 ? hourValues[hourIndex] / maxHour : 0;
    const dayShare = maxDay > 0 ? dayValues[dayIndex] / maxDay : 0;
    if (!hasData) return 0;
    return clamp(hourShare * 0.72 + dayShare * 0.28, 0.08, 1);
  };

  visibleDayIndexes.forEach((dayIndex) => {
    hourValues.forEach((_, hourIndex) => {
      const intensity = getIntensity(dayIndex, hourIndex);
      if (intensity > peakValue) {
        peakValue = intensity;
        peakLabel = `${shortDayOfWeekLabels[dayIndex]} \u00b7 ${hourOfDayLabels[hourIndex]}`;
      }
    });
  });

  return (
    <div className="min-h-[280px] rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
          When visitors arrive
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
          <div className="grid grid-cols-[38px_1fr] gap-x-2 gap-y-1">
            <div />
            <div className="grid grid-cols-[repeat(24,minmax(0,1fr))] gap-1 text-[10px] text-[#9CA3AF]" style={fontMeta}>
              {hourTickIndexes.map((hour) => (
                <div key={hour} className="col-span-2 text-center">
                  {hour}
                </div>
              ))}
            </div>
            {visibleDayIndexes.map((dayIndex) => (
              <Fragment key={dayIndex}>
                <div className="flex h-4 items-center text-[11px] text-[#6B7280]" style={fontBody}>
                  {shortDayOfWeekLabels[dayIndex]}
                </div>
                <div className="grid grid-cols-[repeat(24,minmax(0,1fr))] gap-1">
                  {hourValues.map((_, hourIndex) => {
                    const intensity = getIntensity(dayIndex, hourIndex);
                    const alpha = 0.1 + intensity * 0.68;
                    return (
                      <div
                        key={`${dayIndex}-${hourIndex}`}
                        className="h-4 rounded-[2px]"
                        title={`${dayOfWeekLabels[dayIndex]} ${hourOfDayLabels[hourIndex]}`}
                        style={{ backgroundColor: `rgba(79, 70, 229, ${alpha})` }}
                      />
                    );
                  })}
                </div>
              </Fragment>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#7B8190]" style={fontBody}>
            <span>
              {"Peak \u00b7 "}
              <span className="font-semibold text-[#4B5563]">{peakLabel}</span>
            </span>
            <span>{"Period \u00b7 "}{rangeLabel}</span>
          </div>
        </>
      )}
    </div>
  );
};
