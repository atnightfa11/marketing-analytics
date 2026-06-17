import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AggregateWindow,
  BreakdownDimension,
  BreakdownMetricKey,
  BreakdownRow,
  createCheckoutSession,
  createDashboardNote,
  DashboardSiteSummary,
  DashboardNote,
  deleteDashboardNote,
  fetchAggregate,
  fetchBillingStatus,
  fetchBreakdown,
  fetchDashboardSites,
  fetchDashboardNotes,
  fetchForecast,
  fetchImportHistory,
  fetchSiteIpBlocks,
  fetchSiteAccess,
  fetchSiteHealth,
  fetchSiteSettings,
  ForecastEntry,
  ForecastResponse,
  createSiteIpBlock,
  grantSiteAccess,
  HistoricalImportBatch,
  importHistoricalCsv,
  deleteSiteIpBlock,
  removeSiteAccess,
  resolveActiveSiteId,
  rollbackImportBatch,
  SiteAccessMember,
  SiteHealthResponse,
  SiteIpBlock,
  TimePartingDayType,
  updateSiteTimezone,
} from "./api";
import { KPIGrid } from "./components/KPIGrid";
import { useAuth } from "./hooks/useAuth";
import { useTheme } from "./hooks/useTheme";
import { formatNumber, formatPercent, formatShortDate } from "./utils/format";
import { buildSourceMediumLabel, classifyChannelLabel, normalizeSourceLabel } from "./utils/sourceAttribution";
import en from "./locales/en.json";

const fontHeading: React.CSSProperties = { fontFamily: "var(--font-sans)" };
const fontBody: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
};
const fontMetric: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
  fontVariantNumeric: "tabular-nums lining-nums",
  fontFeatureSettings: '"tnum" 1, "lnum" 1',
  letterSpacing: "0em",
};
const fontMeta: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums lining-nums",
  fontFeatureSettings: '"tnum" 1, "lnum" 1',
  letterSpacing: "0.01em",
};

const LAST_SITE_ID_STORAGE_KEY = "valid_last_site_id";
const ENABLE_DEMO_MODE = import.meta.env.VITE_ENABLE_DEMO_MODE === "true";

const metricLabels: Record<string, string> = {
  uniques: "Unique Visitors",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
  avg_pages_per_visit: "Pages per Visit",
  bounce_rate: "Bounce Rate",
  visit_duration: "Visit Duration",
  revenue: "Revenue",
};
const breakdownMetricInlineLabels: Record<BreakdownMetricKey, string> = {
  uniques: "Visitors",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
};
const hourOfDayLabels = [
  "12 AM",
  "1 AM",
  "2 AM",
  "3 AM",
  "4 AM",
  "5 AM",
  "6 AM",
  "7 AM",
  "8 AM",
  "9 AM",
  "10 AM",
  "11 AM",
  "12 PM",
  "1 PM",
  "2 PM",
  "3 PM",
  "4 PM",
  "5 PM",
  "6 PM",
  "7 PM",
  "8 PM",
  "9 PM",
  "10 PM",
  "11 PM",
] as const;
const dayOfWeekLabels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

const metricOptions = [
  { key: "pageviews", label: "Pageviews" },
  { key: "uniques", label: "Unique Visitors" },
  { key: "sessions", label: "Sessions" },
  { key: "conversions", label: "Conversions" },
  { key: "revenue", label: "Revenue" },
  { key: "avg_pages_per_visit", label: "Average Pages per Visit" },
  { key: "visit_duration", label: "Visit Duration" },
  { key: "bounce_rate", label: "Bounce Rate" },
];
const aggregateMetricKeys = ["pageviews", "uniques", "sessions", "conversions", "revenue"] as const;
const breakdownDimensions: BreakdownDimension[] = ["sources", "pages", "devices", "countries", "conversions", "hour_of_day", "day_of_week"];
const timezoneOptions = [
  "UTC",
  "America/Chicago",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
] as const;
const goalEligibleMetrics = ["revenue", "conversions", "pageviews", "sessions", "uniques"] as const;
type GoalMetric = (typeof goalEligibleMetrics)[number];
type GoalRepeat = "monthly";

interface MetricGoal {
  metric: GoalMetric;
  target: number;
  periodDays: number;
  repeat: GoalRepeat;
  updatedAt: string;
}

type SiteGoalsMap = Partial<Record<GoalMetric, MetricGoal>>;
type GoalStore = Record<string, SiteGoalsMap>;
const DASHBOARD_GOALS_STORAGE_KEY = "valid_dashboard_metric_goals_v1";

const readGoalStore = (): GoalStore => {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(DASHBOARD_GOALS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as GoalStore;
  } catch {
    return {};
  }
};

const extractApiErrorMessage = (error: unknown): string | null => {
  if (!error || typeof error !== "object") return null;
  const maybeError = error as { response?: { status?: number; data?: { detail?: string } } };
  const status = maybeError.response?.status;
  const detail = maybeError.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (status === 403) {
    return "This account does not have access to this site. Log out and sign in with the correct account.";
  }
  if (status === 401) {
    return "Your session is not valid for this site. Log out and sign in again.";
  }
  return null;
};

const statusToneClass = (status: "ok" | "warning" | "error" | string): string => {
  if (status === "ok" || status === "completed") return "bg-emerald-50 text-emerald-700";
  if (status === "error" || status === "failed") return "bg-[#FFF1F2] text-[#8B2635]";
  if (status === "rolled_back") return "bg-gray-100 text-gray-700";
  return "bg-[#EEF2FF] text-[#4f46e5]";
};

const formatDateTime = (value?: string | null): string => {
  if (!value) return "—";
  return new Date(value).toLocaleString();
};

const writeGoalStore = (store: GoalStore) => {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DASHBOARD_GOALS_STORAGE_KEY, JSON.stringify(store));
};

const loadGoalsForSite = (siteId: string): SiteGoalsMap => {
  const store = readGoalStore();
  return store[siteId] ?? {};
};

const upsertGoalForSite = (
  siteId: string,
  goal: { metric: GoalMetric; target: number; periodDays?: number; repeat?: GoalRepeat }
): SiteGoalsMap => {
  const store = readGoalStore();
  const current = store[siteId] ?? {};
  const nextGoal: MetricGoal = {
    metric: goal.metric,
    target: Math.max(0, goal.target),
    periodDays: goal.periodDays ?? 30,
    repeat: goal.repeat ?? "monthly",
    updatedAt: new Date().toISOString(),
  };
  const next = { ...current, [goal.metric]: nextGoal };
  store[siteId] = next;
  writeGoalStore(store);
  return next;
};

const removeGoalForSite = (siteId: string, metric: GoalMetric): SiteGoalsMap => {
  const store = readGoalStore();
  const current = { ...(store[siteId] ?? {}) };
  delete current[metric];
  store[siteId] = current;
  writeGoalStore(store);
  return current;
};

const rangeOptions = ["Today", "Yesterday", "Last 7", "Last 30", "Last 90", "MTD", "YTD", "Custom"] as const;
const forecastOptions = [
  { key: "7d", label: "Next 7 Days", kind: "days", days: 7 },
  { key: "30d", label: "Next 30 Days", kind: "days", days: 30 },
  { key: "60d", label: "Next 60 Days", kind: "days", days: 60 },
  { key: "90d", label: "Next 90 Days", kind: "days", days: 90 },
  { key: "q1", label: "Q1", kind: "quarter", quarter: 1 },
  { key: "q2", label: "Q2", kind: "quarter", quarter: 2 },
  { key: "q3", label: "Q3", kind: "quarter", quarter: 3 },
  { key: "q4", label: "Q4", kind: "quarter", quarter: 4 },
] as const;

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const formatDuration = (seconds: number) => {
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
  if (!Number.isFinite(value)) return "N/A";
  if (metric === "revenue") return formatCurrency(value);
  if (metric === "visit_duration") return formatDuration(value);
  if (metric.includes("rate")) return formatPercent(value);
  return formatNumber(value);
};

const formatDailyPace = (metric: string, value: number) => {
  if (!Number.isFinite(value)) return "—";
  if (metric === "revenue") return `${formatCurrency(value)}/day`;
  if (Math.abs(value) < 10 && !Number.isInteger(value)) return `${value.toFixed(1)}/day`;
  return `${formatNumber(value)}/day`;
};

const MAX_PUBLISHED_FORECAST_ACCURACY_MAPE = 0.5;

const metricSupportsGoals = (metric: string): metric is GoalMetric =>
  (goalEligibleMetrics as readonly string[]).includes(metric);

const formatCompactCurrency = (value: number) => {
  if (!Number.isFinite(value)) return "—";
  const absValue = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const format = (amount: number) => (amount % 1 === 0 ? amount.toFixed(0) : amount.toFixed(1));
  if (absValue >= 1_000_000_000) return `${sign}$${format(absValue / 1_000_000_000)}b`;
  if (absValue >= 1_000_000) return `${sign}$${format(absValue / 1_000_000)}m`;
  if (absValue >= 1_000) return `${sign}$${format(absValue / 1_000)}k`;
  return `${sign}$${Math.round(absValue)}`;
};

const formatAxisDate = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const formatTooltipDate = (value: string) =>
  new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

type ChartGranularity = "day" | "week" | "month";

// Returns the ISO date (YYYY-MM-DD) marking the start of the bucket that contains `day`.
// Weeks start on Monday so partial weeks line up with common analytics conventions.
const bucketKeyFor = (day: string, granularity: ChartGranularity): string => {
  if (granularity === "day") return day;
  const date = new Date(`${day}T00:00:00Z`);
  if (granularity === "month") {
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-01`;
  }
  const weekday = (date.getUTCDay() + 6) % 7;
  const monday = new Date(date);
  monday.setUTCDate(date.getUTCDate() - weekday);
  return monday.toISOString().slice(0, 10);
};

const formatAxisDateGranular = (value: string, granularity: ChartGranularity): string => {
  const d = new Date(`${value}T00:00:00`);
  if (granularity === "month") return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const formatTooltipDateGranular = (value: string, granularity: ChartGranularity): string => {
  const d = new Date(`${value}T00:00:00`);
  if (granularity === "month") {
    return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }
  if (granularity === "week") {
    return `Week of ${d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
  }
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
};

const granularityLabel = (granularity: ChartGranularity): string =>
  granularity === "month" ? "monthly" : granularity === "week" ? "weekly" : "daily";
const formatRangeLabel = (start: string, end: string) => {
  const startDate = parseDay(start);
  const endDate = parseDay(end);
  const sameDay = start === end;
  if (sameDay) {
    return startDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }
  if (startDate.getFullYear() === endDate.getFullYear()) {
    if (startDate.getMonth() === endDate.getMonth()) {
      return `${startDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })} - ${endDate.toLocaleDateString(
        undefined,
        { day: "numeric", year: "numeric" }
      )}`;
    }
    return `${startDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })} - ${endDate.toLocaleDateString(
      undefined,
      { month: "short", day: "numeric", year: "numeric" }
    )}`;
  }
  return `${startDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} - ${endDate.toLocaleDateString(
    undefined,
    { month: "short", day: "numeric", year: "numeric" }
  )}`;
};

const safeRatio = (numerator: number, denominator: number) =>
  Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0 ? numerator / denominator : Number.NaN;

const deriveBounceRate = (sessions: number, pageviews: number) => {
  if (!Number.isFinite(sessions) || sessions <= 0) return Number.NaN;
  const extraPageviews = Math.max(0, pageviews - sessions);
  const engagedSessions = Math.min(sessions, extraPageviews);
  return clamp(1 - engagedSessions / sessions, 0, 1);
};

const deriveVisitDurationSeconds = (avgPagesPerVisit: number, bounceRate: number) => {
  if (!Number.isFinite(avgPagesPerVisit) || !Number.isFinite(bounceRate)) return Number.NaN;
  return clamp((avgPagesPerVisit - 1) * 45 + (1 - bounceRate) * 30, 0, 1800);
};

type ForecastOption = (typeof forecastOptions)[number];
type RangeOption = (typeof rangeOptions)[number];
type DateRange = { start: string; end: string };

const parseDay = (day: string) => new Date(`${day}T00:00:00`);
const formatIsoDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const MS_PER_DAY = 86_400_000;

const getQuarterWindow = (quarter: number, reference: Date) => {
  const currentQuarter = Math.floor(reference.getMonth() / 3) + 1;
  let year = reference.getFullYear();
  if (quarter < currentQuarter) {
    year += 1;
  }
  const start = new Date(year, (quarter - 1) * 3, 1);
  const end = new Date(year, quarter * 3, 0);
  return { start, end, label: `Q${quarter} ${year}` };
};

const resolveForecastWindow = (
  entries: ForecastEntry[],
  lastActualDay: string | null,
  option: ForecastOption
) => {
  const referenceDate = lastActualDay ? parseDay(lastActualDay) : new Date();
  if (entries.length === 0) {
    const label = option.kind === "quarter" ? getQuarterWindow(option.quarter, referenceDate).label : option.label;
    return { label, entries: [] as ForecastEntry[] };
  }
  if (option.kind === "days") {
    if (!lastActualDay) {
      return { label: option.label, entries: entries.slice(0, option.days) };
    }
    const start = parseDay(lastActualDay);
    start.setDate(start.getDate() + 1);
    const end = new Date(start);
    end.setDate(end.getDate() + option.days - 1);
    const windowEntries = entries.filter((entry) => {
      const day = parseDay(entry.day);
      return day >= start && day <= end;
    });
    return { label: option.label, entries: windowEntries };
  }
  const { start, end, label } = getQuarterWindow(option.quarter, referenceDate);
  const windowEntries = entries.filter((entry) => {
    const day = parseDay(entry.day);
    return day >= start && day <= end;
  });
  return { label, entries: windowEntries };
};

type BreakdownMetricTotals = Partial<Record<BreakdownMetricKey, number>>;

interface BreakdownTableRow {
  label: string;
  metrics: BreakdownMetricTotals;
}

interface ActiveFilter {
  dimension: string;
  value: string;
  share: number;
}

interface BreakdownData {
  rows: BreakdownTableRow[];
  total: number;
  primaryMetric: BreakdownMetricKey;
  metricKeys: BreakdownMetricKey[];
}

interface ComparisonPoint {
  day: string;
  value: number;
}

interface TrendChartPoint {
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

const DeviceIcon: React.FC<{ label: string }> = ({ label }) => {
  const commonProps = {
    width: 14,
    height: 14,
    viewBox: "0 0 14 14",
    fill: "none",
    stroke: "#94A3B8",
    strokeWidth: 1.3,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (label === "Mobile") {
    return (
      <svg {...commonProps}>
        <rect x="4" y="1.5" width="6" height="11" rx="1.6" />
        <path d="M6.3 10.2h1.4" />
      </svg>
    );
  }

  if (label === "Tablet") {
    return (
      <svg {...commonProps}>
        <rect x="2.7" y="1.7" width="8.6" height="10.6" rx="1.2" />
        <path d="M6.2 10.4h1.6" />
      </svg>
    );
  }

  return (
    <svg {...commonProps}>
      <rect x="1.7" y="2" width="10.6" height="7" rx="1" />
      <path d="M4.7 11.5h4.6" />
      <path d="M7 9v2.5" />
    </svg>
  );
};

const renderBreakdownLabel = (dimension: string | undefined, label: string) => {
  if (dimension !== "device") return label;
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <DeviceIcon label={label} />
      <span className="truncate">{label}</span>
    </span>
  );
};

const filterDimensionLabels: Record<string, string> = {
  channel: "Channel",
  source: "Source",
  source_medium: "Source / Medium",
  campaign: "Campaign",
  content: "Content",
  term: "Term",
  page: "Page",
  country: "Country",
  device: "Device",
  goal: "Goal",
  hour_of_day: "Hour",
  day_of_week: "Day",
};

const renderFilterDimensionLabel = (dimension: string): string =>
  filterDimensionLabels[dimension] ??
  dimension
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

const breakdownFallbackDimensionLabels: Record<string, string> = {
  acquisition: "Channel",
  "traffic sources": "Channel",
  "top pages": "Page",
  countries: "Country",
  devices: "Device",
  goals: "Goal",
  "time parting": "Time",
};

const getBreakdownDimensionHeaderLabel = (title: string, rowDimension?: string): string => {
  if (rowDimension) return renderFilterDimensionLabel(rowDimension);
  return breakdownFallbackDimensionLabels[title.toLowerCase()] ?? "Dimension";
};

const breakdownBarColorsByDimension: Record<string, string> = {
  channel: "#eef2ff",
  source: "#eef2ff",
  source_medium: "#eef2ff",
  campaign: "#eef2ff",
  content: "#eef2ff",
  term: "#eef2ff",
  page: "#eef2ff",
  country: "#eef2ff",
  device: "#eef2ff",
  goal: "#eef2ff",
  hour_of_day: "#eef2ff",
  day_of_week: "#eef2ff",
  hostname: "#eef2ff",
};

const getBreakdownBarColor = (rowDimension?: string): string =>
  (rowDimension && breakdownBarColorsByDimension[rowDimension]) || "#eef2ff";

const createEmptyBreakdownData = (
  primaryMetric: BreakdownMetricKey,
  metricKeys: BreakdownMetricKey[] = [primaryMetric]
): BreakdownData => ({
  rows: [],
  total: 0,
  primaryMetric,
  metricKeys,
});

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const isoDayForDateInTimeZone = (value: Date, timeZone: string): string => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  const day = parts.find((part) => part.type === "day")?.value;
  if (!year || !month || !day) return formatIsoDate(value);
  return `${year}-${month}-${day}`;
};
const isoDayInTimeZone = (isoTimestamp: string, timeZone: string) =>
  isoDayForDateInTimeZone(new Date(isoTimestamp), timeZone);

const dayForAggregateWindow = (window: AggregateWindow, timeZone: string): string => {
  const startMs = new Date(window.window_start).getTime();
  const endMs = new Date(window.window_end).getTime();
  const durationMs = endMs - startMs;
  const isDailyBucket = Number.isFinite(durationMs) && durationMs >= 20 * 60 * 60 * 1000;
  if (isDailyBucket) return window.window_start.slice(0, 10);
  return isoDayInTimeZone(window.window_start, timeZone);
};

const resolveRangeBounds = (
  rangeKey: RangeOption,
  custom: DateRange,
  timeZone: string = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
): { start: string; end: string } | null => {
  const todayDay = isoDayForDateInTimeZone(new Date(), timeZone);
  const end = parseDay(todayDay);
  const start = parseDay(todayDay);

  if (rangeKey === "Custom") {
    if (!custom.start || !custom.end) return null;
    const startDate = parseDay(custom.start);
    const endDate = parseDay(custom.end);
    const from = startDate <= endDate ? startDate : endDate;
    const to = startDate <= endDate ? endDate : startDate;
    return { start: formatIsoDate(from), end: formatIsoDate(to) };
  }

  if (rangeKey === "Today") {
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  if (rangeKey === "Yesterday") {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  if (rangeKey === "Last 7") {
    start.setDate(start.getDate() - 6);
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  if (rangeKey === "Last 30") {
    start.setDate(start.getDate() - 29);
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  if (rangeKey === "Last 90") {
    start.setDate(start.getDate() - 89);
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  if (rangeKey === "MTD") {
    const first = new Date(end.getFullYear(), end.getMonth(), 1);
    return { start: formatIsoDate(first), end: formatIsoDate(end) };
  }
  if (rangeKey === "YTD") {
    const jan1 = new Date(end.getFullYear(), 0, 1);
    return { start: formatIsoDate(jan1), end: formatIsoDate(end) };
  }
  return null;
};

const enumerateDays = (startDay: string, endDay: string): string[] => {
  const start = parseDay(startDay);
  const end = parseDay(endDay);
  const from = start <= end ? start : end;
  const to = start <= end ? end : start;
  const days: string[] = [];
  for (let cursor = new Date(from); cursor <= to; cursor.setDate(cursor.getDate() + 1)) {
    days.push(formatIsoDate(cursor));
  }
  return days;
};

type DailyValuePoint = { day: string; value: number };

const fillMissingDaysWithZero = (
  entries: DailyValuePoint[],
  rangeStart: string,
  rangeEnd: string,
  observedCountDays: Set<string>,
  earliestObservedCountDay: string | null,
  latestObservedCountDay: string | null
): DailyValuePoint[] => {
  if (!earliestObservedCountDay || !latestObservedCountDay) {
    return entries;
  }
  const fromCoverage = rangeStart > earliestObservedCountDay ? rangeStart : earliestObservedCountDay;
  const toCoverage = rangeEnd < latestObservedCountDay ? rangeEnd : latestObservedCountDay;
  if (fromCoverage > toCoverage) {
    return entries;
  }
  const byDay = new Map(entries.map((entry) => [entry.day, entry.value]));
  const result: DailyValuePoint[] = [];
  for (const day of enumerateDays(rangeStart, rangeEnd)) {
    const existing = byDay.get(day);
    if (existing !== undefined) {
      result.push({ day, value: existing });
      continue;
    }
    const inReducerCoverage = day >= fromCoverage && day <= toCoverage;
    const hasAnyCountSignal = observedCountDays.has(day);
    if (inReducerCoverage && !hasAnyCountSignal) {
      result.push({ day, value: 0 });
    }
  }
  return result;
};

const buildSeededDailySeries = (days: number = 180) => {
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  const start = new Date(end);
  start.setDate(start.getDate() - (days - 1));
  const allDays = enumerateDays(formatIsoDate(start), formatIsoDate(end));

  const seeded = {
    pageviews: [] as { day: string; value: number }[],
    uniques: [] as { day: string; value: number }[],
    sessions: [] as { day: string; value: number }[],
    conversions: [] as { day: string; value: number }[],
    revenue: [] as { day: string; value: number }[],
    visit_duration: [] as { day: string; value: number }[],
  };

  allDays.forEach((day, index) => {
    const seasonal = 1 + Math.sin((index / 7) * Math.PI * 2) * 0.14;
    const trend = 0.78 + index / (days * 1.85);
    const base = Math.max(24, Math.round(190 * seasonal * trend));
    const pageviews = base;
    const uniques = Math.max(12, Math.round(pageviews * 0.63));
    const sessions = Math.max(8, Math.round(uniques * 1.08));
    const conversions = Math.max(0, Math.round(sessions * 0.043));
    const revenue = Math.max(0, Math.round(conversions * 42));
    const visitDuration = 112 + Math.round((index % 9) * 4);

    seeded.pageviews.push({ day, value: pageviews });
    seeded.uniques.push({ day, value: uniques });
    seeded.sessions.push({ day, value: sessions });
    seeded.conversions.push({ day, value: conversions });
    seeded.revenue.push({ day, value: revenue });
    seeded.visit_duration.push({ day, value: visitDuration });
  });

  return seeded;
};

const buildSeededForecast = (entries: { day: string; value: number }[], horizonDays: number = 120): ForecastEntry[] => {
  if (!entries.length) return [];
  const sorted = [...entries].sort((a, b) => a.day.localeCompare(b.day));
  const recent = sorted.slice(-Math.min(28, sorted.length)).map((row) => row.value);
  const average = recent.reduce((sum, value) => sum + value, 0) / Math.max(1, recent.length);
  const firstRecent = recent[0] ?? average;
  const lastRecent = recent[recent.length - 1] ?? average;
  const trendPerDay = (lastRecent - firstRecent) / Math.max(1, recent.length - 1);
  const variance =
    recent.reduce((sum, value) => {
      const delta = value - average;
      return sum + delta * delta;
    }, 0) / Math.max(1, recent.length);
  const sigma = Math.max(1, Math.sqrt(variance));
  const lastDay = parseDay(sorted[sorted.length - 1].day);

  const forecast: ForecastEntry[] = [];
  const cappedHorizon = Math.max(1, horizonDays);
  for (let i = 1; i <= cappedHorizon; i += 1) {
    const day = new Date(lastDay);
    day.setDate(day.getDate() + i);
    const seasonal = 1 + Math.sin(((sorted.length + i) / 7) * Math.PI * 2) * 0.09;
    const yhat = Math.max(0, (average + trendPerDay * i) * seasonal);
    const band = 1.2816 * sigma;
    forecast.push({
      day: formatIsoDate(day),
      yhat,
      yhat_lower: Math.max(0, yhat - band),
      yhat_upper: Math.max(0, yhat + band),
    });
  }
  return forecast;
};

const getBreakdownMetricValue = (row: BreakdownTableRow, metric: BreakdownMetricKey) => row.metrics[metric] ?? 0;

const aggregateRowsByLabel = (rows: BreakdownTableRow[]) => {
  const bucket = new Map<string, BreakdownMetricTotals>();
  rows.forEach((row) => {
    const existing = bucket.get(row.label) ?? {};
    const next: BreakdownMetricTotals = { ...existing };
    Object.entries(row.metrics).forEach(([metric, value]) => {
      next[metric as BreakdownMetricKey] = (next[metric as BreakdownMetricKey] ?? 0) + value;
    });
    bucket.set(row.label, next);
  });
  return Array.from(bucket.entries())
    .map(([label, metrics]) => ({ label, metrics }))
    .sort((a, b) => {
      const aPrimary = getBreakdownMetricValue(a, "sessions") || getBreakdownMetricValue(a, "pageviews");
      const bPrimary = getBreakdownMetricValue(b, "sessions") || getBreakdownMetricValue(b, "pageviews");
      return bPrimary - aPrimary || a.label.localeCompare(b.label);
    });
};

const SunIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <circle cx="8" cy="8" r="3" />
    <line x1="8" y1="1.5" x2="8" y2="3" />
    <line x1="8" y1="13" x2="8" y2="14.5" />
    <line x1="1.5" y1="8" x2="3" y2="8" />
    <line x1="13" y1="8" x2="14.5" y2="8" />
    <line x1="3.4" y1="3.4" x2="4.4" y2="4.4" />
    <line x1="11.6" y1="11.6" x2="12.6" y2="12.6" />
    <line x1="3.4" y1="12.6" x2="4.4" y2="11.6" />
    <line x1="11.6" y1="4.4" x2="12.6" y2="3.4" />
  </svg>
);

const MoonIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5 a4.5 4.5 0 0 0 7 7Z" />
  </svg>
);

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggleTheme}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#DDE4EC] bg-white text-[#5F6673] shadow-sm transition-colors hover:border-[#C7D0DC] hover:text-[#4338ca] no-print"
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
};

const ExpandIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <polyline points="3 6.5 3 3 6.5 3" />
    <polyline points="9.5 3 13 3 13 6.5" />
    <polyline points="13 9.5 13 13 9.5 13" />
    <polyline points="6.5 13 3 13 3 9.5" />
  </svg>
);

const CloseIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <line x1="4" y1="4" x2="12" y2="12" />
    <line x1="12" y1="4" x2="4" y2="12" />
  </svg>
);

