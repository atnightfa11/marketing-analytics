import type { BreakdownDimension, BreakdownMetricKey } from "./api";
import type { forecastOptions, goalEligibleMetrics, rangeOptions } from "./constants";

export type GoalMetric = (typeof goalEligibleMetrics)[number];
export type GoalRepeat = "monthly";

export interface MetricGoal {
  metric: GoalMetric;
  conversionType?: string | null;
  target: number;
  periodDays: number;
  repeat: GoalRepeat;
  updatedAt: string;
}

export type SiteGoalsMap = Record<string, MetricGoal>;

export type ChartGranularity = "day" | "week" | "month";
export type ForecastOption = (typeof forecastOptions)[number];
export type RangeOption = (typeof rangeOptions)[number];
export type DateRange = { start: string; end: string };
export type DailyValuePoint = { day: string; value: number };
export type BreakdownMetricTotals = Partial<Record<BreakdownMetricKey, number>>;

export interface BreakdownTableRow {
  label: string;
  metrics: BreakdownMetricTotals;
}

export interface ActiveFilter {
  dimension: string;
  value: string;
  share: number;
}

export interface BreakdownData {
  rows: BreakdownTableRow[];
  total: number;
  primaryMetric: BreakdownMetricKey;
  metricKeys: BreakdownMetricKey[];
  totalsByMetric: BreakdownMetricTotals;
}

export type BreakdownErrorMap = Partial<Record<BreakdownDimension, string>>;

export interface ComparisonPoint {
  day: string;
  value: number;
}

export interface TrendChartPoint {
  day: string;
  actual: number | null;
  todaySoFar: number | null;
  todayBridge: number | null;
  compare: number | null;
  compareDay: string | null;
  forecast: number | null;
  forecastLine: number | null;
  forecastLower: number | null;
  forecastUpper: number | null;
  forecastBandSpan: number | null;
  deltaPositiveRange: [number, number] | null;
  deltaNegativeRange: [number, number] | null;
}