const TableBlock: React.FC<{
  title: string;
  header?: React.ReactNode;
  rows: BreakdownTableRow[];
  metricKeys: BreakdownMetricKey[];
  primaryMetric: BreakdownMetricKey;
  total?: number;
  emptyState?: string;
  rowDimension?: string;
  activeFilters?: ActiveFilter[];
  onToggleFilter?: (dimension: string, row: BreakdownTableRow, total: number, primaryMetric: BreakdownMetricKey) => void;
}> = ({ title, header, rows, metricKeys, primaryMetric, total, emptyState, rowDimension, activeFilters, onToggleFilter }) => {
  const [expanded, setExpanded] = useState(false);
  const maxValue = rows.reduce((max, row) => Math.max(max, getBreakdownMetricValue(row, primaryMetric)), 0);
  const totalValue = total ?? rows.reduce((sum, row) => sum + getBreakdownMetricValue(row, primaryMetric), 0);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [expanded]);

  const renderRows = (compact: boolean) => {
    if (rows.length === 0) {
      return (
        <div className="py-6 text-xs text-gray-400" style={fontBody}>
          {emptyState ?? "Awaiting events. This table will populate after data arrives."}
        </div>
      );
    }
    const dimensionLabel = getBreakdownDimensionHeaderLabel(title, rowDimension);
    const metricMinWidth = compact ? "minmax(64px,auto)" : "minmax(86px,auto)";
    const gridTemplateColumns = `minmax(0,1fr) ${metricKeys.map(() => metricMinWidth).join(" ")}`;
    const gridStyle: React.CSSProperties = { gridTemplateColumns };
    const barColor = getBreakdownBarColor(rowDimension);
    return (
      <div className="space-y-1.5">
        <div
          className={`grid items-center gap-2 border-b border-[var(--color-border-subtle)] pb-2 text-[11px] text-[#6B7280] ${
            compact ? "" : "text-xs"
          }`}
          style={{ ...fontBody, ...gridStyle }}
        >
          <div className="uppercase tracking-[0.06em]">{dimensionLabel}</div>
          {metricKeys.map((metricKey) => (
            <div key={metricKey} className="text-right uppercase tracking-[0.06em]">
              {breakdownMetricInlineLabels[metricKey]}
            </div>
          ))}
        </div>
        {rows.map((row) => {
          const primaryValue = getBreakdownMetricValue(row, primaryMetric);
          const width = maxValue > 0 ? Math.max(5, (primaryValue / maxValue) * 100) : 0;
          const isActive = Boolean(
            rowDimension && activeFilters?.some((f) => f.dimension === rowDimension && f.value === row.label)
          );
          const labelClass = compact
            ? "truncate whitespace-nowrap"
            : "whitespace-normal break-words";
          const textSize = compact ? "text-[13px]" : "text-sm";
          return (
            <div key={row.label} className={compact ? "py-1" : "py-1.5"}>
              <div className="grid items-center gap-2" style={gridStyle}>
                <button
                  type="button"
                  className={`relative min-w-0 overflow-hidden rounded-sm px-2 py-1.5 text-left ${textSize} text-[#374151] transition-colors ${
                    rowDimension && onToggleFilter
                      ? isActive
                        ? "text-[#4338ca] underline decoration-[#4338ca] underline-offset-2"
                        : "hover:text-[#4338ca] hover:underline hover:decoration-[#4338ca] hover:underline-offset-2"
                      : ""
                  }`}
                  style={fontBody}
                  onClick={() => {
                    if (!rowDimension || !onToggleFilter) return;
                    onToggleFilter(rowDimension, row, totalValue, primaryMetric);
                  }}
                >
                  <span
                    className="pointer-events-none absolute inset-y-0 left-0 rounded-sm"
                    style={{ width: `${width}%`, backgroundColor: barColor }}
                  />
                  <span className={`relative z-10 block min-w-0 ${labelClass}`}>
                    {renderBreakdownLabel(rowDimension, row.label)}
                  </span>
                </button>
                {metricKeys.map((metricKey) => (
                  <div
                    key={metricKey}
                    className={`${textSize} whitespace-nowrap text-right font-medium text-[#111827] metric-number`}
                    style={fontMetric}
                  >
                    {formatMetricValue(metricKey, getBreakdownMetricValue(row, metricKey))}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="min-h-[280px] rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {header ? (
            header
          ) : (
            <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
              {title}
            </div>
          )}
        </div>
        <button
          type="button"
          aria-label={`Expand ${title}`}
          title="Expand"
          onClick={() => setExpanded(true)}
          className="shrink-0 p-1 text-gray-400 transition-colors hover:text-[#1F2937]"
        >
          <ExpandIcon />
        </button>
      </div>
      {renderRows(true)}
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#111827]/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={`${title} details`}
          onClick={() => setExpanded(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-subtle)] px-5 py-3">
              <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                {title}
              </div>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setExpanded(false)}
                className="p-1 text-gray-400 transition-colors hover:text-[#1F2937]"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="overflow-auto px-5 py-4">{renderRows(false)}</div>
          </div>
        </div>
      )}
    </div>
  );
};

const shortDayOfWeekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const hourTickIndexes = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22] as const;

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

const TimePartingHeatmap: React.FC<{
  hourRows: BreakdownTableRow[];
  dayRows: BreakdownTableRow[];
  primaryMetric: BreakdownMetricKey;
  dayType: TimePartingDayType;
  setDayType: (value: TimePartingDayType) => void;
  emptyState: string;
  rangeLabel: string;
}> = ({ hourRows, dayRows, primaryMetric, dayType, setDayType, emptyState, rangeLabel }) => {
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
        peakLabel = `${shortDayOfWeekLabels[dayIndex]} · ${hourOfDayLabels[hourIndex]}`;
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
      {!hasData ? (
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
              <React.Fragment key={dayIndex}>
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
              </React.Fragment>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#7B8190]" style={fontBody}>
            <span>
              Peak · <span className="font-semibold text-[#4B5563]">{peakLabel}</span>
            </span>
            <span>Period · {rangeLabel}</span>
          </div>
        </>
      )}
    </div>
  );
};

const GoalsProgressCard: React.FC<{
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
          const currentValue = values[goal.metric] ?? Number.NaN;
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
            <div key={goal.metric}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold text-[#374151]" style={fontBody}>
                    {metricLabels[goal.metric] ?? goal.metric}
                  </div>
                  <div className="mt-0.5 text-[11px] text-[#7B8190]" style={fontBody}>
                    Target · {formatMetricValue(goal.metric, targetForWindow)}
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
          Period · {rangeLabel}
        </div>
      </div>
    )}
  </div>
);

const LogoutButton: React.FC<{ className?: string }> = ({ className }) => {
  const { token, authEnabled, logout } = useAuth();
  const navigate = useNavigate();

  if (!authEnabled || !token) return null;

  return (
    <button
      type="button"
      onClick={() => {
        logout();
        navigate("/", { replace: true });
      }}
      className={className ?? "border border-gray-200 bg-white px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-gray-500 hover:border-gray-300 hover:text-[#1F2937]"}
      style={fontBody}
    >
      Log out
    </button>
  );
};

const formatSiteHost = (site: DashboardSiteSummary): string => {
  const raw = site.allowed_origin || site.site_id;
  try {
    return new URL(raw).hostname || raw;
  } catch {
    return raw.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }
};

const SitePicker: React.FC<{ sites: DashboardSiteSummary[]; error?: string | null }> = ({ sites, error }) => {
  const lastSiteId =
    typeof window !== "undefined" ? localStorage.getItem(LAST_SITE_ID_STORAGE_KEY) : null;

  return (
    <div className="min-h-screen bg-[#F7F8FA] px-6 py-8 text-[#111827]">
      <main className="mx-auto max-w-5xl">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <a href="/" className="text-[28px] font-bold tracking-[-0.01em] text-[#111827]" style={fontHeading}>
              Valid
            </a>
            <div className="mt-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-[#737B8C]" style={fontMeta}>
              Select a site
            </div>
          </div>
          <LogoutButton />
        </header>

        <section className="rounded-lg border border-[#DDE1E7] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#EEF1F4] pb-4">
            <div>
              <h1 className="text-xl font-semibold text-[#111827]" style={fontHeading}>
                Your dashboards
              </h1>
              <p className="mt-1 text-sm text-[#6B7280]" style={fontBody}>
                Choose the account you want to view.
              </p>
            </div>
            <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[#737B8C]" style={fontMeta}>
              {sites.length} {sites.length === 1 ? "site" : "sites"}
            </span>
          </div>

          {error && (
            <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" style={fontBody}>
              {error}
            </div>
          )}

          {sites.length === 0 ? (
            <div className="py-10 text-center text-sm text-[#6B7280]" style={fontBody}>
              No dashboards are available for this login.
            </div>
          ) : (
            <div className="divide-y divide-[#EEF1F4]">
              {sites.map((site) => {
                const isRecent = site.site_id === lastSiteId;
                return (
                  <a
                    key={site.site_id}
                    href={`/site/${encodeURIComponent(site.site_id)}`}
                    className="group flex flex-wrap items-center justify-between gap-4 py-4 text-left hover:bg-[#FAFBFC]"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-base font-semibold text-[#111827]" style={fontHeading}>
                          {site.site_name || site.site_id}
                        </span>
                        {isRecent && (
                          <span className="rounded border border-[#DDE1E7] bg-[#F7F8FA] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#737B8C]" style={fontMeta}>
                            Recent
                          </span>
                        )}
                        <span className="rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#737B8C]" style={fontMeta}>
                          {site.plan}
                        </span>
                      </div>
                      <div className="mt-1 truncate text-sm text-[#6B7280]" style={fontBody}>
                        {formatSiteHost(site)}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-[#9CA3AF]" style={fontMeta}>
                        {site.site_id}
                      </div>
                    </div>
                    <span className="text-sm font-semibold text-[#5B55FF] group-hover:text-[#4338CA]" style={fontBody}>
                      Open dashboard -&gt;
                    </span>
                  </a>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

const Overview: React.FC = () => {
  const { token, authEnabled } = useAuth();
  const canQuery = !authEnabled || Boolean(token);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { siteId: pathSiteId } = useParams<{ siteId?: string }>();
  const querySiteId = searchParams.get("site_id") ?? undefined;
  const hasExplicitSiteSelection = Boolean((querySiteId && querySiteId.trim()) || (pathSiteId && pathSiteId.trim()));
  const showSeededBreakdowns = ENABLE_DEMO_MODE && !hasExplicitSiteSelection;
  const siteId = useMemo(() => resolveActiveSiteId(querySiteId ?? pathSiteId), [querySiteId, pathSiteId]);

  useEffect(() => {
    const query = querySiteId?.trim();
    if (!pathSiteId && query) {
      navigate(`/site/${encodeURIComponent(query)}`, { replace: true });
    }
  }, [navigate, pathSiteId, querySiteId]);
  useEffect(() => {
    if (hasExplicitSiteSelection && siteId) {
      localStorage.setItem(LAST_SITE_ID_STORAGE_KEY, siteId);
    }
  }, [hasExplicitSiteSelection, siteId]);
  const [selectedMetric, setSelectedMetric] = useState<string>(() => {
    const m = searchParams.get("metric");
    return m && metricLabels[m] ? m : "pageviews";
  });
  const [range, setRange] = useState<RangeOption>(() => {
    const r = searchParams.get("range");
    return r && (rangeOptions as readonly string[]).includes(r) ? (r as RangeOption) : "Last 30";
  });
  const [selectedHostname, setSelectedHostname] = useState<string>(() => {
    const host = searchParams.get("hostname");
    return host && host.trim() ? host.trim() : "all";
  });
  const [siteTimezone, setSiteTimezone] = useState<string>("UTC");
  const [siteGoals, setSiteGoals] = useState<SiteGoalsMap>({});
  const [forecastKey, setForecastKey] = useState<(typeof forecastOptions)[number]["key"]>(() => {
    const fk = searchParams.get("forecast");
    return fk && forecastOptions.some((opt) => opt.key === fk)
      ? (fk as ForecastOption["key"])
      : "30d";
  });
  const [forecast, setForecast] = useState<ForecastEntry[]>([]);
  const [forecastMeta, setForecastMeta] = useState<Pick<ForecastResponse, "mape" | "has_anomaly"> | null>(
    null
  );
  const [dashboardNotes, setDashboardNotes] = useState<DashboardNote[]>([]);
  const [noteDate, setNoteDate] = useState<string>("");
  const [noteBody, setNoteBody] = useState<string>("");
  const [noteStatus, setNoteStatus] = useState<string | null>(null);
  const [isSavingNote, setIsSavingNote] = useState(false);
  const [isNoteComposerOpen, setIsNoteComposerOpen] = useState(false);
  const [hoveredNoteMarkerDay, setHoveredNoteMarkerDay] = useState<string | null>(null);
  const [selectedNoteMarkerDay, setSelectedNoteMarkerDay] = useState<string | null>(null);
  const [aggregateMap, setAggregateMap] = useState<Record<string, AggregateWindow[]>>({});
  const [breakdownData, setBreakdownData] = useState<Record<BreakdownDimension, BreakdownData>>({
    sources: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
    pages: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews"]),
    devices: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
    countries: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
    conversions: createEmptyBreakdownData("conversions", ["uniques", "sessions", "conversions"]),
    hour_of_day: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
    day_of_week: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
    hostnames: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  });
  const [hostnameOptions, setHostnameOptions] = useState<string[]>([]);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [customRange, setCustomRange] = useState<DateRange>(() => ({
    start: searchParams.get("start") ?? "",
    end: searchParams.get("end") ?? "",
  }));
  const [compareEnabled, setCompareEnabled] = useState<boolean>(() => searchParams.get("cmp") === "1");
  const [compareMode, setCompareMode] = useState<"previous" | "custom">(() => {
    const m = searchParams.get("cmpMode");
    return m === "custom" ? "custom" : "previous";
  });
  const [compareRange, setCompareRange] = useState<DateRange>(() => ({
    start: searchParams.get("cmpStart") ?? "",
    end: searchParams.get("cmpEnd") ?? "",
  }));
  const [acquisitionTab, setAcquisitionTab] = useState<"channels" | "sources" | "source_medium" | "campaigns">(() => {
    const t = searchParams.get("tab");
    if (t === "sources" || t === "source_medium" || t === "campaigns") return t;
    return "channels";
  });
  const [campaignDimension, setCampaignDimension] = useState<"campaign" | "content" | "term">(() => {
    const c = searchParams.get("camp");
    if (c === "content" || c === "term") return c;
    return "campaign";
  });
  const [timePartingDayType, setTimePartingDayType] = useState<TimePartingDayType>(() => {
    const raw = searchParams.get("tpDays");
    return raw === "weekday" || raw === "weekend" ? raw : "all";
  });
  const [activeFilters, setActiveFilters] = useState<ActiveFilter[]>(() => {
    const raw = searchParams.get("filter");
    if (!raw) return [];
    return raw
      .split(",")
      .filter(Boolean)
      .map((pair): ActiveFilter | null => {
        const idx = pair.indexOf(":");
        if (idx < 0) return null;
        const dim = pair.slice(0, idx);
        const val = decodeURIComponent(pair.slice(idx + 1));
        if (!dim || !val) return null;
        return { dimension: dim, value: val, share: 1 };
      })
      .filter((x): x is ActiveFilter => Boolean(x));
  });
  const [exportFormat, setExportFormat] = useState<"csv" | "pdf">("csv");
  const [exportMode, setExportMode] = useState<"current" | "all">("current");
  const [dismissedAnomalies, setDismissedAnomalies] = useState<Set<string>>(() => new Set());
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const chartGridStroke = isDark ? "rgba(249,250,251,0.10)" : "#E5E7EB";
  const chartAxisTick = isDark ? "rgba(249,250,251,0.55)" : "#6B7280";
  const chartReferenceStroke = isDark ? "rgba(249,250,251,0.25)" : "#D1D5DB";
  const hostnameFilter = !showSeededBreakdowns && selectedHostname !== "all" ? selectedHostname : undefined;

  useEffect(() => {
    if (!canQuery || showSeededBreakdowns) return;
    let cancelled = false;
    fetchSiteSettings(token ?? undefined, siteId)
      .then((settings) => {
        if (!cancelled) setSiteTimezone(settings.timezone || "UTC");
      })
      .catch(() => {
        if (!cancelled) setSiteTimezone("UTC");
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, showSeededBreakdowns, token, siteId]);

  useEffect(() => {
    setSiteGoals(loadGoalsForSite(siteId));
  }, [siteId]);

  const previousSiteIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (previousSiteIdRef.current === null) {
      previousSiteIdRef.current = siteId;
      return;
    }
    if (previousSiteIdRef.current !== siteId) {
      previousSiteIdRef.current = siteId;
      setActiveFilters([]);
      setSelectedHostname("all");
    }
  }, [siteId]);
  useEffect(() => {
    if (!canQuery) return;
    const metricsToFetch = [...aggregateMetricKeys];
    Promise.all(
      metricsToFetch.map((metric) =>
        fetchAggregate(metric, "standard", token ?? undefined, siteId, hostnameFilter).then((data) => ({
          metric,
          data,
        }))
      )
    )
      .then((results) => {
        setAccessError(null);
        const next: Record<string, AggregateWindow[]> = {};
        results.forEach((item) => {
          next[item.metric] = item.data;
        });
        setAggregateMap(next);
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        if (message) setAccessError(message);
        console.error(error);
      });
  }, [canQuery, token, siteId, hostnameFilter]);

  useEffect(() => {
    if (!aggregateMetricKeys.includes(selectedMetric as (typeof aggregateMetricKeys)[number])) {
      setForecast([]);
      setForecastMeta(null);
      return;
    }
    if (showSeededBreakdowns) {
      let seededMetricSeries: { day: string; value: number }[] = [];
      if (selectedMetric === "pageviews") seededMetricSeries = seededSeries.pageviews;
      else if (selectedMetric === "uniques") seededMetricSeries = seededSeries.uniques;
      else if (selectedMetric === "sessions") seededMetricSeries = seededSeries.sessions;
      else if (selectedMetric === "conversions") seededMetricSeries = seededSeries.conversions;
      else if (selectedMetric === "revenue") seededMetricSeries = seededSeries.revenue;
      setForecast(buildSeededForecast(seededMetricSeries, 120));
      setForecastMeta({ mape: 0.08, has_anomaly: false });
      return;
    }
    if (!canQuery) return;
    fetchForecast(token ?? undefined, selectedMetric, siteId)
      .then((data) => {
        setAccessError(null);
        setForecast(data.forecast);
        setForecastMeta({ mape: data.mape, has_anomaly: data.has_anomaly });
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        if (message) setAccessError(message);
        console.error(error);
      });
  }, [canQuery, token, selectedMetric, siteId, showSeededBreakdowns]);

  const toDaily = (windows: AggregateWindow[]) => {
    const bucket: Record<string, number> = {};
    windows.forEach((window) => {
      const day = dayForAggregateWindow(window, siteTimezone);
      bucket[day] = (bucket[day] ?? 0) + window.value;
    });
    const entries = Object.entries(bucket)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([day, value]) => ({ day, value }));
    return entries;
  };

  const filterByRange = (
    entries: { day: string; value: number }[],
    rangeKey: RangeOption = range,
    custom: DateRange = customRange
  ) => {
    if (entries.length === 0) return entries;
    const bounds = resolveRangeBounds(rangeKey, custom, siteTimezone);
    if (!bounds) return entries;
    return entries.filter((entry) => entry.day >= bounds.start && entry.day <= bounds.end);
  };
  const maybeFillMissingDailyZeros = (
    metric: string,
    entries: DailyValuePoint[],
    rangeKey: RangeOption = range,
    custom: DateRange = customRange
  ): DailyValuePoint[] => {
    const isCountMetric = ["pageviews", "uniques", "sessions", "conversions", "revenue"].includes(metric);
    if (!isCountMetric) return entries;
    const bounds = resolveRangeBounds(rangeKey, custom, siteTimezone);
    if (!bounds) return entries;
    return fillMissingDaysWithZero(
      entries,
      bounds.start,
      bounds.end,
      observedCountDaySet,
      earliestObservedCountDay,
      latestObservedCountDay
    );
  };

  const buildMetricRows = (
    labels: string[],
    weights: number[],
    totalsByMetric: BreakdownMetricTotals
  ): BreakdownTableRow[] => {
    const weightSum = weights.reduce((sum, weight) => sum + weight, 0) || 1;
    return labels.map((label, index) => {
      const share = weights[index] / weightSum;
      const metrics = Object.entries(totalsByMetric).reduce<BreakdownMetricTotals>((acc, [metric, totalValue]) => {
        if (typeof totalValue === "number" && Number.isFinite(totalValue) && totalValue > 0) {
          acc[metric as BreakdownMetricKey] = Math.round(totalValue * share);
        }
        return acc;
      }, {});
      return { label, metrics };
    });
  };

  const mapByDay = (entries: { day: string; value: number }[]) => new Map(entries.map((entry) => [entry.day, entry.value]));
  const makeDerivedSeries = (
    dayValues: string[],
    compute: (day: string) => number
  ) =>
    dayValues
      .map((day) => ({ day, value: compute(day) }))
      .filter((entry) => Number.isFinite(entry.value));

  const seededSeries = useMemo(() => buildSeededDailySeries(210), []);
  const pageviewsAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.pageviews : toDaily(aggregateMap.pageviews ?? [])),
    [showSeededBreakdowns, seededSeries.pageviews, aggregateMap, siteTimezone]
  );
  const uniquesAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.uniques : toDaily(aggregateMap.uniques ?? [])),
    [showSeededBreakdowns, seededSeries.uniques, aggregateMap, siteTimezone]
  );
  const sessionsAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.sessions : toDaily(aggregateMap.sessions ?? [])),
    [showSeededBreakdowns, seededSeries.sessions, aggregateMap, siteTimezone]
  );
  const conversionsAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.conversions : toDaily(aggregateMap.conversions ?? [])),
    [showSeededBreakdowns, seededSeries.conversions, aggregateMap, siteTimezone]
  );
  const revenueAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.revenue : toDaily(aggregateMap.revenue ?? [])),
    [showSeededBreakdowns, seededSeries.revenue, aggregateMap, siteTimezone]
  );
  const durationAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.visit_duration : toDaily(aggregateMap.avg_time_on_site ?? [])),
    [showSeededBreakdowns, seededSeries.visit_duration, aggregateMap, siteTimezone]
  );
  const observedCountDayList = useMemo(() => {
    const set = new Set<string>();
    [pageviewsAll, uniquesAll, sessionsAll, conversionsAll, revenueAll].forEach((series) => {
      series.forEach((entry) => set.add(entry.day));
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [pageviewsAll, uniquesAll, sessionsAll, conversionsAll, revenueAll]);
  const observedCountDaySet = useMemo(() => new Set(observedCountDayList), [observedCountDayList]);
  const earliestObservedCountDay = observedCountDayList[0] ?? null;
  const latestObservedCountDay =
    observedCountDayList.length > 0 ? observedCountDayList[observedCountDayList.length - 1] : null;

  const dailyPageviews = useMemo(
    () => maybeFillMissingDailyZeros("pageviews", filterByRange(pageviewsAll, range, customRange), range, customRange),
    [pageviewsAll, range, customRange, observedCountDayList]
  );
  const dailyUniques = useMemo(
    () => maybeFillMissingDailyZeros("uniques", filterByRange(uniquesAll, range, customRange), range, customRange),
    [uniquesAll, range, customRange, observedCountDayList]
  );
  const dailySessions = useMemo(
    () => maybeFillMissingDailyZeros("sessions", filterByRange(sessionsAll, range, customRange), range, customRange),
    [sessionsAll, range, customRange, observedCountDayList]
  );
  const dailyConversions = useMemo(
    () => maybeFillMissingDailyZeros("conversions", filterByRange(conversionsAll, range, customRange), range, customRange),
    [conversionsAll, range, customRange, observedCountDayList]
  );
  const dailyRevenue = useMemo(
    () => maybeFillMissingDailyZeros("revenue", filterByRange(revenueAll, range, customRange), range, customRange),
    [revenueAll, range, customRange, observedCountDayList]
  );
  const dailyDuration = useMemo(() => filterByRange(durationAll, range, customRange), [durationAll, range, customRange]);

  const avgPagesPerVisitAll = useMemo(() => {
    const pageviewsMap = mapByDay(pageviewsAll);
    const sessionsMap = mapByDay(sessionsAll);
    const days = Array.from(new Set([...pageviewsMap.keys(), ...sessionsMap.keys()])).sort((a, b) => a.localeCompare(b));
    return makeDerivedSeries(days, (day) => safeRatio(pageviewsMap.get(day) ?? Number.NaN, sessionsMap.get(day) ?? Number.NaN));
  }, [pageviewsAll, sessionsAll]);

  const dailyAvgPagesPerVisit = useMemo(
    () => filterByRange(avgPagesPerVisitAll, range, customRange),
    [avgPagesPerVisitAll, range, customRange]
  );

  const bounceRateAll = useMemo(() => {
    const pageviewsMap = mapByDay(pageviewsAll);
    const sessionsMap = mapByDay(sessionsAll);
    const days = Array.from(new Set([...sessionsMap.keys(), ...pageviewsMap.keys()])).sort((a, b) =>
      a.localeCompare(b)
    );
    return makeDerivedSeries(days, (day) =>
      deriveBounceRate(sessionsMap.get(day) ?? Number.NaN, pageviewsMap.get(day) ?? Number.NaN)
    );
  }, [pageviewsAll, sessionsAll]);

  const dailyBounceRate = useMemo(() => filterByRange(bounceRateAll, range, customRange), [bounceRateAll, range, customRange]);

  const visitDurationAll = useMemo(() => {
    if (durationAll.length > 0) return durationAll;
    const avgPagesMap = mapByDay(avgPagesPerVisitAll);
    const bounceMap = mapByDay(bounceRateAll);
    const days = Array.from(new Set([...avgPagesMap.keys(), ...bounceMap.keys()])).sort((a, b) => a.localeCompare(b));
    return makeDerivedSeries(days, (day) =>
      deriveVisitDurationSeconds(avgPagesMap.get(day) ?? Number.NaN, bounceMap.get(day) ?? Number.NaN)
    );
  }, [durationAll, avgPagesPerVisitAll, bounceRateAll]);

  const dailyVisitDuration = useMemo(
    () => filterByRange(visitDurationAll, range, customRange),
    [visitDurationAll, range, customRange]
  );

  const getDailySeries = (metric: string) => {
    switch (metric) {
      case "pageviews":
        return dailyPageviews;
      case "uniques":
        return dailyUniques;
      case "sessions":
        return dailySessions;
      case "conversions":
        return dailyConversions;
      case "revenue":
        return dailyRevenue;
      case "avg_pages_per_visit":
        return dailyAvgPagesPerVisit;
      case "visit_duration":
        return dailyVisitDuration;
      case "bounce_rate":
        return dailyBounceRate;
      default:
        return [];
    }
  };

  const getUnfilteredSeries = (metric: string) => {
    switch (metric) {
      case "pageviews":
        return pageviewsAll;
      case "uniques":
        return uniquesAll;
      case "sessions":
        return sessionsAll;
      case "conversions":
        return conversionsAll;
      case "revenue":
        return revenueAll;
      case "avg_pages_per_visit":
        return avgPagesPerVisitAll;
      case "visit_duration":
        return visitDurationAll;
      case "bounce_rate":
        return bounceRateAll;
      default:
        return [];
    }
  };

  const dailySelectedAll = useMemo(
    () => getUnfilteredSeries(selectedMetric),
    [
      selectedMetric,
      pageviewsAll,
      uniquesAll,
      sessionsAll,
      conversionsAll,
      revenueAll,
      avgPagesPerVisitAll,
      visitDurationAll,
      bounceRateAll,
    ]
  );
  const dailySelected = useMemo(
    () => getDailySeries(selectedMetric),
    [
      selectedMetric,
      pageviewsAll,
      uniquesAll,
      sessionsAll,
      conversionsAll,
      revenueAll,
      avgPagesPerVisitAll,
      visitDurationAll,
      bounceRateAll,
      range,
      customRange,
    ]
  );
  const breakdownDateRange = useMemo(() => {
    if (range === "Custom" && customRange.start && customRange.end) {
      return { start: customRange.start, end: customRange.end };
    }
    if (dailyPageviews.length === 0) {
      return null;
    }
    return {
      start: dailyPageviews[0].day,
      end: dailyPageviews[dailyPageviews.length - 1].day,
    };
  }, [range, customRange, dailyPageviews]);

  useEffect(() => {
    if (!canQuery || showSeededBreakdowns) {
      setHostnameOptions([]);
      return;
    }
    const start = breakdownDateRange?.start;
    const end = breakdownDateRange?.end;
    fetchBreakdown("hostnames", token ?? undefined, siteId, start, end, 50)
      .then((response) => {
        setAccessError(null);
        const options = response.rows
          .map((row) => row.label)
          .filter((label) => label && label !== "Unknown");
        setHostnameOptions(options);
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        if (message) setAccessError(message);
        setHostnameOptions([]);
      });
  }, [canQuery, showSeededBreakdowns, token, siteId, breakdownDateRange?.start, breakdownDateRange?.end]);

  useEffect(() => {
    if (selectedHostname === "all") return;
    if (hostnameOptions.includes(selectedHostname)) return;
    setSelectedHostname("all");
  }, [selectedHostname, hostnameOptions]);

  useEffect(() => {
    if (!canQuery) return;
    if (showSeededBreakdowns) {
      setBreakdownData({
        sources: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
        pages: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews"]),
        devices: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
        countries: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
        conversions: createEmptyBreakdownData("conversions", ["uniques", "sessions", "conversions"]),
        hour_of_day: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
        day_of_week: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
        hostnames: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
      });
      return;
    }

    let cancelled = false;
    const start = breakdownDateRange?.start;
    const end = breakdownDateRange?.end;
    Promise.all(
      breakdownDimensions.map((dimension) =>
        fetchBreakdown(
          dimension,
          token ?? undefined,
          siteId,
          start,
          end,
          dimension === "hour_of_day" ? 24 : dimension === "day_of_week" ? 7 : 10,
          hostnameFilter,
          dimension === "hour_of_day" || dimension === "day_of_week" ? timePartingDayType : undefined
        ).then((response) => ({
          dimension,
          response,
        }))
      )
    )
      .then((results) => {
        if (cancelled) return;
        setAccessError(null);
        const next: Record<BreakdownDimension, BreakdownData> = {
          sources: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
          pages: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews"]),
          devices: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
          countries: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
          conversions: createEmptyBreakdownData("conversions", ["uniques", "sessions", "conversions"]),
          hour_of_day: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
          day_of_week: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
          hostnames: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
        };
        results.forEach((result) => {
          next[result.dimension] = {
            rows: result.response.rows.map((row: BreakdownRow) => ({
              label: row.label,
              metrics: row.metrics ?? {},
            })),
            total: result.response.total ?? 0,
            primaryMetric: result.response.primary_metric,
            metricKeys: result.response.metric_keys ?? [result.response.primary_metric],
          };
        });
        setBreakdownData(next);
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        if (message) setAccessError(message);
        console.error(error);
      });

    return () => {
      cancelled = true;
    };
  }, [
    canQuery,
    showSeededBreakdowns,
    token,
    siteId,
    breakdownDateRange?.start,
    breakdownDateRange?.end,
    hostnameFilter,
    timePartingDayType,
  ]);

  const computeKpiValues = (series: {
    pageviews: { day: string; value: number }[];
    uniques: { day: string; value: number }[];
    sessions: { day: string; value: number }[];
    conversions: { day: string; value: number }[];
    revenue: { day: string; value: number }[];
    visitDuration: { day: string; value: number }[];
  }) => {
    const pageviews = series.pageviews.reduce((sum, row) => sum + row.value, 0);
    const uniques = series.uniques.reduce((sum, row) => sum + row.value, 0);
    const sessions = series.sessions.reduce((sum, row) => sum + row.value, 0);
    const conversions = series.conversions.reduce((sum, row) => sum + row.value, 0);
    const revenue = series.revenue.reduce((sum, row) => sum + row.value, 0);
    const avgPagesPerVisit = safeRatio(pageviews, sessions);
    const bounceRate = deriveBounceRate(sessions, pageviews);
    const durationAverage =
      series.visitDuration.length > 0
        ? series.visitDuration.reduce((sum, row) => sum + row.value, 0) / series.visitDuration.length
        : Number.NaN;
    const visitDuration = Number.isFinite(durationAverage)
      ? durationAverage
      : deriveVisitDurationSeconds(avgPagesPerVisit, bounceRate);
    return {
      pageviews,
      uniques,
      sessions,
      conversions,
      revenue,
      avg_pages_per_visit: avgPagesPerVisit,
      visit_duration: visitDuration,
      bounce_rate: bounceRate,
    };
  };

  const totals = computeKpiValues({
    pageviews: dailyPageviews,
    uniques: dailyUniques,
    sessions: dailySessions,
    conversions: dailyConversions,
    revenue: dailyRevenue,
    visitDuration: dailyVisitDuration,
  });
  const activeFilterScale = useMemo(
    () => activeFilters.reduce((acc, filter) => acc * filter.share, 1),
    [activeFilters]
  );
  const scaledTotals = useMemo(() => {
    if (activeFilterScale >= 0.999) return totals;
    return {
      ...totals,
      pageviews: totals.pageviews * activeFilterScale,
      uniques: totals.uniques * activeFilterScale,
      sessions: totals.sessions * activeFilterScale,
      conversions: totals.conversions * activeFilterScale,
      revenue: totals.revenue * activeFilterScale,
    };
  }, [totals, activeFilterScale]);
  const availableBounds = useMemo(() => {
    if (dailySelectedAll.length === 0) return null;
    return {
      min: dailySelectedAll[0].day,
      max: dailySelectedAll[dailySelectedAll.length - 1].day,
    };
  }, [dailySelectedAll]);

  useEffect(() => {
    if (!availableBounds) return;
    const maxDate = parseDay(availableBounds.max);
    const minDate = parseDay(availableBounds.min);
    const defaultEnd = formatIsoDate(maxDate);
    const defaultStartDate = new Date(maxDate);
    defaultStartDate.setDate(defaultStartDate.getDate() - 29);
    const clampedStart = defaultStartDate < minDate ? minDate : defaultStartDate;
    const defaultStart = formatIsoDate(clampedStart);
    setCustomRange((prev) => {
      if (!prev.start || !prev.end) {
        return { start: defaultStart, end: defaultEnd };
      }
      const nextStart = prev.start < availableBounds.min ? availableBounds.min : prev.start;
      const nextEnd = prev.end > availableBounds.max ? availableBounds.max : prev.end;
      return { start: nextStart, end: nextEnd };
    });
  }, [availableBounds]);

  useEffect(() => {
    const setAutoForecast = (next: (typeof forecastOptions)[number]["key"]) => setForecastKey(next);
    if (range === "Today" || range === "Yesterday" || range === "Last 7") {
      setAutoForecast("7d");
      return;
    }
    if (range === "Last 30" || range === "MTD") {
      setAutoForecast("30d");
      return;
    }
    if (range === "Last 90" || range === "YTD") {
      setAutoForecast("90d");
      return;
    }
    if (range === "Custom" && customRange.start && customRange.end) {
      const start = parseDay(customRange.start);
      const end = parseDay(customRange.end);
      const diff = Math.max(1, Math.round(Math.abs(end.getTime() - start.getTime()) / MS_PER_DAY) + 1);
      if (diff <= 7) setAutoForecast("7d");
      else if (diff <= 30) setAutoForecast("30d");
      else if (diff <= 60) setAutoForecast("60d");
      else setAutoForecast("90d");
    }
  }, [range, customRange.start, customRange.end]);

  useEffect(() => {
    if (!availableBounds || compareMode !== "custom" || !compareRange.start || !compareRange.end) return;
    setCompareRange((prev) => {
      const nextStart = prev.start < availableBounds.min ? availableBounds.min : prev.start;
      const nextEnd = prev.end > availableBounds.max ? availableBounds.max : prev.end;
      return { start: nextStart, end: nextEnd };
    });
  }, [availableBounds, compareMode, compareRange.start, compareRange.end]);

  const selectedRangeBounds = useMemo(
    () => resolveRangeBounds(range, customRange, siteTimezone),
    [range, customRange.start, customRange.end, siteTimezone]
  );
  const todayKey = useMemo(() => isoDayForDateInTimeZone(new Date(), siteTimezone), [siteTimezone]);
  const lastActualDay = dailySelected.length > 0 ? dailySelected[dailySelected.length - 1].day : null;
  const hasTodayActual = dailySelected.some((entry) => entry.day === todayKey);
  const lastCompleteActualDay =
    hasTodayActual
      ? [...dailySelected].reverse().find((entry) => entry.day < todayKey)?.day ?? null
      : lastActualDay;
  const primaryRangeBounds = useMemo(() => {
    if (selectedRangeBounds) return selectedRangeBounds;
    if (dailySelected.length === 0) return null;
    return { start: dailySelected[0].day, end: dailySelected[dailySelected.length - 1].day };
  }, [selectedRangeBounds, dailySelected]);

  useEffect(() => {
    if (!canQuery || showSeededBreakdowns || !primaryRangeBounds) {
      setDashboardNotes([]);
      return;
    }
    let cancelled = false;
    fetchDashboardNotes(token ?? undefined, siteId, primaryRangeBounds.start, primaryRangeBounds.end)
      .then((notes) => {
        if (!cancelled) setDashboardNotes(notes);
      })
      .catch((error) => {
        if (!cancelled) {
          setDashboardNotes([]);
          console.error(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, showSeededBreakdowns, token, siteId, primaryRangeBounds?.start, primaryRangeBounds?.end]);

  const selectedForecast =
    (forecastOptions.find((option) => option.key === forecastKey) as ForecastOption) ??
    (forecastOptions.find((option) => option.key === "30d") as ForecastOption);
  const forecastWindow = useMemo(
    () => resolveForecastWindow(forecast, lastCompleteActualDay, selectedForecast),
    [forecast, lastCompleteActualDay, selectedForecast]
  );

  const forecastLabel = forecastWindow.label;
  const forecastHorizon = useMemo(() => {
    const entries = forecastWindow.entries;
    if (entries.some((entry) => entry.day === todayKey)) return entries;
    const firstFutureEntry = entries.find((entry) => entry.day > todayKey) ?? forecast.find((entry) => entry.day > todayKey);
    if (!firstFutureEntry) return entries;
    const todayEntry: ForecastEntry = { ...firstFutureEntry, day: todayKey };
    const nextEntries = [todayEntry, ...entries.filter((entry) => entry.day > todayKey)];
    if (selectedForecast.kind === "days") return nextEntries.slice(0, selectedForecast.days);
    return nextEntries;
  }, [forecastWindow.entries, todayKey, forecast, selectedForecast]);

  useEffect(() => {
    const preferredDate = primaryRangeBounds
      ? todayKey < primaryRangeBounds.start
        ? primaryRangeBounds.start
        : todayKey > primaryRangeBounds.end
          ? primaryRangeBounds.end
          : todayKey
      : todayKey;
    if (!noteDate || noteDate < (primaryRangeBounds?.start ?? "") || noteDate > (primaryRangeBounds?.end ?? "9999-12-31")) {
      setNoteDate(preferredDate);
    }
  }, [noteDate, primaryRangeBounds?.start, primaryRangeBounds?.end, todayKey, siteId]);

  const previousBounds = useMemo(() => {
    if (!availableBounds || !primaryRangeBounds) return null;
    const start = parseDay(primaryRangeBounds.start);
    const end = parseDay(primaryRangeBounds.end);
    const diffDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / MS_PER_DAY) + 1);
    const compareEnd = new Date(start);
    compareEnd.setDate(compareEnd.getDate() - 1);
    const compareStart = new Date(compareEnd);
    compareStart.setDate(compareStart.getDate() - (diffDays - 1));
    const minDate = parseDay(availableBounds.min);
    const maxDate = parseDay(availableBounds.max);
    const clampDate = (date: Date) => new Date(Math.min(Math.max(date.getTime(), minDate.getTime()), maxDate.getTime()));
    const clampedStart = clampDate(compareStart);
    const clampedEnd = clampDate(compareEnd);
    return { start: formatIsoDate(clampedStart), end: formatIsoDate(clampedEnd) };
  }, [availableBounds, primaryRangeBounds]);

  const comparisonBounds = useMemo(() => {
    if (!compareEnabled || !availableBounds) return null;
    if (compareMode === "previous") return previousBounds;
    if (!compareRange.start || !compareRange.end) return null;
    const startCandidate = compareRange.start < availableBounds.min ? availableBounds.min : compareRange.start;
    const endCandidate = compareRange.end > availableBounds.max ? availableBounds.max : compareRange.end;
    const start = startCandidate <= endCandidate ? startCandidate : endCandidate;
    const end = startCandidate <= endCandidate ? endCandidate : startCandidate;
    return { start, end };
  }, [compareEnabled, compareMode, compareRange, availableBounds, previousBounds]);

  useEffect(() => {
    if (!compareEnabled || compareMode !== "custom" || !primaryRangeBounds || compareRange.start) return;
    const start = parseDay(primaryRangeBounds.start);
    const end = parseDay(primaryRangeBounds.end);
    const diffDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / MS_PER_DAY) + 1);
    const compareEnd = new Date(start);
    compareEnd.setDate(compareEnd.getDate() - 1);
    const compareStart = new Date(compareEnd);
    compareStart.setDate(compareStart.getDate() - (diffDays - 1));
    setCompareRange({ start: formatIsoDate(compareStart), end: formatIsoDate(compareEnd) });
  }, [compareEnabled, compareMode, primaryRangeBounds, compareRange.start]);

  const filterByWindow = (entries: { day: string; value: number }[], start: string, end: string) => {
    if (entries.length === 0) return entries;
    const minDate = parseDay(entries[0].day);
    const maxDate = parseDay(entries[entries.length - 1].day);
    const clampDate = (date: Date) =>
      new Date(Math.min(Math.max(date.getTime(), minDate.getTime()), maxDate.getTime()));
    const startDate = clampDate(parseDay(start));
    const endDate = clampDate(parseDay(end));
    const from = startDate <= endDate ? startDate : endDate;
    const to = startDate <= endDate ? endDate : startDate;
    return entries.filter((entry) => {
      const day = parseDay(entry.day);
      return day >= from && day <= to;
    });
  };

  const getSeriesForBounds = (metric: string, bounds: { start: string; end: string } | null) => {
    if (!bounds) return [];
    const entries = getUnfilteredSeries(metric);
    const filtered = filterByWindow(entries, bounds.start, bounds.end);
    const isCountMetric = ["pageviews", "uniques", "sessions", "conversions", "revenue"].includes(metric);
    if (!isCountMetric) return filtered;
    return fillMissingDaysWithZero(
      filtered,
      bounds.start,
      bounds.end,
      observedCountDaySet,
      earliestObservedCountDay,
      latestObservedCountDay
    );
  };

  const getComparisonSeries = (metric: string) => getSeriesForBounds(metric, comparisonBounds);

  const comparisonAligned = useMemo(() => {
    if (!compareEnabled) return new Map<string, ComparisonPoint>();
    const compareEntries = getComparisonSeries(selectedMetric);
    if (compareEntries.length === 0 || dailySelected.length === 0) return new Map<string, ComparisonPoint>();
    const minLength = Math.min(dailySelected.length, compareEntries.length);
    const primarySlice = dailySelected.slice(dailySelected.length - minLength);
    const compareSlice = compareEntries.slice(compareEntries.length - minLength);
    const map = new Map<string, ComparisonPoint>();
    primarySlice.forEach((row, index) => {
      const compareValue = compareSlice[index]?.value;
      if (Number.isFinite(compareValue)) {
        map.set(row.day, {
          day: compareSlice[index]?.day ?? row.day,
          value: compareValue,
        });
      }
    });
    return map;
  }, [compareEnabled, dailySelected, selectedMetric, comparisonBounds, compareMode, compareRange, aggregateMap]);

  const comparisonTotals = compareEnabled
    ? computeKpiValues({
        pageviews: getComparisonSeries("pageviews"),
        uniques: getComparisonSeries("uniques"),
        sessions: getComparisonSeries("sessions"),
        conversions: getComparisonSeries("conversions"),
        revenue: getComparisonSeries("revenue"),
        visitDuration: getComparisonSeries("visit_duration"),
      })
    : null;
  const previousTotals = previousBounds
    ? computeKpiValues({
        pageviews: getSeriesForBounds("pageviews", previousBounds),
        uniques: getSeriesForBounds("uniques", previousBounds),
        sessions: getSeriesForBounds("sessions", previousBounds),
        conversions: getSeriesForBounds("conversions", previousBounds),
        revenue: getSeriesForBounds("revenue", previousBounds),
        visitDuration: getSeriesForBounds("visit_duration", previousBounds),
      })
    : null;
  const kpiComparisonValues = compareEnabled ? comparisonTotals : previousTotals;
  const kpiComparisonLabel = comparisonBounds
    ? compareMode === "previous"
      ? "vs previous period"
      : `vs ${formatShortDate(comparisonBounds.start)}–${formatShortDate(comparisonBounds.end)}`
    : previousBounds
      ? "vs previous period"
      : null;
  const currentRangeLabel = primaryRangeBounds ? formatRangeLabel(primaryRangeBounds.start, primaryRangeBounds.end) : null;
  const comparisonRangeLabel = compareEnabled && comparisonBounds
    ? formatRangeLabel(comparisonBounds.start, comparisonBounds.end)
    : null;
  const rangeDomainDays = useMemo(() => {
    if (primaryRangeBounds) return enumerateDays(primaryRangeBounds.start, primaryRangeBounds.end);
    if (dailySelected.length > 0) return dailySelected.map((entry) => entry.day);
    return [];
  }, [primaryRangeBounds, dailySelected]);
  const actualByDay = useMemo(() => new Map(dailySelected.map((row) => [row.day, row.value])), [dailySelected]);
  const priorActualDayForToday = useMemo(() => {
    for (let index = dailySelected.length - 1; index >= 0; index -= 1) {
      if (dailySelected[index].day < todayKey) return dailySelected[index].day;
    }
    return null;
  }, [dailySelected, todayKey]);
  const forecastCandidates = useMemo(
    () =>
      forecastHorizon.filter((entry) => {
        if (hasTodayActual) return entry.day >= todayKey;
        if (!lastActualDay) return true;
        return entry.day > lastActualDay;
      }),
    [forecastHorizon, hasTodayActual, todayKey, lastActualDay]
  );
  const forecastSummary = useMemo(() => {
    if (forecastCandidates.length === 0) return null;
    const total = forecastCandidates.reduce((sum, entry) => sum + entry.yhat, 0);
    return {
      total,
      average: total / forecastCandidates.length,
    };
  }, [forecastCandidates]);
  const forecastByDay = useMemo(() => {
    const map = new Map<string, ForecastEntry>();
    forecastCandidates.forEach((entry) => {
      map.set(entry.day, entry);
    });
    return map;
  }, [forecastCandidates]);
  const chartDomainDays = useMemo(() => {
    if (forecastCandidates.length === 0) return rangeDomainDays;
    const merged = new Set<string>(rangeDomainDays);
    forecastCandidates.forEach((entry) => merged.add(entry.day));
    return Array.from(merged).sort((a, b) => a.localeCompare(b));
  }, [rangeDomainDays, forecastCandidates]);
  const forecastStartDay = useMemo(() => {
    for (const day of chartDomainDays) {
      if (forecastByDay.has(day)) return day;
    }
    return null;
  }, [chartDomainDays, forecastByDay]);
  const baseChartData = useMemo(
    () =>
      chartDomainDays.map((day) => {
        const forecastEntry = forecastByDay.get(day);
        const comparisonEntry = comparisonAligned.get(day);
        const lower = forecastEntry?.yhat_lower;
        const upper = forecastEntry?.yhat_upper;
        const hasBand = Number.isFinite(lower) && Number.isFinite(upper);
        const bandSpan = hasBand ? Math.max(0, (upper as number) - (lower as number)) : null;
        const rawActualValue = actualByDay.get(day) ?? null;
        const isTodayPoint = day === todayKey;
        const actualValue = isTodayPoint && hasTodayActual ? null : rawActualValue;
        const todaySoFarValue =
          hasTodayActual && (isTodayPoint || day === priorActualDayForToday) ? rawActualValue : null;
        const shouldBridgeToday =
          !hasTodayActual &&
          Boolean(priorActualDayForToday) &&
          Boolean(forecastByDay.get(todayKey));
        const todayBridgeValue =
          shouldBridgeToday && (day === priorActualDayForToday || isTodayPoint)
            ? day === priorActualDayForToday
              ? rawActualValue
              : forecastByDay.get(todayKey)?.yhat ?? null
            : null;
        const compareValue = comparisonEntry?.value ?? null;
        const hasDelta =
          Number.isFinite(actualValue ?? Number.NaN) && Number.isFinite(compareValue ?? Number.NaN);
        const deltaPositiveRange: [number, number] | null = hasDelta
          ? [compareValue as number, Math.max(actualValue as number, compareValue as number)]
          : null;
        const deltaNegativeRange: [number, number] | null = hasDelta
          ? [Math.min(actualValue as number, compareValue as number), compareValue as number]
          : null;
        return {
          day,
          actual: actualValue,
          todaySoFar: todaySoFarValue,
          todayBridge: todayBridgeValue,
          compare: compareValue,
          compareDay: comparisonEntry?.day ?? null,
          forecast: forecastEntry?.yhat ?? null,
          forecastLine: forecastEntry?.yhat ?? null,
          forecastLower: hasBand ? (lower as number) : null,
          forecastUpper: hasBand ? (upper as number) : null,
          forecastBandSpan: hasBand ? bandSpan : null,
          deltaPositiveRange,
          deltaNegativeRange,
        } satisfies TrendChartPoint;
      }),
    [
      chartDomainDays,
      forecastByDay,
      actualByDay,
      comparisonAligned,
      todayKey,
      hasTodayActual,
      priorActualDayForToday,
    ]
  );

  const scaledKpiComparisonValues = useMemo(() => {
    if (!kpiComparisonValues) return null;
    if (activeFilterScale >= 0.999) return kpiComparisonValues;
    return {
      ...kpiComparisonValues,
      pageviews: (kpiComparisonValues.pageviews ?? 0) * activeFilterScale,
      uniques: (kpiComparisonValues.uniques ?? 0) * activeFilterScale,
      sessions: (kpiComparisonValues.sessions ?? 0) * activeFilterScale,
      conversions: (kpiComparisonValues.conversions ?? 0) * activeFilterScale,
      revenue: (kpiComparisonValues.revenue ?? 0) * activeFilterScale,
    };
  }, [kpiComparisonValues, activeFilterScale]);

  const isCountTrendMetric = ["pageviews", "uniques", "sessions", "conversions", "revenue"].includes(selectedMetric);
  const trendScale = isCountTrendMetric ? activeFilterScale : 1;

  // Auto-select chart granularity. Only metrics whose daily values are safely additive
  // roll up to week/month; uniques (can't dedupe across days) and rate metrics
  // (bounce_rate, avg_pages_per_visit, visit_duration — the reducer doesn't expose
  // numerator/denominator) stay daily regardless of range.
  const chartGranularity: ChartGranularity = useMemo(() => {
    const canAggregate = ["pageviews", "sessions", "conversions", "revenue"].includes(selectedMetric);
    if (!canAggregate) return "day";
    const days = rangeDomainDays.length;
    if (days > 365) return "month";
    if (days > 90) return "week";
    return "day";
  }, [selectedMetric, rangeDomainDays.length]);

  const bucketedChartData = useMemo<TrendChartPoint[]>(() => {
    if (chartGranularity === "day") return baseChartData;
    const buckets = new Map<
      string,
      {
        actual: number | null;
        todaySoFar: number | null;
        todayBridge: number | null;
        compare: number | null;
        forecast: number | null;
        forecastLine: number | null;
        forecastLower: number | null;
        forecastUpper: number | null;
      }
    >();
    const addTo = (acc: number | null, value: number | null | undefined): number | null => {
      if (!Number.isFinite(value ?? Number.NaN)) return acc;
      return (acc ?? 0) + (value as number);
    };
    for (const point of baseChartData) {
      const key = bucketKeyFor(point.day, chartGranularity);
      const current = buckets.get(key) ?? {
        actual: null,
        todaySoFar: null,
        todayBridge: null,
        compare: null,
        forecast: null,
        forecastLine: null,
        forecastLower: null,
        forecastUpper: null,
      };
      buckets.set(key, {
        actual: addTo(current.actual, point.actual),
        todaySoFar: addTo(current.todaySoFar, point.todaySoFar),
        todayBridge: null,
        compare: addTo(current.compare, point.compare),
        forecast: addTo(current.forecast, point.forecast),
        forecastLine: addTo(current.forecastLine, point.forecastLine),
        forecastLower: addTo(current.forecastLower, point.forecastLower),
        forecastUpper: addTo(current.forecastUpper, point.forecastUpper),
      });
    }
    return Array.from(buckets.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([key, acc]) => {
        const hasDelta =
          Number.isFinite(acc.actual ?? Number.NaN) && Number.isFinite(acc.compare ?? Number.NaN);
        const deltaPositiveRange: [number, number] | null = hasDelta
          ? [acc.compare as number, Math.max(acc.actual as number, acc.compare as number)]
          : null;
        const deltaNegativeRange: [number, number] | null = hasDelta
          ? [Math.min(acc.actual as number, acc.compare as number), acc.compare as number]
          : null;
        const hasBand =
          Number.isFinite(acc.forecastLower ?? Number.NaN) &&
          Number.isFinite(acc.forecastUpper ?? Number.NaN);
        return {
          day: key,
          actual: acc.actual,
          todaySoFar: acc.todaySoFar,
          todayBridge: null,
          compare: acc.compare,
          compareDay: null,
          forecast: acc.forecast,
          forecastLine: acc.forecastLine,
          forecastLower: hasBand ? (acc.forecastLower as number) : null,
          forecastUpper: hasBand ? (acc.forecastUpper as number) : null,
          forecastBandSpan: hasBand
            ? Math.max(0, (acc.forecastUpper as number) - (acc.forecastLower as number))
            : null,
          deltaPositiveRange,
          deltaNegativeRange,
        } satisfies TrendChartPoint;
      });
  }, [baseChartData, chartGranularity]);

  const chartData = useMemo(
    () =>
      bucketedChartData.map((point) => {
        if (trendScale >= 0.999) return point;
        const scaleRange = (range: [number, number] | null): [number, number] | null =>
          range ? [range[0] * trendScale, range[1] * trendScale] : null;
        return {
          ...point,
          actual: Number.isFinite(point.actual ?? Number.NaN) ? (point.actual ?? 0) * trendScale : point.actual,
          todaySoFar: Number.isFinite(point.todaySoFar ?? Number.NaN)
            ? (point.todaySoFar ?? 0) * trendScale
            : point.todaySoFar,
          todayBridge: Number.isFinite(point.todayBridge ?? Number.NaN)
            ? (point.todayBridge ?? 0) * trendScale
            : point.todayBridge,
          compare: Number.isFinite(point.compare ?? Number.NaN) ? (point.compare ?? 0) * trendScale : point.compare,
          forecast: Number.isFinite(point.forecast ?? Number.NaN) ? (point.forecast ?? 0) * trendScale : point.forecast,
          forecastLine: Number.isFinite(point.forecastLine ?? Number.NaN)
            ? (point.forecastLine ?? 0) * trendScale
            : point.forecastLine,
          forecastLower: Number.isFinite(point.forecastLower ?? Number.NaN)
            ? (point.forecastLower ?? 0) * trendScale
            : point.forecastLower,
          forecastUpper: Number.isFinite(point.forecastUpper ?? Number.NaN)
            ? (point.forecastUpper ?? 0) * trendScale
            : point.forecastUpper,
          forecastBandSpan: Number.isFinite(point.forecastBandSpan ?? Number.NaN)
            ? (point.forecastBandSpan ?? 0) * trendScale
            : point.forecastBandSpan,
          deltaPositiveRange: scaleRange(point.deltaPositiveRange),
          deltaNegativeRange: scaleRange(point.deltaNegativeRange),
        };
      }),
    [bucketedChartData, trendScale]
  );
  const notesByMarkerDay = useMemo(() => {
    const notesByDay = new Map<string, DashboardNote[]>();
    if (dashboardNotes.length === 0 || chartData.length === 0) return notesByDay;
    const chartDays = new Set(chartData.map((point) => point.day));
    dashboardNotes.forEach((note) => {
      const markerDay = bucketKeyFor(note.day, chartGranularity);
      if (!chartDays.has(markerDay)) return;
      const existing = notesByDay.get(markerDay) ?? [];
      existing.push(note);
      notesByDay.set(
        markerDay,
        existing.sort((a, b) => a.day.localeCompare(b.day) || a.id - b.id)
      );
    });
    return notesByDay;
  }, [dashboardNotes, chartData, chartGranularity]);
  const noteMarkerDays = useMemo(
    () => Array.from(notesByMarkerDay.keys()).sort((a, b) => a.localeCompare(b)),
    [notesByMarkerDay]
  );
  const activeNoteMarkerDay = selectedNoteMarkerDay ?? hoveredNoteMarkerDay;
  const activeMarkerNotes = activeNoteMarkerDay ? notesByMarkerDay.get(activeNoteMarkerDay) ?? [] : [];

  useEffect(() => {
    if (selectedNoteMarkerDay && !notesByMarkerDay.has(selectedNoteMarkerDay)) {
      setSelectedNoteMarkerDay(null);
    }
    if (hoveredNoteMarkerDay && !notesByMarkerDay.has(hoveredNoteMarkerDay)) {
      setHoveredNoteMarkerDay(null);
    }
  }, [hoveredNoteMarkerDay, notesByMarkerDay, selectedNoteMarkerDay]);

  const hasActual = chartData.some((point) => point.actual !== null);
  const hasTodaySoFar = chartData.some((point) => point.todaySoFar !== null);
  const hasTodayBridge = chartData.some((point) => point.todayBridge !== null);
  const hasCompare = chartData.some((point) => point.compare !== null);
  const hasForecast = chartData.some((point) => point.forecast !== null);
  const hasForecastBand = chartData.some((point) => point.forecastBandSpan !== null);
  const hasAnyForecastData = forecastCandidates.length > 0;
  const forecastMutedNote = hasAnyForecastData
    ? "Forecast unavailable in selected date range."
    : "Forecast unavailable until more history is collected.";
  const selectedRangeDayCount = rangeDomainDays.length;

  const seededBreakdownTotals = useMemo(
    () => ({
      uniques: scaledTotals.uniques,
      sessions: scaledTotals.sessions,
      pageviews: scaledTotals.pageviews,
      conversions: scaledTotals.conversions,
    }),
    [scaledTotals.uniques, scaledTotals.sessions, scaledTotals.pageviews, scaledTotals.conversions]
  );
  const sourceRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(
            ["Direct", "Google", "Reddit", "DuckDuckGo", "openai.com", "LinkedIn"],
            [0.31, 0.26, 0.14, 0.12, 0.1, 0.07],
            seededBreakdownTotals
          )
        : breakdownData.sources.rows.map((row) => ({ ...row, label: normalizeSourceLabel(row.label) })),
    [showSeededBreakdowns, seededBreakdownTotals, breakdownData.sources.rows]
  );
  const channelRows = useMemo(
    () =>
      aggregateRowsByLabel(
        sourceRows.map((row) => ({
          label: classifyChannelLabel(row.label),
          metrics: row.metrics,
        }))
      ),
    [sourceRows]
  );
  const sourceMediumRows = useMemo(
    () =>
      aggregateRowsByLabel(
        sourceRows.map((row) => ({
          label: buildSourceMediumLabel(row.label),
          metrics: row.metrics,
        }))
      ),
    [sourceRows]
  );
  const campaignRows = useMemo(() => {
    if (!showSeededBreakdowns) return [] as BreakdownTableRow[];
    if (campaignDimension === "content") {
      return buildMetricRows(
        ["hero-video", "cta-footer", "docs-banner", "homepage-hero"],
        [0.34, 0.24, 0.22, 0.2],
        seededBreakdownTotals
      );
    }
    if (campaignDimension === "term") {
      return buildMetricRows(
        ["privacy analytics", "cookie-free analytics", "plausible alternative", "gdpr analytics"],
        [0.31, 0.27, 0.24, 0.18],
        seededBreakdownTotals
      );
    }
    return buildMetricRows(
      ["spring_launch", "brand_search", "product_update", "partner_referral"],
      [0.36, 0.26, 0.2, 0.18],
      seededBreakdownTotals
    );
  }, [showSeededBreakdowns, campaignDimension, seededBreakdownTotals]);
  const acquisitionRows = useMemo(() => {
    if (acquisitionTab === "sources") return sourceRows;
    if (acquisitionTab === "source_medium") return sourceMediumRows;
    if (acquisitionTab === "campaigns") return campaignRows;
    return channelRows;
  }, [acquisitionTab, sourceRows, sourceMediumRows, campaignRows, channelRows]);
  const acquisitionMetricKeys = showSeededBreakdowns
    ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
    : acquisitionTab === "campaigns"
      ? (["sessions"] as BreakdownMetricKey[])
      : breakdownData.sources.metricKeys;
  const acquisitionPrimaryMetric = showSeededBreakdowns
    ? ("sessions" as BreakdownMetricKey)
    : acquisitionTab === "campaigns"
      ? ("sessions" as BreakdownMetricKey)
      : breakdownData.sources.primaryMetric;
  const acquisitionTotal = showSeededBreakdowns ? scaledTotals.sessions : breakdownData.sources.total;
  const acquisitionEmptyState =
    acquisitionTab === "campaigns"
      ? "Campaign and UTM metadata will appear after campaign parameters are collected."
      : "No acquisition data yet for the selected range.";
  const acquisitionDimensionKey = useMemo(() => {
    if (acquisitionTab === "sources") return "source";
    if (acquisitionTab === "source_medium") return "source_medium";
    if (acquisitionTab === "campaigns") return campaignDimension;
    return "channel";
  }, [acquisitionTab, campaignDimension]);
  const topChannel = useMemo(() => {
    const ranked = channelRows
      .map((row) => ({
        label: row.label,
        value: getBreakdownMetricValue(row, acquisitionPrimaryMetric),
      }))
      .filter((row) => Number.isFinite(row.value) && row.value > 0)
      .sort((a, b) => b.value - a.value);
    if (ranked.length === 0) return null;
    const top = ranked[0];
    const share = acquisitionTotal > 0 ? top.value / acquisitionTotal : 0;
    return { ...top, share };
  }, [channelRows, acquisitionPrimaryMetric, acquisitionTotal]);

  const toggleFilter = (dimension: string, row: BreakdownTableRow, total: number, primaryMetric: BreakdownMetricKey) => {
    const rowValue = getBreakdownMetricValue(row, primaryMetric);
    if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(rowValue) || rowValue <= 0) return;
    const share = clamp(rowValue / total, 0.01, 1);
    setActiveFilters((prev) => {
      const match = prev.find((f) => f.dimension === dimension && f.value === row.label);
      if (match) {
        return prev.filter((f) => !(f.dimension === dimension && f.value === row.label));
      }
      const withoutSameDimension = prev.filter((f) => f.dimension !== dimension);
      return [...withoutSameDimension, { dimension, value: row.label, share }];
    });
  };

  const removeFilter = (dimension: string, value: string) => {
    setActiveFilters((prev) => prev.filter((f) => !(f.dimension === dimension && f.value === value)));
  };

  const pageRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(["/", "/pricing", "/blog/privacy", "/docs/setup", "/about"], [0.3, 0.22, 0.18, 0.16, 0.14], {
            uniques: scaledTotals.uniques,
            sessions: scaledTotals.sessions,
            pageviews: scaledTotals.pageviews,
          })
        : breakdownData.pages.rows,
    [showSeededBreakdowns, scaledTotals.uniques, scaledTotals.sessions, scaledTotals.pageviews, breakdownData.pages.rows]
  );
  const deviceRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(["Mobile", "Desktop", "Tablet"], [0.58, 0.34, 0.08], seededBreakdownTotals)
        : breakdownData.devices.rows,
    [showSeededBreakdowns, seededBreakdownTotals, breakdownData.devices.rows]
  );
  const countryRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(
            ["United States", "United Kingdom", "Canada", "Germany", "France", "Netherlands", "Australia", "Sweden", "India", "Japan"],
            [0.28, 0.12, 0.09, 0.08, 0.07, 0.06, 0.06, 0.05, 0.1, 0.09],
            seededBreakdownTotals
          )
        : breakdownData.countries.rows,
    [showSeededBreakdowns, seededBreakdownTotals, breakdownData.countries.rows]
  );
  const goalRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(
            ["Demo Request", "Contact Us", "Trial Signup", "Purchase", "Newsletter"],
            [0.34, 0.22, 0.18, 0.16, 0.1],
            { uniques: scaledTotals.uniques, sessions: scaledTotals.sessions, conversions: scaledTotals.conversions }
          )
        : breakdownData.conversions.rows,
    [showSeededBreakdowns, scaledTotals.uniques, scaledTotals.sessions, scaledTotals.conversions, breakdownData.conversions.rows]
  );
  const seededHourRows = useMemo(
    () =>
      buildMetricRows(
        [...hourOfDayLabels],
        [0.04, 0.02, 0.01, 0.01, 0.01, 0.02, 0.03, 0.06, 0.08, 0.09, 0.08, 0.07, 0.06, 0.05, 0.05, 0.05, 0.06, 0.07, 0.06, 0.05, 0.04, 0.04, 0.03, 0.02],
        seededBreakdownTotals
      ),
    [seededBreakdownTotals]
  );
  const seededDayRows = useMemo(
    () =>
      buildMetricRows(
        [...dayOfWeekLabels],
        [0.12, 0.13, 0.13, 0.14, 0.17, 0.16, 0.15],
        seededBreakdownTotals
      ),
    [seededBreakdownTotals]
  );
  const timePartingEligible = showSeededBreakdowns || selectedRangeDayCount >= 7;
  const timePartingPrimaryMetric = showSeededBreakdowns
    ? ("sessions" as BreakdownMetricKey)
    : breakdownData.hour_of_day.primaryMetric;
  const timePartingEmptyState = timePartingEligible
    ? "No time-parting data yet for the selected range."
    : "Time-parting analysis becomes useful once you view at least 7 days.";
  const breakdownCards = useMemo(() => {
    return [
      {
        title: "Top Pages",
        rows: pageRows,
        empty: "No page data yet for the selected range.",
        dimension: "page",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.pages.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews"] as BreakdownMetricKey[])
          : breakdownData.pages.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.pages.total,
      },
      {
        title: "Countries",
        rows: countryRows,
        empty: "No country data yet for the selected range.",
        dimension: "country",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.countries.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
          : breakdownData.countries.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.countries.total,
      },
      {
        title: "Devices",
        rows: deviceRows,
        empty: "No device data yet for the selected range.",
        dimension: "device",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.devices.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
          : breakdownData.devices.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.devices.total,
      },
      {
        title: "Goals",
        rows: goalRows,
        empty: "No goal events yet for the selected range.",
        dimension: "goal",
        primaryMetric: showSeededBreakdowns ? ("conversions" as BreakdownMetricKey) : breakdownData.conversions.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "conversions"] as BreakdownMetricKey[])
          : breakdownData.conversions.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.conversions : breakdownData.conversions.total,
      },
    ];
  }, [
    pageRows,
    countryRows,
    deviceRows,
    goalRows,
    showSeededBreakdowns,
    scaledTotals.pageviews,
    scaledTotals.conversions,
    breakdownData.pages.primaryMetric,
    breakdownData.pages.metricKeys,
    breakdownData.pages.total,
    breakdownData.countries.primaryMetric,
    breakdownData.countries.metricKeys,
    breakdownData.countries.total,
    breakdownData.devices.primaryMetric,
    breakdownData.devices.metricKeys,
    breakdownData.devices.total,
    breakdownData.conversions.primaryMetric,
    breakdownData.conversions.metricKeys,
    breakdownData.conversions.total,
  ]);

  // URL persistence: mirror dashboard state back into the query params (initial state is hydrated
  // from the URL via lazy `useState` initializers above, so this just keeps the URL in sync).
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    const managedKeys = [
      "metric",
      "range",
      "hostname",
      "start",
      "end",
      "cmp",
      "cmpMode",
      "cmpStart",
      "cmpEnd",
      "forecast",
      "tab",
      "camp",
      "tp",
      "tpDays",
      "filter",
    ];
    managedKeys.forEach((k) => next.delete(k));
    if (selectedMetric !== "pageviews") next.set("metric", selectedMetric);
    if (range !== "Last 30") next.set("range", range);
    if (selectedHostname !== "all") next.set("hostname", selectedHostname);
    if (range === "Custom") {
      if (customRange.start) next.set("start", customRange.start);
      if (customRange.end) next.set("end", customRange.end);
    }
    if (compareEnabled) next.set("cmp", "1");
    if (compareEnabled && compareMode !== "previous") next.set("cmpMode", compareMode);
    if (compareEnabled && compareMode === "custom") {
      if (compareRange.start) next.set("cmpStart", compareRange.start);
      if (compareRange.end) next.set("cmpEnd", compareRange.end);
    }
    if (forecastKey !== "30d") next.set("forecast", forecastKey);
    if (acquisitionTab !== "channels") next.set("tab", acquisitionTab);
    if (campaignDimension !== "campaign") next.set("camp", campaignDimension);
    if (timePartingDayType !== "all") next.set("tpDays", timePartingDayType);
    if (activeFilters.length > 0) {
      next.set(
        "filter",
        activeFilters
          .map((f) => `${f.dimension}:${encodeURIComponent(f.value)}`)
          .join(",")
      );
    }
    const currentQs = searchParams.toString();
    const nextQs = next.toString();
    if (currentQs !== nextQs) {
      setSearchParams(next, { replace: true });
    }
  }, [
    selectedMetric,
    range,
    selectedHostname,
    customRange.start,
    customRange.end,
    compareEnabled,
    compareMode,
    compareRange.start,
    compareRange.end,
    forecastKey,
    acquisitionTab,
    campaignDimension,
    timePartingDayType,
    activeFilters,
    searchParams,
    setSearchParams,
  ]);

  // Reconcile active filter shares against current breakdown data so URL-hydrated filters
  // and range changes produce accurate KPI/trend scaling.
  useEffect(() => {
    if (activeFilters.length === 0) return;
    const dimensionSources: Record<
      string,
      { rows: BreakdownTableRow[]; total: number; primaryMetric: BreakdownMetricKey } | undefined
    > = {
      channel: {
        rows: channelRows,
        total: acquisitionTotal,
        primaryMetric: acquisitionPrimaryMetric,
      },
      source: { rows: sourceRows, total: acquisitionTotal, primaryMetric: acquisitionPrimaryMetric },
      source_medium: {
        rows: sourceMediumRows,
        total: acquisitionTotal,
        primaryMetric: acquisitionPrimaryMetric,
      },
      campaign: { rows: campaignRows, total: acquisitionTotal, primaryMetric: acquisitionPrimaryMetric },
      content: { rows: campaignRows, total: acquisitionTotal, primaryMetric: acquisitionPrimaryMetric },
      term: { rows: campaignRows, total: acquisitionTotal, primaryMetric: acquisitionPrimaryMetric },
      page: {
        rows: pageRows,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.pages.total,
        primaryMetric: showSeededBreakdowns ? "pageviews" : breakdownData.pages.primaryMetric,
      },
      country: {
        rows: countryRows,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.countries.total,
        primaryMetric: showSeededBreakdowns ? "pageviews" : breakdownData.countries.primaryMetric,
      },
      device: {
        rows: deviceRows,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.devices.total,
        primaryMetric: showSeededBreakdowns ? "pageviews" : breakdownData.devices.primaryMetric,
      },
      goal: {
        rows: goalRows,
        total: showSeededBreakdowns ? scaledTotals.conversions : breakdownData.conversions.total,
        primaryMetric: showSeededBreakdowns ? "conversions" : breakdownData.conversions.primaryMetric,
      },
      day_of_week: {
        rows: showSeededBreakdowns ? seededDayRows : breakdownData.day_of_week.rows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.day_of_week.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.day_of_week.primaryMetric,
      },
      hour_of_day: {
        rows: showSeededBreakdowns ? seededHourRows : breakdownData.hour_of_day.rows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.hour_of_day.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.hour_of_day.primaryMetric,
      },
    };
    setActiveFilters((prev) => {
      let changed = false;
      const next = prev.map((filter) => {
        const source = dimensionSources[filter.dimension];
        if (!source) return filter;
        const { rows, total, primaryMetric } = source;
        if (!rows || rows.length === 0 || !Number.isFinite(total) || total <= 0) return filter;
        const row = rows.find((r) => r.label === filter.value);
        if (!row) return filter;
        const rowValue = getBreakdownMetricValue(row, primaryMetric);
        if (!Number.isFinite(rowValue) || rowValue <= 0) return filter;
        const share = clamp(rowValue / total, 0.01, 1);
        // Tolerance must exceed the rounding noise from seeded buildMetricRows
        // (which rounds each row independently, leaving the sum ~1 off the total).
        // 0.01 (1 percentage point) is well above that noise and still tight enough
        // to catch real share shifts from date-range changes.
        if (Math.abs(share - filter.share) < 0.01) return filter;
        changed = true;
        return { ...filter, share };
      });
      return changed ? next : prev;
    });
  }, [
    activeFilters.length,
    channelRows,
    sourceRows,
    sourceMediumRows,
    campaignRows,
    pageRows,
    countryRows,
    deviceRows,
    goalRows,
    seededDayRows,
    seededHourRows,
    acquisitionTotal,
    acquisitionPrimaryMetric,
    breakdownData,
    showSeededBreakdowns,
    scaledTotals.pageviews,
    scaledTotals.conversions,
    scaledTotals.sessions,
  ]);

  const mapeValue = forecastMeta?.mape ?? Number.NaN;
  const canPublishForecastAccuracy =
    Number.isFinite(mapeValue) && mapeValue >= 0 && mapeValue <= MAX_PUBLISHED_FORECAST_ACCURACY_MAPE;
  const forecastAccuracy = canPublishForecastAccuracy
    ? `${clamp((1 - mapeValue) * 100, 0, 100).toFixed(0)}%`
    : "Building";
  const forecastAccuracyClass = canPublishForecastAccuracy
    ? mapeValue <= 0.1
      ? "text-emerald-600"
      : "text-amber-600"
    : "text-gray-400";
  const showForecastBuildingInfo =
    forecastAccuracy === "Building" && (selectedMetric === "conversions" || selectedMetric === "revenue");
  const selectedMetricLabel = metricLabels[selectedMetric] ?? selectedMetric;
  const selectedMetricLower = selectedMetricLabel.toLowerCase();
  const selectedMetricCurrentValue = (scaledTotals as Record<string, number>)[selectedMetric] ?? Number.NaN;
  const selectedMetricComparisonValue = scaledKpiComparisonValues
    ? ((scaledKpiComparisonValues as Record<string, number>)[selectedMetric] ?? Number.NaN)
    : Number.NaN;
  const selectedMetricDeltaPct =
    Number.isFinite(selectedMetricCurrentValue) &&
    Number.isFinite(selectedMetricComparisonValue) &&
    Math.abs(selectedMetricComparisonValue) > 0
      ? (selectedMetricCurrentValue - selectedMetricComparisonValue) / selectedMetricComparisonValue
      : Number.NaN;
  const selectedMetricGoal = metricSupportsGoals(selectedMetric) ? siteGoals[selectedMetric] ?? null : null;
  const forecastDayCount = forecastCandidates.length;
  const goalTargetForWindow =
    selectedMetricGoal && forecastDayCount > 0
      ? selectedMetricGoal.target * (forecastDayCount / Math.max(1, selectedMetricGoal.periodDays))
      : null;
  const goalGap =
    forecastSummary && Number.isFinite(goalTargetForWindow ?? Number.NaN)
      ? forecastSummary.total - (goalTargetForWindow ?? 0)
      : null;
  const goalGapPct =
    Number.isFinite(goalGap ?? Number.NaN) && Number.isFinite(goalTargetForWindow ?? Number.NaN) && (goalTargetForWindow ?? 0) > 0
      ? ((goalGap ?? 0) / (goalTargetForWindow ?? 1)) * 100
      : Number.NaN;
  const goalSentence =
    Number.isFinite(goalGapPct)
      ? `At the current pace, ${selectedMetricLower} is forecasted to finish ${Math.abs(goalGapPct).toFixed(0)}% ${
          (goalGap ?? 0) >= 0 ? "above" : "below"
        } goal.`
      : null;
  const topChannelLabel = topChannel?.label ?? null;
  const topChannelSharePct = topChannel ? Math.round(topChannel.share * 100) : null;
  const selectedRangeEndDay = rangeDomainDays.length > 0 ? rangeDomainDays[rangeDomainDays.length - 1] : null;
  const trendFooterNote = useMemo(() => {
    const notes: string[] = [];
    if (!lastActualDay) {
      notes.push("No actual data yet.");
    } else if (selectedRangeEndDay && lastActualDay < selectedRangeEndDay) {
      notes.push(`Actual data through ${formatShortDate(lastActualDay)}.`);
    }
    if (!hasForecast) {
      notes.push(forecastMutedNote);
    }
    return notes.join(" ");
  }, [lastActualDay, selectedRangeEndDay, hasForecast, forecastMutedNote]);
  const chartFormatter = (value: number) => {
    if (selectedMetric === "revenue") return formatCompactCurrency(value);
    if (selectedMetric === "bounce_rate") return formatPercent(value);
    if (selectedMetric === "visit_duration") return formatDuration(value);
    if (selectedMetric === "avg_pages_per_visit") return value.toFixed(2);
    return formatNumber(value);
  };
  const showTodayLine =
    chartGranularity === "day" &&
    chartDomainDays.length > 0 &&
    todayKey >= chartDomainDays[0] &&
    todayKey <= chartDomainDays[chartDomainDays.length - 1];
  const todayActualValue = actualByDay.get(todayKey) ?? Number.NaN;
  const todayForecastEntry = forecastHorizon.find((entry) => entry.day === todayKey);
  const todayProjectionValue = Number.isFinite(todayForecastEntry?.yhat ?? Number.NaN)
    ? (todayForecastEntry?.yhat as number)
    : todayActualValue;
  const todayProgressPct =
    Number.isFinite(todayActualValue) && Number.isFinite(todayProjectionValue) && todayProjectionValue > 0
      ? clamp((todayActualValue / todayProjectionValue) * 100, 0, 999)
      : Number.NaN;
  const todayProgressNote = Number.isFinite(todayActualValue)
    ? `${formatMetricValue(selectedMetric, todayActualValue)} so far${
        Number.isFinite(todayProgressPct) ? ` · ${todayProgressPct.toFixed(0)}% complete` : ""
      }`
    : "No same-day actuals yet";
  const chartSubtitle = [
    currentRangeLabel ?? range,
    lastCompleteActualDay ? `actual through ${formatShortDate(lastCompleteActualDay)}` : "awaiting actual data",
    hasForecast ? `forecast through ${forecastLabel.toLowerCase()}` : forecastMutedNote,
  ].join(" · ");
  const periodDeltaDisplay = Number.isFinite(selectedMetricDeltaPct)
    ? `${selectedMetricDeltaPct >= 0 ? "↑" : "↓"} ${Math.abs(selectedMetricDeltaPct * 100).toFixed(0)}%`
    : "N/A";
  const periodDeltaNote = kpiComparisonLabel ?? "vs previous period";
  const forecastTileHeading =
    forecastDayCount > 0
      ? `Next ${forecastDayCount} days · total`
      : selectedForecast.kind === "days"
        ? `Next ${selectedForecast.days} days · total`
        : `${forecastLabel} · total`;
  const dashboardGoals = Object.values(siteGoals).filter((goal): goal is MetricGoal => Boolean(goal));
  const insightItems = useMemo(() => {
    const items: { label: string; text: string }[] = [];
    if (forecastMeta?.has_anomaly) {
      items.push({
        label: "Anomaly",
        text: `${selectedMetricLabel} was unusually different from the site's recent pattern. Forecasts may be wider while the trend stabilizes.`,
      });
    }
    if (topChannelLabel && Number.isFinite(topChannelSharePct ?? Number.NaN)) {
      items.push({
        label: "Contributor",
        text: `${topChannelLabel} drives ${topChannelSharePct}% of sessions in this period.`,
      });
    }
    if (Number.isFinite(selectedMetricDeltaPct)) {
      items.push({
        label: "Trend",
        text: `${selectedMetricLabel} is ${selectedMetricDeltaPct >= 0 ? "up" : "down"} ${Math.abs(
          selectedMetricDeltaPct * 100
        ).toFixed(1)}% ${periodDeltaNote}.`,
      });
    }
    if (forecastSummary) {
      items.push({
        label: "Pacing",
        text: `The next ${forecastDayCount} days are projected at ${formatMetricValue(
          selectedMetric,
          forecastSummary.total
        )}, averaging ${formatDailyPace(selectedMetric, forecastSummary.average)}.`,
      });
    }
    if (goalSentence) {
      items.push({ label: "Goal", text: goalSentence });
    } else if (dashboardGoals.length > 0) {
      items.push({ label: "Goal", text: "Goals are being tracked against the selected period below." });
    }
    if (items.length === 0) {
      items.push({ label: "Status", text: "No major changes detected for this period." });
    }
    return items.slice(0, 5);
  }, [
    forecastMeta?.has_anomaly,
    selectedMetricLabel,
    topChannelLabel,
    topChannelSharePct,
    selectedMetricDeltaPct,
    periodDeltaNote,
    forecastSummary,
    forecastDayCount,
    selectedMetric,
    goalSentence,
    dashboardGoals.length,
  ]);
  const dashboardControlClass =
    "h-8 rounded-md border border-[#DDE4EC] bg-white px-3 text-xs font-medium text-[#424A57] shadow-sm outline-none transition-colors hover:border-[#C7D0DC] focus:border-[#5b55ff]";
  const dashboardActionClass =
    "inline-flex h-8 items-center rounded-md border border-[#DDE4EC] bg-white px-3 text-[11px] font-semibold text-[#5F6673] shadow-sm transition-colors hover:border-[#C7D0DC] hover:text-[#1F2937]";
  const formatNoteMetric = (metric?: string | null) => {
    if (!metric) return "Period";
    return metricLabels[metric] ?? metric;
  };
  const handleCreateNote = async () => {
    const body = noteBody.trim();
    if (!body || !noteDate || !canQuery || showSeededBreakdowns) return;
    setIsSavingNote(true);
    setNoteStatus(null);
    try {
      const created = await createDashboardNote(
        {
          day: noteDate,
          body,
          metric: null,
        },
        token ?? undefined,
        siteId
      );
      setDashboardNotes((prev) => [created, ...prev].sort((a, b) => b.day.localeCompare(a.day)));
      setSelectedNoteMarkerDay(bucketKeyFor(created.day, chartGranularity));
      setHoveredNoteMarkerDay(null);
      setNoteBody("");
      setIsNoteComposerOpen(false);
      setNoteStatus("Saved");
    } catch (error) {
      setNoteStatus(extractApiErrorMessage(error) ?? "Unable to save note.");
      console.error(error);
    } finally {
      setIsSavingNote(false);
    }
  };
  const handleDeleteNote = async (note: DashboardNote) => {
    if (!canQuery || showSeededBreakdowns) return;
    setNoteStatus(null);
    try {
      await deleteDashboardNote(note.id, token ?? undefined, siteId);
      setDashboardNotes((prev) => prev.filter((item) => item.id !== note.id));
    } catch (error) {
      setNoteStatus(extractApiErrorMessage(error) ?? "Unable to delete note.");
      console.error(error);
    }
  };

  const slugify = (value: string) => value.toLowerCase().replace(/\s+/g, "-");
  const downloadCsv = (lines: string[], filename: string) => {
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleExportAllMetricsCsv = async () => {
    if (authEnabled && !token) return;
    const metricKeys = [...aggregateMetricKeys];
    const forecasts = await Promise.all(
      metricKeys.map(async (metric) => {
        if (metric === selectedMetric) {
          return { metric, forecast };
        }
        try {
          const response = await fetchForecast(token ?? undefined, metric, siteId);
          return { metric, forecast: response.forecast };
        } catch (error) {
          console.error(error);
          return { metric, forecast: [] as ForecastEntry[] };
        }
      })
    );
    const forecastMap = new Map(forecasts.map((item) => [item.metric, item.forecast]));
    const lines: string[] = [["date", "metric", "actual", "forecast", "forecast_lower", "forecast_upper"].join(",")];
    metricKeys.forEach((metric) => {
      const actualEntries = getDailySeries(metric);
      const actualByDay = new Map(actualEntries.map((row) => [row.day, row.value]));
      const lastDay = actualEntries.length > 0 ? actualEntries[actualEntries.length - 1].day : null;
      const metricForecast = forecastMap.get(metric) ?? [];
      const metricWindow = resolveForecastWindow(metricForecast, lastDay, selectedForecast);
      const forecastByDay = new Map(metricWindow.entries.map((entry) => [entry.day, entry]));
      const days = Array.from(new Set([...actualByDay.keys(), ...forecastByDay.keys()])).sort((a, b) =>
        a.localeCompare(b)
      );
      const toCell = (value?: number) => {
        const safeValue = value ?? Number.NaN;
        if (!Number.isFinite(safeValue)) return "";
        return metric === "revenue" ? safeValue.toFixed(2) : safeValue.toFixed(0);
      };
      days.forEach((day) => {
        const actual = actualByDay.get(day);
        const forecastRow = forecastByDay.get(day);
        lines.push(
          [
            day,
            metric,
            toCell(actual),
            toCell(forecastRow?.yhat),
            toCell(forecastRow?.yhat_lower),
            toCell(forecastRow?.yhat_upper),
          ].join(",")
        );
      });
    });
    const slug = slugify(range);
    const forecastSlug = `forecast-${slugify(forecastLabel)}`;
    downloadCsv(lines, `valid-all-metrics-${slug}-${forecastSlug}.csv`);
  };

  const handleExportCsv = async () => {
    if (exportMode === "all") {
      await handleExportAllMetricsCsv();
      return;
    }
    if (csvRows.length === 0) return;
    const isRevenue = selectedMetric === "revenue";
    const isRate = selectedMetric === "bounce_rate";
    const isRatio = selectedMetric === "avg_pages_per_visit";
    const isDuration = selectedMetric === "visit_duration";
    const toCell = (value?: number) => {
      const safeValue = value ?? Number.NaN;
      if (!Number.isFinite(safeValue)) return "";
      if (isRate || isRatio) return safeValue.toFixed(4);
      if (isDuration) return safeValue.toFixed(1);
      if (isRevenue) return safeValue.toFixed(2);
      return safeValue.toFixed(0);
    };
    const lines = [
      ["date", "actual", "forecast", "forecast_lower", "forecast_upper"].join(","),
      ...csvRows.map((row) =>
        [
          row.day,
          toCell(row.actual),
          toCell(row.forecast),
          toCell(row.lower),
          toCell(row.upper),
        ].join(",")
      ),
    ];
    const slug = slugify(range);
    const forecastSlug = `forecast-${slugify(forecastLabel)}`;
    downloadCsv(lines, `valid-${selectedMetric}-${slug}-${forecastSlug}.csv`);
  };

  const handleExportPdf = () => {
    window.print();
  };
  const handleExportAction = async () => {
    if (exportFormat === "pdf") {
      handleExportPdf();
      return;
    }
    await handleExportCsv();
  };
  const csvRows = useMemo(() => {
    const actualByDay = new Map(dailySelected.map((row) => [row.day, row.value]));
    const forecastByDay = new Map(forecastHorizon.map((entry) => [entry.day, entry]));
    const days = Array.from(new Set([...actualByDay.keys(), ...forecastByDay.keys()])).sort((a, b) =>
      a.localeCompare(b)
    );
    return days.map((day) => {
      const actual = actualByDay.get(day);
      const forecastRow = forecastByDay.get(day);
      return {
        day,
        actual,
        forecast: forecastRow?.yhat,
        lower: forecastRow?.yhat_lower,
        upper: forecastRow?.yhat_upper,
      };
    });
  }, [dailySelected, forecastHorizon]);
  const renderNoteMarkerLabel = (day: string) => (props: { viewBox?: { x?: number; y?: number; height?: number } }) => {
    const viewBox = props.viewBox ?? {};
    const x = Number(viewBox.x ?? 0);
    const y = Number(viewBox.y ?? 0) + Number(viewBox.height ?? 0) - 3;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const isActive = activeNoteMarkerDay === day;
    const toggleMarker = () => {
      setSelectedNoteMarkerDay((current) => (current === day ? null : day));
      setHoveredNoteMarkerDay(null);
    };
    return (
      <g
        transform={`translate(${x},${y})`}
        role="button"
        tabIndex={0}
        aria-label={`Notes for ${formatShortDate(day)}`}
        onMouseEnter={() => setHoveredNoteMarkerDay(day)}
        onClick={toggleMarker}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleMarker();
          }
        }}
        className="cursor-pointer outline-none"
      >
        <path
          d="M -5 0 L 5 0 L 0 -8 Z"
          fill={isActive ? "#4F46E5" : "#7C83FF"}
          stroke="#FFFFFF"
          strokeWidth={1.5}
        />
      </g>
    );
  };

  return (
    <div className="min-h-screen bg-[#F5F6F8] print-bg">
      <header className="no-print">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-start justify-between gap-4 px-5 pb-3 pt-8 sm:px-8">
          <div>
            <div className="text-[22px] font-semibold leading-none text-[#111827]" style={fontHeading}>
              Valid
            </div>
            <div className="mt-4 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
              Site · {siteId}
            </div>
          </div>
          <div className="flex max-w-full flex-col items-end gap-2">
            <div className="flex max-w-full items-center gap-2 overflow-x-auto whitespace-nowrap">
            <select
              aria-label="Date range"
              className={`${dashboardControlClass} border-[#6B63FF] text-[#5b55ff]`}
              style={fontBody}
              value={range}
              onChange={(event) => setRange(event.target.value as RangeOption)}
            >
              {rangeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            {!showSeededBreakdowns && (
              <select
                aria-label="Hostname filter"
                className={`${dashboardControlClass} w-[190px]`}
                style={fontBody}
                value={selectedHostname}
                onChange={(event) => setSelectedHostname(event.target.value)}
                title={selectedHostname === "all" ? "All hostnames" : selectedHostname}
              >
                <option value="all">All hostnames</option>
                {hostnameOptions.map((host) => (
                  <option key={host} value={host}>
                    {host}
                  </option>
                ))}
              </select>
            )}
            {range === "Custom" && (
              <div className="flex items-center gap-1">
                <input
                  type="date"
                  aria-label="Custom range start date"
                  className={dashboardControlClass}
                  style={fontBody}
                  min={availableBounds?.min}
                  max={availableBounds?.max}
                  value={customRange.start}
                  autoFocus={range === "Custom" && !customRange.start}
                  onChange={(event) =>
                    setCustomRange((prev) => {
                      const nextStart = event.target.value;
                      const nextEnd = prev.end && prev.end < nextStart ? nextStart : prev.end;
                      return { start: nextStart, end: nextEnd };
                    })
                  }
                />
                <span className="text-[10px] text-gray-400" style={fontBody}>
                  to
                </span>
                <input
                  type="date"
                  aria-label="Custom range end date"
                  className={dashboardControlClass}
                  style={fontBody}
                  min={availableBounds?.min}
                  max={availableBounds?.max}
                  value={customRange.end}
                  onChange={(event) =>
                    setCustomRange((prev) => {
                      const nextEnd = event.target.value;
                      const nextStart = prev.start && prev.start > nextEnd ? nextEnd : prev.start;
                      return { start: nextStart, end: nextEnd };
                    })
                  }
                />
              </div>
            )}
            <label className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[#DDE4EC] bg-white px-3 text-[11px] font-semibold text-[#5F6673] shadow-sm">
              <input
                type="checkbox"
                checked={compareEnabled}
                onChange={(event) => setCompareEnabled(event.target.checked)}
              />
              <span style={fontBody}>Compare</span>
            </label>
            {compareEnabled && (
              <>
                <select
                  aria-label="Comparison period"
                  className={dashboardControlClass}
                  style={fontBody}
                  value={compareMode}
                  onChange={(event) => setCompareMode(event.target.value as "previous" | "custom")}
                >
                  <option value="previous">Previous period</option>
                  <option value="custom">Custom range</option>
                </select>
                {compareMode === "custom" && (
                  <div className="flex items-center gap-1">
                    <input
                      type="date"
                      aria-label="Comparison start date"
                      className={dashboardControlClass}
                      style={fontBody}
                      min={availableBounds?.min}
                      max={availableBounds?.max}
                      value={compareRange.start}
                      onChange={(event) =>
                        setCompareRange((prev) => {
                          const nextStart = event.target.value;
                          const nextEnd = prev.end && prev.end < nextStart ? nextStart : prev.end;
                          return { start: nextStart, end: nextEnd };
                        })
                      }
                    />
                    <span className="text-[10px] text-gray-400" style={fontBody}>
                      to
                    </span>
                    <input
                      type="date"
                      aria-label="Comparison end date"
                      className={dashboardControlClass}
                      style={fontBody}
                      min={availableBounds?.min}
                      max={availableBounds?.max}
                      value={compareRange.end}
                      onChange={(event) =>
                        setCompareRange((prev) => {
                          const nextEnd = event.target.value;
                          const nextStart = prev.start && prev.start > nextEnd ? nextEnd : prev.start;
                          return { start: nextStart, end: nextEnd };
                        })
                      }
                    />
                  </div>
                )}
              </>
            )}
            <select
              aria-label="Export format"
              className={dashboardControlClass}
              style={fontBody}
              value={exportFormat}
              onChange={(event) => setExportFormat(event.target.value as "csv" | "pdf")}
            >
              <option value="csv">CSV</option>
              <option value="pdf">PDF</option>
            </select>
            {exportFormat === "csv" && (
              <select
                aria-label="CSV export scope"
                className={`${dashboardControlClass} w-[150px]`}
                style={fontBody}
                value={exportMode}
                onChange={(event) => setExportMode(event.target.value as "current" | "all")}
              >
                <option value="current">Selected metric</option>
                <option value="all">All metrics</option>
              </select>
            )}
            <button
              type="button"
              onClick={() => void handleExportAction()}
              className={dashboardActionClass}
              style={fontBody}
            >
              Export
            </button>
            <a
              href={`/site/${encodeURIComponent(siteId)}/settings`}
              className={dashboardActionClass}
              style={fontBody}
            >
              Settings
            </a>
            <ThemeToggle />
            <LogoutButton className={dashboardActionClass} />
            </div>
            <div className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
              Metrics · {range}{hostnameFilter ? ` · ${hostnameFilter}` : ""}
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1180px] space-y-5 px-5 pb-12 pt-0 sm:px-8 print-container">
        {accessError && (
          <div className="border-l-2 border-[#8B2635] bg-[#FFF4F5] px-4 py-3 text-sm text-[#6B1F2A]" style={fontBody}>
            {accessError}
          </div>
        )}
        <KPIGrid
          values={scaledTotals}
          comparisonValues={scaledKpiComparisonValues}
          comparisonLabel={kpiComparisonLabel}
          currentRangeLabel={currentRangeLabel}
          comparisonRangeLabel={comparisonRangeLabel}
          showDetailedComparison={compareEnabled}
          selectedMetric={selectedMetric}
          onSelectMetric={setSelectedMetric}
        />
        {forecastMeta?.has_anomaly &&
          !dismissedAnomalies.has(`${siteId}:${selectedMetric}`) && (
            <div
              role="status"
              className="flex items-start gap-3 border-l-2 border-[#8B2635] bg-[#FBEFF1] px-4 py-3 text-[13px] text-[#1F2937]"
              style={fontBody}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                stroke="#8B2635"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="mt-0.5 shrink-0"
              >
                <path d="M8 1.5 L14.5 13.5 L1.5 13.5 Z" />
                <line x1="8" y1="6" x2="8" y2="9.5" />
                <circle cx="8" cy="11.5" r="0.6" fill="#8B2635" stroke="none" />
              </svg>
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-[#8B2635]">
                  Anomaly detected in {metricLabels[selectedMetric] ?? selectedMetric}
                </div>
                <div className="mt-0.5 text-[12px] text-[#4B5563]">
                  Recent traffic was unusually different from the site's recent pattern. Forecasts may be wider while the trend stabilizes.
                </div>
              </div>
              <button
                type="button"
                aria-label="Dismiss anomaly notice"
                onClick={() =>
                  setDismissedAnomalies((prev) => {
                    const next = new Set(prev);
                    next.add(`${siteId}:${selectedMetric}`);
                    return next;
                  })
                }
                className="shrink-0 p-1 text-[#8B2635]/70 transition-colors hover:text-[#8B2635]"
              >
                <CloseIcon />
              </button>
            </div>
          )}
        {activeFilters.length > 0 && (
          <div className="sticky top-0 z-30 bg-[#4338ca] py-2 text-white shadow-sm no-print">
            <div className="flex flex-wrap items-center gap-2 px-3 text-[12px]" style={fontBody}>
              <span className="text-[10px] uppercase tracking-[0.18em] text-white/70" style={fontMeta}>
                Segment
              </span>
              {activeFilters.map((filter) => (
                <span
                  key={`${filter.dimension}:${filter.value}`}
                  className="inline-flex items-center gap-1.5 bg-white/15 px-2 py-0.5"
                >
                  <span className="text-white/70">{renderFilterDimensionLabel(filter.dimension)}:</span>
                  <span className="font-semibold">{renderBreakdownLabel(filter.dimension, filter.value)}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${filter.dimension} filter`}
                    onClick={() => removeFilter(filter.dimension, filter.value)}
                    className="-mr-0.5 ml-0.5 p-0.5 text-white/70 hover:text-white"
                  >
                    <CloseIcon />
                  </button>
                </span>
              ))}
              <button
                type="button"
                onClick={() => setActiveFilters([])}
                className="border border-white/40 bg-transparent px-2 py-0.5 text-[11px] text-white/90 hover:bg-white/10"
              >
                Clear all
              </button>
              <span className="ml-auto text-[11px] text-white/70">
                Trend & KPI views scaled by dimension share (approx).
              </span>
            </div>
          </div>
        )}
        <section className="rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[18px] font-semibold text-[#1F2937]" style={fontBody}>
                {selectedMetricLabel}
              </div>
              <div className="mt-1 text-[12px] text-[#7B8190]" style={fontBody}>
                {chartSubtitle}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
                Forecast horizon
              </span>
              <select
                aria-label="Forecast horizon"
                className={dashboardControlClass}
                style={fontBody}
                value={forecastKey}
                onChange={(event) => setForecastKey(event.target.value as ForecastOption["key"])}
              >
                {forecastOptions.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div
            className="relative mt-6"
            onMouseLeave={() => {
              if (!selectedNoteMarkerDay) setHoveredNoteMarkerDay(null);
            }}
          >
            {!hasActual && !hasForecast ? (
              <div className="py-10 text-sm text-gray-400" style={fontBody}>
                No chart data yet. Seed events, run the reducer, and reload.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={chartData}>
                  <CartesianGrid stroke={chartGridStroke} strokeDasharray="2 6" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={(value: string) => formatAxisDateGranular(value, chartGranularity)}
                    tick={{ fill: chartAxisTick, fontSize: 10, fontFamily: "var(--font-sans)" }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={24}
                    interval="preserveStartEnd"
                    tickMargin={8}
                  />
                  <YAxis
                    tickFormatter={chartFormatter}
                    tick={{ fill: chartAxisTick, fontSize: 10, fontFamily: "var(--font-sans)" }}
                    axisLine={false}
                    tickLine={false}
                    width={48}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length || !label) return null;
                      const point = payload[0]?.payload as TrendChartPoint | undefined;
                      if (!point) return null;
                      const actualValue = point.actual;
                      const todaySoFarValue = point.todaySoFar;
                      const compareValue = point.compare;
                      const forecastValue = point.forecast;
                      const delta =
                        Number.isFinite(actualValue ?? Number.NaN) && Number.isFinite(compareValue ?? Number.NaN) && (compareValue ?? 0) > 0
                          ? ((actualValue ?? 0) - (compareValue ?? 0)) / (compareValue ?? 1)
                          : Number.NaN;
                      const deltaDisplay = Number.isFinite(delta)
                        ? `${delta >= 0 ? "↑" : "↓"} ${Math.abs(delta * 100).toFixed(1)}%`
                        : null;
                      const deltaClass = Number.isFinite(delta)
                        ? delta >= 0
                          ? "text-[#6EE7B7]"
                          : "text-[#FCA5A5]"
                        : "text-gray-400";
                      return (
                        <div className="min-w-[208px] border border-[#111827] bg-[#111827] px-3 py-3 text-white shadow-lg">
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-gray-300" style={fontBody}>
                              {metricLabels[selectedMetric] ?? selectedMetric}
                            </div>
                            {deltaDisplay && (
                              <div className={`text-[11px] metric-number ${deltaClass}`} style={fontMetric}>
                                {deltaDisplay}
                              </div>
                            )}
                          </div>
                          {Number.isFinite(actualValue ?? Number.NaN) && (
                            <div className="flex items-center justify-between gap-4 py-1 text-sm">
                              <span className="text-gray-200" style={fontBody}>{formatTooltipDateGranular(String(label), chartGranularity)}</span>
                              <span className="metric-number text-white" style={fontMetric}>
                                {formatMetricValue(selectedMetric, actualValue ?? Number.NaN)}
                              </span>
                            </div>
                          )}
                          {Number.isFinite(todaySoFarValue ?? Number.NaN) && String(label) === todayKey && (
                            <div className="flex items-center justify-between gap-4 py-1 text-sm">
                              <span className="text-gray-200" style={fontBody}>Today so far</span>
                              <span className="metric-number text-white" style={fontMetric}>
                                {formatMetricValue(selectedMetric, todaySoFarValue ?? Number.NaN)}
                              </span>
                            </div>
                          )}
                          {compareEnabled && Number.isFinite(compareValue ?? Number.NaN) && (
                            <div className="flex items-center justify-between gap-4 py-1 text-sm">
                              <span className="text-gray-400" style={fontBody}>
                                {point.compareDay
                                  ? formatTooltipDateGranular(point.compareDay, chartGranularity)
                                  : "Previous period"}
                              </span>
                              <span className="metric-number text-gray-200" style={fontMetric}>
                                {formatMetricValue(selectedMetric, compareValue ?? Number.NaN)}
                              </span>
                            </div>
                          )}
                          {!Number.isFinite(actualValue ?? Number.NaN) && Number.isFinite(forecastValue ?? Number.NaN) && (
                            <div className="mt-2 border-t border-white/10 pt-2">
                              <div className="flex items-center justify-between gap-4 py-1 text-sm">
                                <span className="text-gray-200" style={fontBody}>{formatTooltipDateGranular(String(label), chartGranularity)}</span>
                                <span className="metric-number text-white" style={fontMetric}>
                                  {formatMetricValue(selectedMetric, forecastValue ?? Number.NaN)}
                                </span>
                              </div>
                              {Number.isFinite(point.forecastLower ?? Number.NaN) && (
                                <div className="flex items-center justify-between gap-4 py-1 text-sm">
                                  <span className="text-gray-400" style={fontBody}>Lower interval</span>
                                  <span className="metric-number text-gray-200" style={fontMetric}>
                                    {formatMetricValue(selectedMetric, point.forecastLower ?? Number.NaN)}
                                  </span>
                                </div>
                              )}
                              {Number.isFinite(point.forecastUpper ?? Number.NaN) && (
                                <div className="flex items-center justify-between gap-4 py-1 text-sm">
                                  <span className="text-gray-400" style={fontBody}>Upper interval</span>
                                  <span className="metric-number text-gray-200" style={fontMetric}>
                                    {formatMetricValue(selectedMetric, point.forecastUpper ?? Number.NaN)}
                                  </span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    }}
                    contentStyle={{
                      borderRadius: 0,
                      borderColor: "var(--color-border-subtle)",
                      fontSize: "12px",
                      fontFamily: "var(--font-sans)",
                      fontVariantNumeric: "tabular-nums lining-nums",
                      fontFeatureSettings: '"tnum" 1, "lnum" 1',
                    }}
                    cursor={{ stroke: chartGridStroke }}
                  />
                  {showTodayLine && (
                    <ReferenceLine
                      x={todayKey}
                      stroke={chartReferenceStroke}
                      strokeDasharray="3 6"
                      label={{
                        value: "Now",
                        position: "top",
                        fill: chartAxisTick,
                        fontSize: 10,
                        fontFamily: fontBody.fontFamily,
                      }}
                    />
                  )}
                  {hasForecast && forecastStartDay && !showTodayLine && (
                    <ReferenceLine
                      x={forecastStartDay}
                      stroke={chartReferenceStroke}
                      strokeDasharray="3 6"
                      label={{
                        value: "Forecast starts",
                        position: "top",
                        fill: chartAxisTick,
                        fontSize: 10,
                        fontFamily: "var(--font-sans)",
                      }}
                    />
                  )}
                  {noteMarkerDays.map((day) => (
                    <ReferenceLine
                      key={`note-${day}`}
                      x={day}
                      stroke="transparent"
                      strokeOpacity={0}
                      ifOverflow="extendDomain"
                      label={renderNoteMarkerLabel(day)}
                    />
                  ))}
                  {hasForecastBand && (
                    <>
                      <Area
                        type="linear"
                        dataKey="forecastLower"
                        stackId="forecast-band"
                        stroke="none"
                        fill="transparent"
                        isAnimationActive={false}
                      />
                      <Area
                        type="linear"
                        dataKey="forecastBandSpan"
                        stackId="forecast-band"
                        stroke="none"
                        fill="#6366f1"
                        fillOpacity={0.16}
                        isAnimationActive={false}
                      />
                    </>
                  )}
                  {compareEnabled && hasCompare && (
                    <>
                      <Area
                        type="linear"
                        dataKey="deltaPositiveRange"
                        stroke="none"
                        fill="#4f46e5"
                        fillOpacity={0.14}
                        isAnimationActive={false}
                        activeDot={false}
                        legendType="none"
                      />
                      <Area
                        type="linear"
                        dataKey="deltaNegativeRange"
                        stroke="none"
                        fill="#8B2635"
                        fillOpacity={0.12}
                        isAnimationActive={false}
                        activeDot={false}
                        legendType="none"
                      />
                    </>
                  )}
                  {hasActual && (
                    <Line
                      type="linear"
                      dataKey="actual"
                      stroke="#4f46e5"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {hasTodaySoFar && (
                    <Line
                      type="linear"
                      dataKey="todaySoFar"
                      stroke="#9b8cf6"
                      strokeWidth={2}
                      dot={{ r: 3, fill: "#9b8cf6", stroke: "#ffffff", strokeWidth: 1.5 }}
                      isAnimationActive={false}
                    />
                  )}
                  {hasTodayBridge && (
                    <Line
                      type="linear"
                      dataKey="todayBridge"
                      stroke="#4f46e5"
                      strokeWidth={2}
                      dot={false}
                      activeDot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {compareEnabled && hasCompare && (
                    <Line
                      type="linear"
                      dataKey="compare"
                      stroke="#9CA3AF"
                      strokeWidth={1.5}
                      strokeDasharray="4 6"
                      strokeOpacity={0.75}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {hasForecast && (
                    <Line
                      type="linear"
                      dataKey="forecastLine"
                      stroke="#4338ca"
                      strokeWidth={2}
                      strokeDasharray="6 6"
                      strokeOpacity={0.9}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                </ComposedChart>
              </ResponsiveContainer>
            )}
            {activeNoteMarkerDay && activeMarkerNotes.length > 0 && (
              <div
                className="absolute bottom-3 left-3 z-20 w-[min(340px,calc(100%-24px))] rounded-md border border-[#DDE4EC] bg-white px-3 py-2 text-left shadow-lg"
                onMouseEnter={() => setHoveredNoteMarkerDay(activeNoteMarkerDay)}
                onMouseLeave={() => {
                  if (!selectedNoteMarkerDay) setHoveredNoteMarkerDay(null);
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontBody}>
                      Notes
                    </div>
                    <div className="mt-0.5 text-[11px] text-[#6B7280]" style={fontBody}>
                      {formatShortDate(activeNoteMarkerDay)}
                    </div>
                  </div>
                  {selectedNoteMarkerDay && (
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedNoteMarkerDay(null);
                        setHoveredNoteMarkerDay(null);
                      }}
                      className="-mr-1 rounded-full p-0.5 text-[#9CA3AF] transition-colors hover:bg-[#EEF2F7] hover:text-[#4B5563]"
                      aria-label="Close notes"
                    >
                      <CloseIcon />
                    </button>
                  )}
                </div>
                <div className="mt-2 space-y-2">
                  {activeMarkerNotes.map((note) => (
                    <div key={note.id} className="border-t border-[#EEF2F7] pt-2 first:border-t-0 first:pt-0">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#9CA3AF]" style={fontMeta}>
                            {formatShortDate(note.day)}
                            {note.metric ? ` · ${formatNoteMetric(note.metric)}` : ""}
                          </div>
                          <div className="mt-1 text-[12px] leading-5 text-[#374151]" style={fontBody}>
                            {note.body}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleDeleteNote(note)}
                          className="shrink-0 rounded-full p-0.5 text-[#B7C0CC] transition-colors hover:bg-[#EEF2F7] hover:text-[#8B2635]"
                          aria-label={`Delete note from ${note.day}`}
                        >
                          <CloseIcon />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-[#4B5563]" style={fontBody}>
            {hasActual && (
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 bg-[#4f46e5]" />
                Actual
              </span>
            )}
            {hasTodaySoFar && (
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 bg-[#9b8cf6]" />
                Today so far
              </span>
            )}
            {compareEnabled && hasCompare && (
              <>
                <span className="flex items-center gap-2">
                  <span className="h-0.5 w-5 border-b border-dashed border-gray-400" />
                  Comparison
                </span>
                <span className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-3 bg-[#4f46e5]/20" />
                  Ahead
                </span>
                <span className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-3 bg-[#8B2635]/20" />
                  Behind
                </span>
              </>
            )}
            {hasForecast && (
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 border-b border-dashed border-[#4338ca]" />
                Forecast
              </span>
            )}
            {hasForecastBand && (
              <span className="flex items-center gap-2">
                <span className="h-2 w-5 bg-[#6366f1]/30" />
                Forecast interval
              </span>
            )}
            {trendFooterNote && <span className="text-xs text-[#6B7280]">{trendFooterNote}</span>}
            {chartGranularity !== "day" && (
              <span className="ml-auto text-[11px] italic text-[#6B7280]" style={fontBody}>
                Viewing {granularityLabel(chartGranularity)} (auto)
              </span>
            )}
            {hasForecast && (
              <span
                className={`${chartGranularity !== "day" ? "" : "ml-auto"} flex items-center gap-1.5 text-[11px] text-[#4B5563]`}
                style={fontBody}
              >
                Forecast accuracy <span className={`metric-number ${forecastAccuracyClass}`} style={fontMetric}>{forecastAccuracy}</span>
                {showForecastBuildingInfo && (
                  <span className="group relative inline-flex">
                    <span
                      tabIndex={0}
                      aria-label="Why forecast accuracy is building"
                      className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-[#DDE4EC] bg-white text-[10px] font-semibold text-[#7B8190] outline-none transition-colors hover:border-[#B9C3D0] hover:text-[#4B5563] focus:border-[#6B63FF] focus:text-[#4B5563]"
                      style={fontBody}
                    >
                      i
                    </span>
                    <span
                      role="tooltip"
                      className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 hidden w-[240px] rounded-md border border-[#DDE4EC] bg-white px-3 py-2 text-left text-[11px] leading-4 text-[#4B5563] shadow-lg group-hover:block group-focus-within:block"
                      style={fontBody}
                    >
                      {selectedMetricLabel} can take longer to reach a statistically useful forecast accuracy because it often has fewer completed daily data points.
                    </span>
                  </span>
                )}
              </span>
            )}
          </div>
          {!showSeededBreakdowns && (
            <div className="mt-2">
              <div className="flex flex-wrap items-center justify-end gap-2 text-[11px] text-[#6B7280]" style={fontBody}>
                <button
                  type="button"
                  onClick={() => {
                    setIsNoteComposerOpen((open) => !open);
                    setNoteStatus(null);
                  }}
                  className="inline-flex h-6 items-center rounded-full border border-transparent px-2 text-[11px] font-semibold text-[#4F46E5] transition-colors hover:bg-[#F1F3FF]"
                  aria-expanded={isNoteComposerOpen}
                  style={fontBody}
                >
                  + Add note
                </button>
                {noteStatus && <span className="text-[#7B8190]">{noteStatus}</span>}
              </div>
              {isNoteComposerOpen && (
                <div className="mt-2 flex flex-col gap-2 rounded-md border border-[#E5EAF1] bg-[#FBFCFE] px-3 py-2 sm:flex-row sm:items-center">
                  <input
                    type="date"
                    value={noteDate}
                    min={primaryRangeBounds?.start}
                    max={primaryRangeBounds?.end}
                    onChange={(event) => setNoteDate(event.target.value)}
                    className={`${dashboardControlClass} sm:w-[150px]`}
                    aria-label="Note date"
                    style={fontBody}
                  />
                  <input
                    type="text"
                    value={noteBody}
                    onChange={(event) => setNoteBody(event.target.value)}
                    maxLength={1200}
                    placeholder="Add context for this date"
                    className={`${dashboardControlClass} flex-1`}
                    aria-label="Note"
                    style={fontBody}
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleCreateNote}
                      disabled={isSavingNote || !noteBody.trim() || !noteDate}
                      className="inline-flex h-8 items-center rounded-md bg-[#4F46E5] px-3 text-[11px] font-semibold text-white transition-colors hover:bg-[#4338CA] disabled:cursor-not-allowed disabled:opacity-50"
                      style={fontBody}
                    >
                      {isSavingNote ? "Saving" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIsNoteComposerOpen(false);
                        setNoteBody("");
                        setNoteStatus(null);
                      }}
                      className="inline-flex h-8 items-center rounded-md px-2 text-[11px] font-semibold text-[#6B7280] transition-colors hover:bg-[#EEF2F7] hover:text-[#374151]"
                      style={fontBody}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="mt-4 border-t border-[var(--color-border-subtle)] pt-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-md border border-[var(--color-border-subtle)] bg-[#FBFCFE] px-4 py-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#7B8190]" style={fontBody}>
                  Today projected
                </div>
                <div className="mt-1 metric-number text-[21px] font-semibold leading-tight text-[#111827]" style={fontMetric}>
                  {formatMetricValue(selectedMetric, todayProjectionValue)}
                </div>
                <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
                  {todayProgressNote}
                </div>
              </div>
              <div className="rounded-md border border-[var(--color-border-subtle)] bg-[#FBFCFE] px-4 py-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#7B8190]" style={fontBody}>
                  {forecastTileHeading}
                </div>
                <div className="mt-1 metric-number text-[21px] font-semibold leading-tight text-[#111827]" style={fontMetric}>
                  {forecastSummary ? formatMetricValue(selectedMetric, forecastSummary.total) : "N/A"}
                </div>
                <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
                  {forecastSummary ? `Avg ${formatDailyPace(selectedMetric, forecastSummary.average)}` : forecastMutedNote}
                </div>
              </div>
              <div className="rounded-md border border-[var(--color-border-subtle)] bg-[#FBFCFE] px-4 py-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#7B8190]" style={fontBody}>
                  Vs prior period
                </div>
                <div
                  className={`mt-1 metric-number text-[21px] font-semibold leading-tight ${
                    Number.isFinite(selectedMetricDeltaPct) && selectedMetricDeltaPct < 0 ? "text-[#8B2635]" : "text-[#111827]"
                  }`}
                  style={fontMetric}
                >
                  {periodDeltaDisplay}
                </div>
                <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
                  {periodDeltaNote}
                </div>
              </div>
            </div>
          </div>
        </section>
        <section>
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
            Insights · {insightItems.length} things to know about this period
          </div>
          <div className="rounded-lg border border-[var(--color-border-subtle)] bg-white px-5 py-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="space-y-4">
              {insightItems.map((item) => (
                <div key={`${item.label}:${item.text}`} className="border-l-2 border-[#6B63FF] pl-3">
                  <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontBody}>
                    {item.label}
                  </div>
                  <div className="mt-1 text-[13px] leading-relaxed text-[#374151]" style={fontBody}>
                    {item.text}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section>
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
            Breakdowns
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <TableBlock
              title="Traffic Sources"
              header={
                <div>
                  <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
                    Traffic sources
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-4 text-[12px] font-semibold text-gray-500" style={fontBody}>
                    <button
                      type="button"
                      className={
                        acquisitionTab === "channels"
                          ? "rounded bg-[#F1F3F6] px-2 py-1 text-[#1F2937]"
                          : "px-2 py-1 hover:text-[#1F2937]"
                      }
                      onClick={() => setAcquisitionTab("channels")}
                    >
                      Channels
                    </button>
                    <button
                      type="button"
                      className={
                        acquisitionTab === "sources"
                          ? "rounded bg-[#F1F3F6] px-2 py-1 text-[#1F2937]"
                          : "px-2 py-1 hover:text-[#1F2937]"
                      }
                      onClick={() => setAcquisitionTab("sources")}
                    >
                      Sources
                    </button>
                    <button
                      type="button"
                      className={
                        acquisitionTab === "source_medium"
                          ? "rounded bg-[#F1F3F6] px-2 py-1 text-[#1F2937]"
                          : "px-2 py-1 hover:text-[#1F2937]"
                      }
                      onClick={() => setAcquisitionTab("source_medium")}
                    >
                      Source / Medium
                    </button>
                    <button
                      type="button"
                      className={
                        acquisitionTab === "campaigns"
                          ? "rounded bg-[#F1F3F6] px-2 py-1 text-[#1F2937]"
                          : "px-2 py-1 hover:text-[#1F2937]"
                      }
                      onClick={() => setAcquisitionTab("campaigns")}
                    >
                      Campaigns
                    </button>
                  {acquisitionTab === "campaigns" && (
                    <select
                      aria-label="Campaign dimension"
                      className={`${dashboardControlClass} h-7`}
                      style={fontBody}
                      value={campaignDimension}
                      onChange={(event) => setCampaignDimension(event.target.value as "campaign" | "content" | "term")}
                    >
                      <option value="campaign">Campaign</option>
                      <option value="content">Content</option>
                      <option value="term">Term</option>
                    </select>
                  )}
                  </div>
                </div>
              }
              rows={acquisitionRows}
              metricKeys={acquisitionMetricKeys}
              primaryMetric={acquisitionPrimaryMetric}
              total={acquisitionTotal}
              rowDimension={acquisitionDimensionKey}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
              emptyState={acquisitionEmptyState}
            />
            <TableBlock
              title="Top Pages"
              rows={breakdownCards[0]?.rows ?? []}
              metricKeys={breakdownCards[0]?.metricKeys ?? (["pageviews"] as BreakdownMetricKey[])}
              primaryMetric={breakdownCards[0]?.primaryMetric ?? "pageviews"}
              total={breakdownCards[0]?.total}
              emptyState={breakdownCards[0]?.empty}
              rowDimension={breakdownCards[0]?.dimension}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
            />
            <TableBlock
              title="Countries"
              rows={breakdownCards[1]?.rows ?? []}
              metricKeys={breakdownCards[1]?.metricKeys ?? (["pageviews"] as BreakdownMetricKey[])}
              primaryMetric={breakdownCards[1]?.primaryMetric ?? "pageviews"}
              total={breakdownCards[1]?.total}
              emptyState={breakdownCards[1]?.empty}
              rowDimension={breakdownCards[1]?.dimension}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
            />
            <TableBlock
              title="Devices"
              rows={breakdownCards[2]?.rows ?? []}
              metricKeys={breakdownCards[2]?.metricKeys ?? (["pageviews"] as BreakdownMetricKey[])}
              primaryMetric={breakdownCards[2]?.primaryMetric ?? "pageviews"}
              total={breakdownCards[2]?.total}
              emptyState={breakdownCards[2]?.empty}
              rowDimension={breakdownCards[2]?.dimension}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
            />
          </div>
        </section>
        <section>
          <div className="mb-3 text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
            Goals & Timing
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <GoalsProgressCard
              goals={dashboardGoals}
              values={scaledTotals as Record<string, number>}
              dayCount={selectedRangeDayCount}
              rangeLabel={currentRangeLabel ?? range}
              siteId={siteId}
            />
            <TimePartingHeatmap
              hourRows={showSeededBreakdowns ? seededHourRows : breakdownData.hour_of_day.rows}
              dayRows={showSeededBreakdowns ? seededDayRows : breakdownData.day_of_week.rows}
              primaryMetric={timePartingPrimaryMetric}
              dayType={timePartingDayType}
              setDayType={setTimePartingDayType}
              emptyState={timePartingEmptyState}
              rangeLabel={currentRangeLabel ?? range}
            />
          </div>
        </section>
      </main>
    </div>
  );
};

const SiteDashboardRedirect: React.FC = () => {
  const { siteId } = useParams<{ siteId?: string }>();
  return <Navigate to={siteId ? `/site/${encodeURIComponent(siteId)}` : "/"} replace />;
};

const Settings: React.FC = () => {
  const { token, authEnabled } = useAuth();
  const canQuery = !authEnabled || Boolean(token);
  const [searchParams] = useSearchParams();
  const { siteId: pathSiteId } = useParams<{ siteId?: string }>();
  const querySiteId = searchParams.get("site_id") ?? undefined;
  const siteId = useMemo(() => resolveActiveSiteId(pathSiteId ?? querySiteId), [pathSiteId, querySiteId]);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [timezoneDraft, setTimezoneDraft] = useState<string>("UTC");
  const [timezoneStatus, setTimezoneStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("idle");
  const [timezoneError, setTimezoneError] = useState<string | null>(null);
  const [billingPlan, setBillingPlan] = useState<"free" | "standard" | "pro">("free");
  const [hasSubscription, setHasSubscription] = useState<boolean>(false);
  const [billingStatus, setBillingStatus] = useState<"idle" | "loading" | "redirecting" | "error">("idle");
  const [billingMessage, setBillingMessage] = useState<string | null>(null);
  const [importCsvText, setImportCsvText] = useState<string>("");
  const [importStatus, setImportStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importBatches, setImportBatches] = useState<HistoricalImportBatch[]>([]);
  const [importHistoryStatus, setImportHistoryStatus] = useState<"idle" | "loading" | "error">("idle");
  const [importHistoryMessage, setImportHistoryMessage] = useState<string | null>(null);
  const [deletingImportBatchId, setDeletingImportBatchId] = useState<number | null>(null);
  const [health, setHealth] = useState<SiteHealthResponse | null>(null);
  const [healthStatus, setHealthStatus] = useState<"idle" | "loading" | "error">("idle");
  const [healthMessage, setHealthMessage] = useState<string | null>(null);
  const [accessMembers, setAccessMembers] = useState<SiteAccessMember[]>([]);
  const [accessUsername, setAccessUsername] = useState<string>("");
  const [accessStatus, setAccessStatus] = useState<"idle" | "loading" | "saving" | "error">("idle");
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [ipBlocks, setIpBlocks] = useState<SiteIpBlock[]>([]);
  const [ipBlockCidr, setIpBlockCidr] = useState<string>("");
  const [ipBlockLabel, setIpBlockLabel] = useState<string>("");
  const [ipBlockStatus, setIpBlockStatus] = useState<"idle" | "loading" | "saving" | "error">("idle");
  const [ipBlockMessage, setIpBlockMessage] = useState<string | null>(null);
  const [deletingIpBlockId, setDeletingIpBlockId] = useState<number | null>(null);
  const [goals, setGoals] = useState<SiteGoalsMap>({});
  const [goalMetric, setGoalMetric] = useState<GoalMetric>("revenue");
  const [goalTargetInput, setGoalTargetInput] = useState<string>("");
  const [goalStatus, setGoalStatus] = useState<string | null>(null);

  useEffect(() => {
    setGoals(loadGoalsForSite(siteId));
  }, [siteId]);

  useEffect(() => {
    if (!canQuery) return;
    let cancelled = false;
    setTimezoneStatus("loading");
    fetchSiteSettings(token ?? undefined, siteId)
      .then((settings) => {
        if (cancelled) return;
        const resolvedTimezone = settings.timezone || "UTC";
        setTimezone(resolvedTimezone);
        setTimezoneDraft(resolvedTimezone);
        setTimezoneStatus("idle");
        setTimezoneError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setTimezone("UTC");
        setTimezoneDraft("UTC");
        setTimezoneStatus("error");
        setTimezoneError(extractApiErrorMessage(error) ?? "Unable to load timezone settings.");
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, token, siteId]);

  useEffect(() => {
    if (!canQuery) return;
    let cancelled = false;
    setBillingStatus("loading");
    setBillingMessage(null);
    fetchBillingStatus(token ?? undefined, siteId)
      .then((status) => {
        if (cancelled) return;
        setBillingPlan(status.plan);
        setHasSubscription(Boolean(status.has_subscription));
        setBillingStatus("idle");
      })
      .catch((error) => {
        if (cancelled) return;
        setBillingStatus("error");
        setBillingMessage(extractApiErrorMessage(error) ?? "Unable to load billing status right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, token, siteId]);

  useEffect(() => {
    if (!canQuery) return;
    let cancelled = false;
    setHealthStatus("loading");
    setHealthMessage(null);
    fetchSiteHealth(token ?? undefined, siteId)
      .then((result) => {
        if (cancelled) return;
        setHealth(result);
        setHealthStatus("idle");
      })
      .catch((error) => {
        if (cancelled) return;
        setHealth(null);
        setHealthStatus("error");
        setHealthMessage(extractApiErrorMessage(error) ?? "Unable to load tracking health right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, token, siteId]);

  const refreshImportHistory = useCallback(async () => {
    if (!canQuery || billingPlan !== "standard") {
      setImportBatches([]);
      setImportHistoryStatus("idle");
      setImportHistoryMessage(null);
      return;
    }
    setImportHistoryStatus("loading");
    setImportHistoryMessage(null);
    try {
      const result = await fetchImportHistory(token ?? undefined, siteId);
      setImportBatches(result.batches ?? []);
      setImportHistoryStatus("idle");
    } catch (error) {
      setImportHistoryStatus("error");
      setImportHistoryMessage(extractApiErrorMessage(error) ?? "Unable to load import history right now.");
    }
  }, [billingPlan, canQuery, siteId, token]);

  useEffect(() => {
    void refreshImportHistory();
  }, [refreshImportHistory]);

  const refreshSiteAccess = useCallback(async () => {
    if (!canQuery) return;
    setAccessStatus("loading");
    setAccessMessage(null);
    try {
      const result = await fetchSiteAccess(token ?? undefined, siteId);
      setAccessMembers(result.members ?? []);
      setAccessStatus("idle");
    } catch (error) {
      setAccessMembers([]);
      setAccessStatus("error");
      setAccessMessage(extractApiErrorMessage(error) ?? "Unable to load site access right now.");
    }
  }, [canQuery, siteId, token]);

  useEffect(() => {
    void refreshSiteAccess();
  }, [refreshSiteAccess]);

  const refreshIpBlocks = useCallback(async () => {
    if (!canQuery) return;
    setIpBlockStatus("loading");
    setIpBlockMessage(null);
    try {
      const result = await fetchSiteIpBlocks(token ?? undefined, siteId);
      setIpBlocks(result.blocks ?? []);
      setIpBlockStatus("idle");
    } catch (error) {
      setIpBlocks([]);
      setIpBlockStatus("error");
      setIpBlockMessage(extractApiErrorMessage(error) ?? "Unable to load IP block list right now.");
    }
  }, [canQuery, siteId, token]);

  useEffect(() => {
    void refreshIpBlocks();
  }, [refreshIpBlocks]);

  const existingGoal = goals[goalMetric];
  useEffect(() => {
    setGoalTargetInput(existingGoal ? String(existingGoal.target) : "");
  }, [goalMetric, existingGoal?.target]);

  const sortedGoals = useMemo(
    () =>
      goalEligibleMetrics
        .map((metric) => goals[metric])
        .filter((goal): goal is MetricGoal => Boolean(goal)),
    [goals]
  );

  const saveTimezone = async () => {
    setTimezoneStatus("saving");
    setTimezoneError(null);
    try {
      const updated = await updateSiteTimezone(timezoneDraft, token ?? undefined, siteId);
      const resolvedTimezone = updated.timezone || timezoneDraft;
      setTimezone(resolvedTimezone);
      setTimezoneDraft(resolvedTimezone);
      setTimezoneStatus("saved");
      window.setTimeout(() => {
        setTimezoneStatus((prev) => (prev === "saved" ? "idle" : prev));
      }, 1200);
    } catch (error) {
      setTimezoneStatus("error");
      setTimezoneError(extractApiErrorMessage(error) ?? "Unable to update timezone right now.");
    }
  };

  const beginStandardCheckout = async () => {
    setBillingStatus("redirecting");
    setBillingMessage(null);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "https://app.validanalytics.io";
      const successUrl = `${origin}/billing/success?site_id=${encodeURIComponent(siteId)}`;
      const cancelUrl = `${origin}/site/${encodeURIComponent(siteId)}/settings`;
      const checkoutPlan = billingPlan === "pro" ? "pro" : "standard";
      const checkout = await createCheckoutSession(checkoutPlan, token ?? undefined, siteId, successUrl, cancelUrl);
      window.location.assign(checkout.checkout_url);
    } catch (error) {
      setBillingStatus("error");
      setBillingMessage(extractApiErrorMessage(error) ?? "Unable to start checkout right now.");
    }
  };

  const handleImportFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setImportStatus("idle");
    setImportMessage(null);
    try {
      setImportCsvText(await file.text());
    } catch {
      setImportStatus("error");
      setImportMessage("Unable to read that CSV file.");
    }
  };

  const submitHistoricalImport = async () => {
    const csvText = importCsvText.trim();
    if (!csvText) {
      setImportStatus("error");
      setImportMessage("Paste or upload a CSV before importing.");
      return;
    }
    setImportStatus("loading");
    setImportMessage(null);
    try {
      const result = await importHistoricalCsv(csvText, token ?? undefined, siteId);
      setImportStatus("success");
      setImportMessage(
        `Imported ${formatNumber(result.imported_rows)} rows across ${formatNumber(result.reduced_days)} days${
          result.batch_id ? ` in batch ${result.batch_id}` : ""
        }.`
      );
      await refreshImportHistory();
    } catch (error) {
      setImportStatus("error");
      setImportMessage(extractApiErrorMessage(error) ?? "Unable to import historical data right now.");
    }
  };

  const deleteImport = async (batchId: number) => {
    setDeletingImportBatchId(batchId);
    setImportHistoryMessage(null);
    try {
      const result = await rollbackImportBatch(batchId, token ?? undefined, siteId);
      setImportMessage(
        `Deleted import ${result.batch_id}. Removed ${formatNumber(result.deleted_rows)} rows and rebuilt ${formatNumber(
          result.reduced_days
        )} days.`
      );
      setImportStatus("success");
      await refreshImportHistory();
    } catch (error) {
      setImportStatus("error");
      setImportMessage(extractApiErrorMessage(error) ?? "Unable to delete that import right now.");
    } finally {
      setDeletingImportBatchId(null);
    }
  };

  const addSiteMember = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const username = accessUsername.trim().toLowerCase();
    if (!username) {
      setAccessStatus("error");
      setAccessMessage("Enter a dashboard username to add.");
      return;
    }
    setAccessStatus("saving");
    setAccessMessage(null);
    try {
      const result = await grantSiteAccess(username, token ?? undefined, siteId);
      setAccessMembers(result.members ?? []);
      setAccessUsername("");
      setAccessStatus("idle");
      setAccessMessage(`${username} can now access this site.`);
    } catch (error) {
      setAccessStatus("error");
      setAccessMessage(extractApiErrorMessage(error) ?? "Unable to add that user right now.");
    }
  };

  const removeSiteMember = async (username: string) => {
    setAccessStatus("saving");
    setAccessMessage(null);
    try {
      const result = await removeSiteAccess(username, token ?? undefined, siteId);
      setAccessMembers(result.members ?? []);
      setAccessStatus("idle");
      setAccessMessage(`${username} was removed from this site.`);
    } catch (error) {
      setAccessStatus("error");
      setAccessMessage(extractApiErrorMessage(error) ?? "Unable to remove that user right now.");
    }
  };

  const addIpBlock = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const cidr = ipBlockCidr.trim();
    if (!cidr) {
      setIpBlockStatus("error");
      setIpBlockMessage("Enter an IP address or CIDR range to block.");
      return;
    }
    setIpBlockStatus("saving");
    setIpBlockMessage(null);
    try {
      const result = await createSiteIpBlock(cidr, ipBlockLabel.trim() || undefined, token ?? undefined, siteId);
      setIpBlocks(result.blocks ?? []);
      setIpBlockCidr("");
      setIpBlockLabel("");
      setIpBlockStatus("idle");
      setIpBlockMessage("IP block added. Matching future traffic will be ignored.");
    } catch (error) {
      setIpBlockStatus("error");
      setIpBlockMessage(extractApiErrorMessage(error) ?? "Unable to add that IP block right now.");
    }
  };

  const removeIpBlock = async (blockId: number) => {
    setDeletingIpBlockId(blockId);
    setIpBlockMessage(null);
    try {
      const result = await deleteSiteIpBlock(blockId, token ?? undefined, siteId);
      setIpBlocks(result.blocks ?? []);
      setIpBlockStatus("idle");
      setIpBlockMessage("IP block removed.");
    } catch (error) {
      setIpBlockStatus("error");
      setIpBlockMessage(extractApiErrorMessage(error) ?? "Unable to remove that IP block right now.");
    } finally {
      setDeletingIpBlockId(null);
    }
  };

  const hasTimezoneChanges = timezoneDraft !== timezone;
  const canImportHistoricalData = billingPlan === "standard";
  const importStatusClassName = importStatus === "error" ? "text-[#8B2635]" : "text-gray-500";

  const billingDescription = (() => {
    if (billingPlan === "standard") {
      return hasSubscription
        ? "Your Standard subscription is active for this site."
        : "This site is marked Standard but no active subscription is linked yet.";
    }
    if (billingPlan === "pro") {
      return "Your Pro subscription is active for this site.";
    }
    return "This site is on the Free plan.";
  })();

  const billingActionLabel =
    billingPlan === "free"
      ? "Upgrade To Standard"
      : billingPlan === "standard"
        ? "Update Standard Subscription"
        : "Manage Pro Subscription";

  const billingActionDisabled = billingStatus === "redirecting" || billingStatus === "loading";

  const billingStatusText =
    billingStatus === "loading"
      ? "Loading billing status..."
      : billingStatus === "redirecting"
        ? "Opening secure Stripe checkout..."
        : billingStatus === "error"
          ? billingMessage ?? "Unable to load billing right now."
          : billingDescription;

  const timezoneStatusText =
    timezoneStatus === "loading"
      ? "Loading timezone..."
      : timezoneStatus === "saving"
        ? "Saving timezone..."
        : timezoneStatus === "saved"
          ? "Timezone updated."
          : timezoneStatus === "error"
            ? timezoneError ?? "Unable to update timezone right now."
            : "Used to bucket daily trends and date-range reporting for this site.";

  const timezoneStatusClassName = timezoneStatus === "error" ? "text-[#8B2635]" : "text-gray-500";


  const submitGoal = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const target = Number(goalTargetInput);
    if (!Number.isFinite(target) || target <= 0) {
      setGoalStatus("Enter a valid target greater than zero.");
      return;
    }
    const nextGoals = upsertGoalForSite(siteId, {
      metric: goalMetric,
      target,
      periodDays: 30,
      repeat: "monthly",
    });
    setGoals(nextGoals);
    setGoalStatus(`${metricLabels[goalMetric] ?? goalMetric} goal saved.`);
  };

  const clearGoal = () => {
    const nextGoals = removeGoalForSite(siteId, goalMetric);
    setGoals(nextGoals);
    setGoalStatus(`${metricLabels[goalMetric] ?? goalMetric} goal removed.`);
    setGoalTargetInput("");
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB] print-bg">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <a href={`/site/${encodeURIComponent(siteId)}`} className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
            Valid
          </a>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 pb-10 pt-6">
        <a href={`/site/${encodeURIComponent(siteId)}`} className="text-sm font-semibold text-[#4f46e5]" style={fontBody}>
          Back to stats
        </a>
        <div className="mt-2 border-b border-gray-200 pb-5">
          <h1 className="text-2xl font-semibold text-[#111827]" style={fontHeading}>
            Settings for {siteId}
          </h1>
        </div>

        <div className="mt-7 grid gap-6 lg:grid-cols-[230px_1fr]">
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <nav className="grid gap-1 text-sm" style={fontBody}>
              {[
                ["#general", "General"],
                ["#targets", "Performance targets"],
                ["#shields", "Shields"],
                ["#billing", "Plan & billing"],
                ["#imports", "Imports & exports"],
                ["#tracking-health", "Tracking health"],
              ].map(([href, label]) => (
                <a key={href} href={href} className="rounded px-3 py-2 text-gray-700 hover:bg-gray-100 hover:text-[#111827]">
                  {label}
                </a>
              ))}
            </nav>
          </aside>

          <div className="space-y-5">
            <section id="general" className="scroll-mt-6 space-y-5">
              <div className="border border-gray-200 bg-white p-5">
                <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                  General
                </div>
                <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                  Core site details, installation review, and dashboard access.
                </div>
              </div>

              <div className="border border-gray-200 bg-white p-5">
                <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                  Site domain
                </div>
                <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                  This is the dashboard site identifier used for reporting.
                </div>
                <input
                  className="mt-4 w-full max-w-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500"
                  style={fontBody}
                  value={siteId}
                  readOnly
                />
              </div>

              <div className="border border-gray-200 bg-white p-5">
                <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                  Site timezone
                </div>
                <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                  Update your reporting timezone.
                </div>
                <div className="mt-4 max-w-md">
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Reporting timezone
                  </label>
                  <select
                    aria-label="Reporting timezone"
                    className="mt-2 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={timezoneDraft}
                    onChange={(event) => setTimezoneDraft(event.target.value)}
                  >
                    {timezoneOptions.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void saveTimezone()}
                    disabled={!hasTimezoneChanges || timezoneStatus === "saving" || timezoneStatus === "loading"}
                    className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    Save timezone
                  </button>
                  <button
                    type="button"
                    onClick={() => setTimezoneDraft(timezone)}
                    disabled={!hasTimezoneChanges || timezoneStatus === "saving"}
                    className="border border-gray-300 bg-white px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                    style={fontBody}
                  >
                    Reset
                  </button>
                </div>
                <div className={`mt-2 text-[11px] ${timezoneStatusClassName}`} style={fontBody}>
                  {timezoneStatusText}
                </div>
              </div>

              <div className="border border-gray-200 bg-white p-5">
                <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                  Site installation
                </div>
                <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                  Control what data is collected and verify your installation.
                </div>
                <a
                  href="#tracking-health"
                  className="mt-5 inline-flex border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white hover:bg-[#3730a3]"
                  style={fontBody}
                >
                  Review installation
                </a>
              </div>

              <div className="border border-gray-200 bg-white p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                      Site access
                    </div>
                    <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                      Share this dashboard with existing Valid dashboard users.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void refreshSiteAccess()}
                    disabled={accessStatus === "loading" || accessStatus === "saving"}
                    className="border border-gray-300 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                    style={fontBody}
                  >
                    Refresh
                  </button>
                </div>
                <form className="mt-4 grid gap-2 md:grid-cols-[1fr_auto]" onSubmit={addSiteMember}>
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      Dashboard username
                    </label>
                    <input
                      className="mt-1 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                      style={fontBody}
                      value={accessUsername}
                      onChange={(event) => setAccessUsername(event.target.value)}
                      placeholder="username"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={accessStatus === "saving" || !accessUsername.trim()}
                    className="self-end border border-[#4f46e5] bg-[#4f46e5] px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    {accessStatus === "saving" ? "Saving..." : "Add user"}
                  </button>
                </form>
                {accessMessage ? (
                  <div className={`mt-2 text-[11px] ${accessStatus === "error" ? "text-[#8B2635]" : "text-gray-500"}`} style={fontBody}>
                    {accessMessage}
                  </div>
                ) : null}
                <div className="mt-4">
                  {accessStatus === "loading" ? (
                    <div className="text-[12px] text-gray-500" style={fontBody}>
                      Loading site access...
                    </div>
                  ) : accessMembers.length > 0 ? (
                    <div className="divide-y divide-gray-100 border border-[var(--color-border-subtle)] bg-[#FCFEFE]">
                      {accessMembers.map((member) => (
                        <div key={`${member.role}-${member.username}`} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                          <div>
                            <div className="text-sm text-[#1F2937]" style={fontBody}>
                              {member.username}
                            </div>
                            <div className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                              {member.role}
                              {member.created_at ? ` - added ${formatDateTime(member.created_at)}` : ""}
                            </div>
                          </div>
                          {member.role === "member" ? (
                            <button
                              type="button"
                              onClick={() => void removeSiteMember(member.username)}
                              disabled={accessStatus === "saving"}
                              className="border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                              style={fontBody}
                            >
                              Remove
                            </button>
                          ) : (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600" style={fontBody}>
                              Owner
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[12px] text-gray-500" style={fontBody}>
                      No access records loaded for this site.
                    </div>
                  )}
                </div>
              </div>
            </section>

            <section id="targets" className="scroll-mt-6 border border-gray-200 bg-white p-5">
              <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                Performance targets
              </div>
              <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                Set dashboard targets for the metrics you want to pace against.
              </div>
              <form className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]" onSubmit={submitGoal}>
                <div>
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Metric
                  </label>
                  <select
                    className="mt-1 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={goalMetric}
                    onChange={(event) => setGoalMetric(event.target.value as GoalMetric)}
                  >
                    {goalEligibleMetrics.map((metric) => (
                      <option key={metric} value={metric}>
                        {metricLabels[metric] ?? metric}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Target
                  </label>
                  <input
                    type="number"
                    min={0}
                    step={goalMetric === "revenue" ? "1" : "0.1"}
                    className="mt-1 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={goalTargetInput}
                    onChange={(event) => setGoalTargetInput(event.target.value)}
                    placeholder={goalMetric === "revenue" ? "10000" : "250"}
                  />
                </div>
                <button
                  type="submit"
                  className="self-end border border-[#4f46e5] bg-[#4f46e5] px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white hover:bg-[#3730a3]"
                  style={fontBody}
                >
                  Save target
                </button>
                <button
                  type="button"
                  onClick={clearGoal}
                  className="self-end border border-gray-300 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-gray-700 hover:border-gray-400"
                  style={fontBody}
                  disabled={!existingGoal}
                >
                  Remove
                </button>
              </form>
              {goalStatus && (
                <div className="mt-2 text-[12px] text-[#4B5563]" style={fontBody}>
                  {goalStatus}
                </div>
              )}
              <div className="mt-5">
                <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                  Configured targets
                </div>
                {sortedGoals.length > 0 ? (
                  <div className="mt-2 space-y-2">
                    {sortedGoals.map((goal) => (
                      <div
                        key={goal.metric}
                        className="flex items-center justify-between border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-2"
                      >
                        <div className="text-sm text-[#1F2937]" style={fontBody}>
                          {metricLabels[goal.metric] ?? goal.metric}
                        </div>
                        <div className="text-sm metric-number text-[#1F2937]" style={fontMetric}>
                          {formatMetricValue(goal.metric, goal.target)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-2 text-[12px] text-[#6B7280]" style={fontBody}>
                    No targets configured yet for this site.
                  </div>
                )}
              </div>
            </section>

            <section id="shields" className="scroll-mt-6 border border-gray-200 bg-white p-5">
              <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                Shields
              </div>
              <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                Exclude internal or known traffic before it is included in analytics.
              </div>
              <form className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={addIpBlock}>
                <div>
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    IP address or CIDR
                  </label>
                  <input
                    className="mt-1 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={ipBlockCidr}
                    onChange={(event) => setIpBlockCidr(event.target.value)}
                    placeholder="203.0.113.10 or 203.0.113.0/24"
                  />
                </div>
                <div>
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Label
                  </label>
                  <input
                    className="mt-1 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={ipBlockLabel}
                    onChange={(event) => setIpBlockLabel(event.target.value)}
                    placeholder="Office, agency, home"
                  />
                </div>
                <button
                  type="submit"
                  disabled={ipBlockStatus === "saving" || !ipBlockCidr.trim()}
                  className="self-end border border-[#4f46e5] bg-[#4f46e5] px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                  style={fontBody}
                >
                  {ipBlockStatus === "saving" ? "Saving..." : "Add block"}
                </button>
              </form>
              {ipBlockMessage ? (
                <div className={`mt-2 text-[11px] ${ipBlockStatus === "error" ? "text-[#8B2635]" : "text-gray-500"}`} style={fontBody}>
                  {ipBlockMessage}
                </div>
              ) : null}
              <div className="mt-4">
                {ipBlockStatus === "loading" ? (
                  <div className="text-[12px] text-gray-500" style={fontBody}>
                    Loading IP block list...
                  </div>
                ) : ipBlocks.length > 0 ? (
                  <div className="divide-y divide-gray-100 border border-[var(--color-border-subtle)] bg-[#FCFEFE]">
                    {ipBlocks.map((block) => (
                      <div key={block.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                        <div>
                          <div className="text-sm text-[#1F2937]" style={fontBody}>
                            {block.cidr}
                          </div>
                          <div className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                            {block.label || "Unlabeled"}
                            {block.created_at ? ` - added ${formatDateTime(block.created_at)}` : ""}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => void removeIpBlock(block.id)}
                          disabled={deletingIpBlockId === block.id}
                          className="border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                          style={fontBody}
                        >
                          {deletingIpBlockId === block.id ? "Removing..." : "Remove"}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[12px] text-[#6B7280]" style={fontBody}>
                    No IP blocks configured yet.
                  </div>
                )}
              </div>
            </section>

            <section id="billing" className="scroll-mt-6 border border-gray-200 bg-white p-5">
              <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                Plan & billing
              </div>
              <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                Manage this site's current plan.
              </div>
              <div className="mt-4 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                  Subscription
                </div>
                <div className="mt-2 text-sm text-[#1F2937]" style={fontBody}>
                  Current plan: <span className="font-semibold capitalize">{billingPlan}</span>
                </div>
                <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                  {billingStatusText}
                </div>
                <button
                  type="button"
                  onClick={() => void beginStandardCheckout()}
                  disabled={billingActionDisabled}
                  className="mt-3 border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                  style={fontBody}
                >
                  {billingActionLabel}
                </button>
              </div>
            </section>

            <section id="imports" className="scroll-mt-6 border border-gray-200 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                    Imports & exports
                  </div>
                  <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                    Import historical aggregate data for long-range trends and forecasts.
                  </div>
                </div>
                <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                  Standard only
                </div>
              </div>
              {canImportHistoricalData ? (
                <div className="mt-4 grid gap-3">
                  <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                    Import historical data
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      CSV file
                    </label>
                    <input
                      type="file"
                      accept=".csv,text/csv"
                      onChange={(event) => void handleImportFileChange(event)}
                      className="mt-1 block w-full text-sm text-[#1F2937] file:mr-3 file:border file:border-gray-300 file:bg-white file:px-3 file:py-1.5 file:text-[10px] file:font-semibold file:uppercase file:tracking-[0.14em] file:text-gray-700 hover:file:border-gray-400"
                      style={fontBody}
                    />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      CSV text
                    </label>
                    <textarea
                      className="mt-1 min-h-[120px] w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                      style={fontMeta}
                      value={importCsvText}
                      onChange={(event) => {
                        setImportCsvText(event.target.value);
                        setImportStatus("idle");
                        setImportMessage(null);
                      }}
                      placeholder={"day,metric,value\n2026-01-01,pageviews,1200\n2026-01-01,revenue,340.5"}
                    />
                    <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                      Required columns: day, metric, value. Metrics: pageviews, uniques, sessions, conversions, revenue.
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => void submitHistoricalImport()}
                      disabled={importStatus === "loading" || !importCsvText.trim()}
                      className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                      style={fontBody}
                    >
                      {importStatus === "loading" ? "Importing..." : "Import CSV"}
                    </button>
                    {importCsvText ? (
                      <button
                        type="button"
                        onClick={() => {
                          setImportCsvText("");
                          setImportStatus("idle");
                          setImportMessage(null);
                        }}
                        className="border border-gray-300 bg-white px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 hover:border-gray-400"
                        style={fontBody}
                      >
                        Clear
                      </button>
                    ) : null}
                  </div>
                  {importMessage ? (
                    <div className={`text-[11px] ${importStatusClassName}`} style={fontBody}>
                      {importMessage}
                    </div>
                  ) : null}
                  <div className="mt-3 border-t border-gray-100 pt-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                          Import history
                        </div>
                        <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                          Deleting an import removes only the imported rows and rebuilds the affected days.
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void refreshImportHistory()}
                        disabled={importHistoryStatus === "loading"}
                        className="border border-gray-300 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                        style={fontBody}
                      >
                        Refresh
                      </button>
                    </div>
                    {importHistoryStatus === "loading" ? (
                      <div className="mt-3 text-[11px] text-gray-500" style={fontBody}>
                        Loading import history...
                      </div>
                    ) : importHistoryStatus === "error" ? (
                      <div className="mt-3 text-[11px] text-[#8B2635]" style={fontBody}>
                        {importHistoryMessage ?? "Unable to load import history."}
                      </div>
                    ) : importBatches.length > 0 ? (
                      <div className="mt-3 overflow-x-auto">
                        <table className="w-full min-w-[720px] border-collapse text-left text-[12px]" style={fontBody}>
                          <thead className="text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                            <tr className="border-b border-gray-100">
                              <th className="py-2 pr-3 font-semibold">Import</th>
                              <th className="py-2 pr-3 font-semibold">Dates</th>
                              <th className="py-2 pr-3 font-semibold">Metrics</th>
                              <th className="py-2 pr-3 font-semibold">Rows</th>
                              <th className="py-2 pr-3 font-semibold">Status</th>
                              <th className="py-2 pr-3 font-semibold">Created</th>
                              <th className="py-2 pr-0 text-right font-semibold">Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {importBatches.map((batch) => (
                              <tr key={batch.id} className="border-b border-gray-100 last:border-b-0">
                                <td className="py-2 pr-3 metric-number text-[#1F2937]" style={fontMetric}>
                                  #{batch.id}
                                </td>
                                <td className="py-2 pr-3 text-gray-700">
                                  {batch.start_day && batch.end_day
                                    ? `${formatShortDate(batch.start_day)} - ${formatShortDate(batch.end_day)}`
                                    : "-"}
                                </td>
                                <td className="py-2 pr-3 text-gray-700">{batch.metrics.join(", ") || "-"}</td>
                                <td className="py-2 pr-3 metric-number text-gray-700" style={fontMetric}>
                                  {formatNumber(batch.imported_rows)}
                                </td>
                                <td className="py-2 pr-3">
                                  <span
                                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${statusToneClass(
                                      batch.status
                                    )}`}
                                    style={fontBody}
                                  >
                                    {batch.status.replace("_", " ")}
                                  </span>
                                  {batch.error ? (
                                    <div className="mt-1 max-w-[220px] truncate text-[10px] text-[#8B2635]" style={fontBody}>
                                      {batch.error}
                                    </div>
                                  ) : null}
                                </td>
                                <td className="py-2 pr-3 text-gray-600">{formatDateTime(batch.created_at)}</td>
                                <td className="py-2 pr-0 text-right">
                                  {batch.rollback_available ? (
                                    <button
                                      type="button"
                                      onClick={() => void deleteImport(batch.id)}
                                      disabled={deletingImportBatchId === batch.id}
                                      className="border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                                      style={fontBody}
                                    >
                                      {deletingImportBatchId === batch.id ? "Deleting..." : "Delete import"}
                                    </button>
                                  ) : (
                                    <span className="text-[10px] text-gray-400" style={fontBody}>
                                      Unavailable
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="mt-3 text-[11px] text-gray-500" style={fontBody}>
                        No historical imports recorded yet.
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="mt-4 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                  <div className="text-sm text-[#1F2937]" style={fontBody}>
                    {billingPlan === "free"
                      ? "Historical imports are available on Standard."
                      : "Historical imports are currently limited to Standard sites."}
                  </div>
                  <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                    {billingPlan === "free"
                      ? "Upgrade to bring in prior analytics data and use it for long-range trends and forecasts."
                      : "This import path uses Standard aggregate storage and is not available for the current plan."}
                  </div>
                  {billingPlan === "free" ? (
                    <button
                      type="button"
                      onClick={() => void beginStandardCheckout()}
                      disabled={billingActionDisabled}
                      className="mt-3 border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                      style={fontBody}
                    >
                      Upgrade to Standard
                    </button>
                  ) : null}
                </div>
              )}
            </section>

            <section id="tracking-health" className="scroll-mt-6 border border-gray-200 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                    Tracking health
                  </div>
                  <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                    Recent tracking, reduction, and forecast signals for this site.
                  </div>
                </div>
                {health ? (
                  <span
                    className={`rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${statusToneClass(
                      health.overall_status
                    )}`}
                    style={fontBody}
                  >
                    {health.overall_status}
                  </span>
                ) : null}
              </div>
              {healthStatus === "loading" ? (
                <div className="mt-4 text-[12px] text-gray-500" style={fontBody}>
                  Loading tracking health...
                </div>
              ) : healthStatus === "error" ? (
                <div className="mt-4 text-[12px] text-[#8B2635]" style={fontBody}>
                  {healthMessage ?? "Unable to load tracking health."}
                </div>
              ) : health ? (
                <div className="mt-4 grid gap-3 lg:grid-cols-[1.4fr_1fr]">
                  <div className="grid gap-2">
                    {health.checks.map((check) => (
                      <div key={check.key} className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                            {check.label}
                          </div>
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${statusToneClass(
                              check.status
                            )}`}
                            style={fontBody}
                          >
                            {check.status}
                          </span>
                        </div>
                        <div className="mt-1 text-[11px] text-gray-600" style={fontBody}>
                          {check.detail}
                        </div>
                        {check.action ? (
                          <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                            {check.action}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  <div className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                    <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      Last {health.lookback_minutes} minutes
                    </div>
                    <div className="mt-2 text-2xl metric-number text-[#1F2937]" style={fontMetric}>
                      {formatNumber(health.recent_reports)}
                    </div>
                    <div className="text-[11px] text-gray-500" style={fontBody}>
                      reports received
                    </div>
                    <div className="mt-3 space-y-1 text-[11px] text-gray-600" style={fontBody}>
                      <div>Last report: {formatDateTime(health.last_report_at)}</div>
                      <div>Active site keys: {formatNumber(health.active_site_keys)}</div>
                      <div>Latest reducer day: {health.latest_reducer_day ?? "-"}</div>
                      <div>Latest aggregate: {formatDateTime(health.latest_standard_published_at)}</div>
                    </div>
                    {Object.keys(health.counts_by_kind).length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-1">
                        {Object.entries(health.counts_by_kind).map(([kind, count]) => (
                          <span
                            key={kind}
                            className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-700"
                            style={fontBody}
                          >
                            {kind}: {formatNumber(count)}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {health.detected_hostnames.length > 0 ? (
                      <div className="mt-3 text-[11px] text-gray-500" style={fontBody}>
                        Hostnames: {health.detected_hostnames.join(", ")}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </section>
          </div>
        </div>
      </main>
    </div>
  );
};

const BillingSuccess: React.FC = () => {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");

  return (
    <div className="min-h-screen bg-[#F9FAFB] print-bg">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <a href="/" className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
            Valid
          </a>
          <LogoutButton />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-10 pt-10">
        <section className="border border-gray-200 bg-white p-6">
          <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
            Billing Confirmed
          </h1>
          <p className="mt-3 text-sm text-gray-700" style={fontBody}>
            Your subscription update was accepted. We have received the Stripe session and are syncing your site plan.
          </p>
          {sessionId ? (
            <p className="mt-3 text-xs text-gray-500" style={fontBody}>
              Session ID: <span className="meta-number" style={fontMeta}>{sessionId}</span>
            </p>
          ) : null}
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href="/"
              className="inline-flex items-center border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white"
              style={fontBody}
            >
              Open Dashboard
            </a>
            <a href="/settings" className="inline-flex items-center border border-gray-300 px-4 py-2 text-sm" style={fontBody}>
              Billing Settings
            </a>
          </div>
        </section>
      </main>
    </div>
  );
};

const BillingCancel: React.FC = () => (
  <div className="min-h-screen bg-[#F9FAFB] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <a href="/" className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
          Valid
        </a>
        <LogoutButton />
      </div>
    </header>
    <main className="mx-auto max-w-3xl px-6 pb-10 pt-10">
      <section className="border border-gray-200 bg-white p-6">
        <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
          Billing Update Canceled
        </h1>
        <p className="mt-3 text-sm text-gray-700" style={fontBody}>
          No change was made to your subscription. You can return anytime to retry checkout.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href="/"
            className="inline-flex items-center border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white"
            style={fontBody}
          >
            Back to Dashboard
          </a>
          <a href="/settings" className="inline-flex items-center border border-gray-300 px-4 py-2 text-sm" style={fontBody}>
            Review Billing
          </a>
        </div>
      </section>
    </main>
  </div>
);

const LoginGate: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-12">
        <section className="w-full border border-gray-200 bg-white p-6">
          <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
            Sign In
          </h1>
          <p className="mt-2 text-sm text-gray-600" style={fontBody}>
            Dashboard access is restricted.
          </p>
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                Username
              </label>
              <input
                type="text"
                aria-label="Username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="w-full border border-gray-300 px-3 py-2 text-sm text-[#111827]"
                style={fontBody}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                Password
              </label>
              <input
                type="password"
                aria-label="Password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full border border-gray-300 px-3 py-2 text-sm text-[#111827]"
                style={fontBody}
                required
              />
            </div>
            {error && (
              <p className="text-sm text-rose-600" style={fontBody}>
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-60"
              style={fontBody}
            >
              {isSubmitting ? "Signing in..." : "Sign In"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
};

const HomeRoute: React.FC = () => {
  const { token, authEnabled } = useAuth();
  const [searchParams] = useSearchParams();
  const querySiteId = searchParams.get("site_id")?.trim();
  const [availableSites, setAvailableSites] = useState<DashboardSiteSummary[] | null>(null);
  const [siteLoadError, setSiteLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!authEnabled || !token || querySiteId) {
      setAvailableSites(null);
      setSiteLoadError(null);
      return;
    }
    let cancelled = false;
    setAvailableSites(null);
    setSiteLoadError(null);
    fetchDashboardSites(token)
      .then((sites: DashboardSiteSummary[]) => {
        if (cancelled) return;
        setAvailableSites(sites);
      })
      .catch(() => {
        if (!cancelled) {
          setAvailableSites([]);
          setSiteLoadError("Unable to load dashboards for this login.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authEnabled, querySiteId, token]);

  if (!authEnabled || !token || querySiteId) {
    return <Overview />;
  }
  if (availableSites === null) {
    return <div className="p-6 text-sm text-gray-500">{en.loading}</div>;
  }
  if (availableSites.length === 1) {
    return <Navigate to={`/site/${encodeURIComponent(availableSites[0].site_id)}`} replace />;
  }
  return <SitePicker sites={availableSites} error={siteLoadError} />;
};

export const App: React.FC = () => {
  const { token, authEnabled, ready } = useAuth();
  useTheme();

  if (!ready) {
    return <div className="p-6 text-sm text-gray-500">{en.loading}</div>;
  }
  if (authEnabled && !token) {
    return <LoginGate />;
  }

  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true }}>
      <Suspense fallback={<div>{en.loading}</div>}>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/site/:siteId" element={<Overview />} />
          <Route path="/site/:siteId/charts" element={<SiteDashboardRedirect />} />
          <Route path="/site/:siteId/alerts" element={<SiteDashboardRedirect />} />
          <Route path="/site/:siteId/settings" element={<Settings />} />
          <Route path="/charts" element={<Navigate to="/" replace />} />
          <Route path="/alerts" element={<Navigate to="/" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/billing/success" element={<BillingSuccess />} />
          <Route path="/billing/cancel" element={<BillingCancel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
