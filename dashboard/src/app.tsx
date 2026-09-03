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
  BillingStatus,
  BreakdownDimension,
  BreakdownMetricKey,
  BreakdownResponse,
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
  fetchInsights,
  fetchMetrics,
  fetchImportHistory,
  fetchSegmentAggregate,
  fetchSiteAlertSettings,
  fetchSiteIpBlocks,
  fetchSiteAccess,
  fetchSiteHealth,
  fetchSiteSettings,
  ForecastEntry,
  ForecastResponse,
  createSiteIpBlock,
  deleteSiteGoal,
  grantSiteAccess,
  HistoricalImportBatch,
  HistoricalImportPreviewResponse,
  importHistoricalCsv,
  InsightItem,
  deleteSiteIpBlock,
  removeSiteAccess,
  previewHistoricalCsv,
  resolveActiveSiteId,
  rollbackImportBatch,
  fetchSiteGoals,
  SiteGoal,
  SiteAccessMember,
  SiteAlertSettings,
  SiteHealthResponse,
  SiteIpBlock,
  SdkInstallVerifyResponse,
  TimePartingDayType,
  updateSiteAlertSettings,
  updateSiteName,
  upsertSiteGoal,
  updateSiteTimezone,
  verifySdkInstall,
} from "./api";
import { GoalsProgressCard } from "./components/GoalsProgressCard";
import { KPIGrid } from "./components/KPIGrid";
import { CloseIcon, MoonIcon, SunIcon } from "./components/icons";
import { LogoutButton } from "./components/LogoutButton";
import { SitePicker } from "./components/SitePicker";
import { TableBlock } from "./components/TableBlock";
import { TimePartingHeatmap } from "./components/TimePartingHeatmap";
import {
  aggregateMetricKeys,
  engagementAggregateMetricKeys,
  breakdownDimensions,
  dayOfWeekLabels,
  ENABLE_DEMO_MODE,
  forecastOptions,
  goalEligibleMetrics,
  hourOfDayLabels,
  LAST_SITE_ID_STORAGE_KEY,
  metricLabels,
  MS_PER_DAY,
  rangeOptions,
  timezoneOptions,
} from "./constants";
import { useAuth } from "./hooks/useAuth";
import { useTheme } from "./hooks/useTheme";
import { BillingCancel, BillingSuccess } from "./routes/BillingStatusRoutes";
import { LoginGate } from "./routes/LoginGate";
import { fontBody, fontHeading, fontMeta, fontMetric } from "./styles/typography";
import type {
  ActiveFilter,
  BreakdownData,
  BreakdownErrorMap,
  BreakdownComparisonContext,
  BreakdownMetricTotals,
  BreakdownTableRow,
  ChartGranularity,
  ComparisonPoint,
  DailyValuePoint,
  DateRange,
  ForecastOption,
  GoalMetric,
  MetricGoal,
  RangeOption,
  SiteGoalsMap,
  TrendChartPoint,
} from "./types";
import {
  formatDailyPace,
  formatDuration,
  formatMetricValue,
  formatNumber,
  formatPercent,
  formatShortDate,
} from "./utils/format";
import { aggregateRowsByLabel, getBreakdownMetricValue, renderBreakdownLabel, renderFilterDimensionLabel } from "./utils/breakdowns";
import { buildSourceMediumLabel, classifyChannelLabel, normalizeSourceLabel } from "./utils/sourceAttribution";
import en from "./locales/en.json";

const mapServerGoals = (goals: SiteGoal[] = []): SiteGoalsMap =>
  goals.reduce<SiteGoalsMap>((acc, goal) => {
    const conversionType = goal.metric === "conversions" ? goal.conversion_type ?? null : null;
    acc[goalKey(goal.metric, conversionType)] = {
      metric: goal.metric,
      conversionType,
      target: goal.target,
      periodDays: goal.period_days,
      repeat: goal.repeat,
      updatedAt: goal.updated_at,
    };
    return acc;
  }, {});

const goalKey = (metric: GoalMetric | SiteGoal["metric"], conversionType?: string | null): string =>
  metric === "conversions" && conversionType ? `conversions:${conversionType}` : metric;

const goalLabel = (goal: Pick<MetricGoal, "metric" | "conversionType">): string =>
  goal.metric === "conversions" && goal.conversionType
    ? `Conversions · ${goal.conversionType}`
    : metricLabels[goal.metric] ?? goal.metric;

const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="mb-3">
    <div className="mb-3 h-0.5 w-11 rounded-full bg-[#4F46E5]" />
    <div className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#7B8190]" style={fontBody}>
      {children}
    </div>
  </div>
);

const settingsPanels = [
  { id: "general", label: "General" },
  { id: "targets", label: "Performance targets" },
  { id: "alerts", label: "Anomaly alerts" },
  { id: "shields", label: "Shields" },
  { id: "billing", label: "Plan & billing" },
  { id: "imports", label: "Imports & exports" },
] as const;

type SettingsPanel = (typeof settingsPanels)[number]["id"];

const isSettingsPanel = (value: string): value is SettingsPanel => settingsPanels.some((panel) => panel.id === value);

const titleCaseSiteName = (value: string): string =>
  value
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => {
      if (/^[A-Z0-9]{2,}$/.test(part)) return part;
      return `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`;
    })
    .join(" ");

const fallbackSiteDisplayName = (siteId: string): string => {
  const cleaned = siteId
    .replace(/^live[-_]/i, "")
    .replace(/[-_](com|org|net|io|co|app|dev)$/i, "")
    .replace(/\.(com|org|net|io|co|app|dev)$/i, "")
    .replace(/[-_.]+/g, " ")
    .trim();
  return cleaned ? titleCaseSiteName(cleaned) : siteId;
};

const dashboardSiteDisplayName = (siteId: string, siteName?: string | null): string => {
  const trimmed = siteName?.trim();
  if (trimmed && trimmed !== siteId) return trimmed;
  return fallbackSiteDisplayName(siteId);
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

const formatRelativeTime = (value?: string | null): string => {
  if (!value) return "recently";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "recently";
  const diffMs = Date.now() - timestamp;
  if (diffMs < 60_000) return "just now";
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDateTime(value);
};

type ErrorBoundaryState = {
  hasError: boolean;
};

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: unknown) {
    console.error("Dashboard render error", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="min-h-screen bg-[#F9FAFB] px-6 py-10">
        <div className="mx-auto max-w-xl rounded-lg border border-[var(--color-border-subtle)] bg-white p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="text-lg font-semibold text-[#111827]" style={fontHeading}>
            Something went wrong
          </div>
          <div className="mt-2 text-sm leading-6 text-[#4B5563]" style={fontBody}>
            The dashboard hit an unexpected display issue. Reloading usually clears it; if it happens again, the API response probably needs review.
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 rounded-md border border-[#4f46e5] bg-[#4f46e5] px-3 py-2 text-sm font-semibold text-white hover:bg-[#3730a3]"
            style={fontBody}
          >
            Reload dashboard
          </button>
        </div>
      </div>
    );
  }
}

const DashboardLoadingSkeleton: React.FC<{ label?: string }> = ({ label = "Loading dashboard" }) => (
  <div className="min-h-screen bg-[#F9FAFB] px-5 py-6 sm:px-8" role="status" aria-live="polite">
    <div className="mx-auto max-w-[1180px] animate-pulse space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="h-7 w-20 rounded bg-[#E5E7EB]" />
          <div className="mt-3 h-3 w-56 rounded bg-[#E5E7EB]" />
        </div>
        <div className="hidden gap-2 sm:flex">
          <div className="h-8 w-20 rounded bg-[#E5E7EB]" />
          <div className="h-8 w-28 rounded bg-[#E5E7EB]" />
          <div className="h-8 w-20 rounded bg-[#E5E7EB]" />
        </div>
      </div>
      <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-[var(--color-border-subtle)] bg-white md:grid-cols-4 xl:grid-cols-8">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="border-b border-r border-[var(--color-border-subtle)] px-4 py-4 xl:border-b-0">
            <div className="h-3 w-20 rounded bg-[#EEF2F7]" />
            <div className="mt-3 h-6 w-16 rounded bg-[#E5E7EB]" />
            <div className="mt-2 h-3 w-24 rounded bg-[#EEF2F7]" />
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-[var(--color-border-subtle)] bg-white p-5">
        <div className="h-5 w-32 rounded bg-[#E5E7EB]" />
        <div className="mt-8 h-[260px] rounded bg-[#F1F3F6]" />
      </div>
    </div>
    <span className="sr-only">{label}</span>
  </div>
);

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

const formatInsightPercent = (value: number, digits = 1): string => {
  if (!Number.isFinite(value)) return "—";
  const pct = value * 100;
  const rounded = Number(pct.toFixed(digits));
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(digits)}%`;
};

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

const deriveBounceRate = (bouncedSessions: number, sessions: number) => {
  if (!Number.isFinite(bouncedSessions) || !Number.isFinite(sessions) || sessions <= 0) return Number.NaN;
  return clamp(bouncedSessions / sessions, 0, 1);
};

const parseDay = (day: string) => new Date(`${day}T00:00:00`);
const formatIsoDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

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

const createEmptyBreakdownData = (
  primaryMetric: BreakdownMetricKey,
  metricKeys: BreakdownMetricKey[] = [primaryMetric]
): BreakdownData => ({
  rows: [],
  total: 0,
  primaryMetric,
  metricKeys,
  totalsByMetric: {},
});

const createEmptyBreakdownMap = (): Record<BreakdownDimension, BreakdownData> => ({
  channels: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  sources: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  source_medium: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  campaign: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  content: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  term: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  pages: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews"]),
  devices: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
  countries: createEmptyBreakdownData("pageviews", ["uniques", "sessions", "pageviews", "conversions"]),
  conversions: createEmptyBreakdownData("conversions", ["uniques", "sessions", "conversions"]),
  hour_of_day: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  day_of_week: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
  hostnames: createEmptyBreakdownData("sessions", ["uniques", "sessions", "pageviews", "conversions"]),
});

const breakdownResponseToData = (response: BreakdownResponse): BreakdownData => ({
  rows: response.rows.map((row: BreakdownRow) => ({
    label: row.label,
    metrics: row.metrics ?? {},
  })),
  total: response.total ?? 0,
  primaryMetric: response.primary_metric,
  metricKeys: response.metric_keys ?? [response.primary_metric],
  totalsByMetric: response.totals ?? {},
});

const breakdownSectionLabels: Record<BreakdownDimension, string> = {
  channels: "Channels",
  sources: "Traffic sources",
  source_medium: "Source / medium",
  campaign: "Campaigns",
  content: "Campaign content",
  term: "Campaign terms",
  pages: "Top pages",
  devices: "Devices",
  countries: "Countries",
  conversions: "Goal completions",
  hour_of_day: "Hourly arrivals",
  day_of_week: "Day-of-week arrivals",
  hostnames: "Hostnames",
};

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
    bounced_sessions: [] as { day: string; value: number }[],
    visit_duration_seconds: [] as { day: string; value: number }[],
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
    const bouncedSessions = Math.max(0, Math.round(sessions * 0.44));

    seeded.pageviews.push({ day, value: pageviews });
    seeded.uniques.push({ day, value: uniques });
    seeded.sessions.push({ day, value: sessions });
    seeded.conversions.push({ day, value: conversions });
    seeded.revenue.push({ day, value: revenue });
    seeded.visit_duration.push({ day, value: visitDuration });
    seeded.bounced_sessions.push({ day, value: bouncedSessions });
    seeded.visit_duration_seconds.push({ day, value: visitDuration * sessions });
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
    return m && metricLabels[m] ? m : "uniques";
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
  const [forecastMeta, setForecastMeta] = useState<Pick<ForecastResponse, "has_anomaly" | "trained_at"> | null>(
    null
  );
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [dashboardNotes, setDashboardNotes] = useState<DashboardNote[]>([]);
  const [noteDate, setNoteDate] = useState<string>("");
  const [noteBody, setNoteBody] = useState<string>("");
  const [noteStatus, setNoteStatus] = useState<string | null>(null);
  const [isSavingNote, setIsSavingNote] = useState(false);
  const [isNoteComposerOpen, setIsNoteComposerOpen] = useState(false);
  const [hoveredNoteMarkerDay, setHoveredNoteMarkerDay] = useState<string | null>(null);
  const [selectedNoteMarkerDay, setSelectedNoteMarkerDay] = useState<string | null>(null);
  const [aggregateMap, setAggregateMap] = useState<Record<string, AggregateWindow[]>>({});
  const [kpiError, setKpiError] = useState<string | null>(null);
  const [metricAnomalies, setMetricAnomalies] = useState<Record<string, boolean>>({});
  const [remoteInsights, setRemoteInsights] = useState<InsightItem[]>([]);
  const [remoteInsightsStatus, setRemoteInsightsStatus] = useState<"fallback" | "loading" | "loaded" | "error">("fallback");
  const [breakdownData, setBreakdownData] = useState<Record<BreakdownDimension, BreakdownData>>(() => createEmptyBreakdownMap());
  const [comparisonBreakdownData, setComparisonBreakdownData] = useState<Record<BreakdownDimension, BreakdownData>>(() =>
    createEmptyBreakdownMap()
  );
  const [comparisonBreakdownsReady, setComparisonBreakdownsReady] = useState(false);
  const [breakdownErrors, setBreakdownErrors] = useState<BreakdownErrorMap>({});
  const [hostnameOptions, setHostnameOptions] = useState<string[]>([]);
  const [hostnameError, setHostnameError] = useState<string | null>(null);
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
  const segmentAggregateFilters = useMemo(() => {
    const filters = activeFilters.map((filter) => ({ dimension: filter.dimension, value: filter.value }));
    if (activeFilters.length > 0 && hostnameFilter) filters.push({ dimension: "hostname", value: hostnameFilter });
    return filters;
  }, [activeFilters, hostnameFilter]);
  const useSegmentAggregates = !showSeededBreakdowns && activeFilters.length > 0;
  const [siteName, setSiteName] = useState<string | null>(null);
  const siteDisplayName = useMemo(() => dashboardSiteDisplayName(siteId, siteName), [siteId, siteName]);
  const selectedRangeBounds = useMemo(
    () => resolveRangeBounds(range, customRange, siteTimezone),
    [range, customRange.start, customRange.end, siteTimezone]
  );
  const aggregateFetchBounds = useMemo(() => {
    const primary = selectedRangeBounds ?? resolveRangeBounds("Last 30", { start: "", end: "" }, siteTimezone);
    if (!primary) return null;

    const ranges: DateRange[] = [primary];
    const primaryStart = parseDay(primary.start);
    const primaryEnd = parseDay(primary.end);
    const diffDays = Math.max(1, Math.round(Math.abs(primaryEnd.getTime() - primaryStart.getTime()) / MS_PER_DAY) + 1);
    const previousEnd = new Date(primaryStart);
    previousEnd.setDate(previousEnd.getDate() - 1);
    const previousStart = new Date(previousEnd);
    previousStart.setDate(previousStart.getDate() - (diffDays - 1));
    ranges.push({ start: formatIsoDate(previousStart), end: formatIsoDate(previousEnd) });

    if (compareEnabled && compareMode === "custom" && compareRange.start && compareRange.end) {
      const compareStart = parseDay(compareRange.start);
      const compareEnd = parseDay(compareRange.end);
      ranges.push(
        compareStart <= compareEnd
          ? { start: compareRange.start, end: compareRange.end }
          : { start: compareRange.end, end: compareRange.start }
      );
    }

    return {
      start: ranges.reduce((min, item) => (item.start < min ? item.start : min), ranges[0].start),
      end: ranges.reduce((max, item) => (item.end > max ? item.end : max), ranges[0].end),
    };
  }, [
    selectedRangeBounds,
    siteTimezone,
    compareEnabled,
    compareMode,
    compareRange.start,
    compareRange.end,
  ]);

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
    if (!canQuery || showSeededBreakdowns) {
      setSiteName(null);
      return;
    }
    let cancelled = false;
    fetchDashboardSites(token ?? undefined)
      .then((sites) => {
        if (cancelled) return;
        setSiteName(sites.find((site) => site.site_id === siteId)?.site_name ?? null);
      })
      .catch(() => {
        if (!cancelled) setSiteName(null);
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, showSeededBreakdowns, siteId, token]);

  useEffect(() => {
    if (!canQuery) {
      setSiteGoals({});
      return;
    }
    let cancelled = false;
    fetchSiteGoals(token ?? undefined, siteId)
      .then((result) => {
        if (!cancelled) setSiteGoals(mapServerGoals(result.goals));
      })
      .catch(() => {
        if (!cancelled) setSiteGoals({});
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, siteId, token]);

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
    if (!canQuery || !aggregateFetchBounds) {
      setKpiError(null);
      setAggregateMap({});
      return;
    }
    let cancelled = false;
    setKpiError(null);
    const metricsToFetch = [...aggregateMetricKeys, ...engagementAggregateMetricKeys];
    Promise.all(
      metricsToFetch.map((metric) =>
        (useSegmentAggregates
          ? fetchSegmentAggregate(
              metric,
              "standard",
              segmentAggregateFilters,
              token ?? undefined,
              siteId,
              aggregateFetchBounds.start,
              aggregateFetchBounds.end
            )
          : fetchAggregate(
              metric,
              "standard",
              token ?? undefined,
              siteId,
              hostnameFilter,
              aggregateFetchBounds.start,
              aggregateFetchBounds.end
            )
        ).then((data) => ({
          metric,
          data,
        }))
      )
    )
      .then((results) => {
        if (cancelled) return;
        setKpiError(null);
        const next: Record<string, AggregateWindow[]> = {};
        results.forEach((item) => {
          next[item.metric] = item.data;
        });
        setAggregateMap(next);
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        if (!cancelled) {
          setAggregateMap({});
          setKpiError(message ?? "Unable to load metrics right now.");
        }
        console.error(error);
      });
    return () => {
      cancelled = true;
    };
  }, [
    canQuery,
    token,
    siteId,
    hostnameFilter,
    aggregateFetchBounds?.start,
    aggregateFetchBounds?.end,
    useSegmentAggregates,
    segmentAggregateFilters,
  ]);

  useEffect(() => {
    if (!aggregateMetricKeys.includes(selectedMetric as (typeof aggregateMetricKeys)[number])) {
      setForecast([]);
      setForecastMeta(null);
      setForecastError(null);
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
      setForecastMeta({ has_anomaly: false, trained_at: new Date().toISOString() });
      setForecastError(null);
      return;
    }
    if (!canQuery) return;
    setForecastError(null);
    fetchForecast(token ?? undefined, selectedMetric, siteId)
      .then((data) => {
        setForecast(data.forecast);
        setForecastMeta({ has_anomaly: data.has_anomaly, trained_at: data.trained_at ?? null });
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        setForecast([]);
        setForecastMeta({ has_anomaly: false, trained_at: null });
        setForecastError(message ?? "Unable to load the current forecast.");
        console.error(error);
      });
  }, [canQuery, token, selectedMetric, siteId, showSeededBreakdowns]);

  // Per-metric anomaly flags (range-independent) so the Insights card can surface
  // anomalies on metrics the user isn't currently viewing.
  useEffect(() => {
    if (!canQuery || showSeededBreakdowns) {
      setMetricAnomalies({});
      return;
    }
    let cancelled = false;
    fetchMetrics(token ?? undefined, siteId)
      .then((stats) => {
        if (cancelled) return;
        const next: Record<string, boolean> = {};
        stats.forEach((stat) => {
          next[stat.metric] = Boolean(stat.has_anomaly);
        });
        setMetricAnomalies(next);
      })
      .catch((error) => {
        if (!cancelled) setMetricAnomalies({});
        console.error(error);
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, showSeededBreakdowns, token, siteId]);

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
    const isCountMetric = [
      "pageviews",
      "uniques",
      "sessions",
      "conversions",
      "revenue",
      "bounced_sessions",
      "visit_duration_seconds",
    ].includes(metric);
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
  const bouncedSessionsAll = useMemo(
    () => (showSeededBreakdowns ? seededSeries.bounced_sessions : toDaily(aggregateMap.bounced_sessions ?? [])),
    [showSeededBreakdowns, seededSeries.bounced_sessions, aggregateMap, siteTimezone]
  );
  const visitDurationSecondsAll = useMemo(
    () =>
      showSeededBreakdowns
        ? seededSeries.visit_duration_seconds
        : toDaily(aggregateMap.visit_duration_seconds ?? []),
    [showSeededBreakdowns, seededSeries.visit_duration_seconds, aggregateMap, siteTimezone]
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
  const dailyBouncedSessions = useMemo(
    () => maybeFillMissingDailyZeros("bounced_sessions", filterByRange(bouncedSessionsAll, range, customRange), range, customRange),
    [bouncedSessionsAll, range, customRange, observedCountDayList]
  );
  const dailyVisitDurationSeconds = useMemo(
    () =>
      maybeFillMissingDailyZeros(
        "visit_duration_seconds",
        filterByRange(visitDurationSecondsAll, range, customRange),
        range,
        customRange
      ),
    [visitDurationSecondsAll, range, customRange, observedCountDayList]
  );
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
    const bouncedSessionsMap = mapByDay(bouncedSessionsAll);
    const sessionsMap = mapByDay(sessionsAll);
    const days = Array.from(new Set([...sessionsMap.keys(), ...bouncedSessionsMap.keys()])).sort((a, b) =>
      a.localeCompare(b)
    );
    return makeDerivedSeries(days, (day) =>
      deriveBounceRate(bouncedSessionsMap.get(day) ?? Number.NaN, sessionsMap.get(day) ?? Number.NaN)
    );
  }, [bouncedSessionsAll, sessionsAll]);

  const dailyBounceRate = useMemo(() => filterByRange(bounceRateAll, range, customRange), [bounceRateAll, range, customRange]);

  const visitDurationAll = useMemo(() => {
    const durationSecondsMap = mapByDay(visitDurationSecondsAll);
    const sessionsMap = mapByDay(sessionsAll);
    const days = Array.from(new Set([...durationSecondsMap.keys(), ...sessionsMap.keys()])).sort((a, b) =>
      a.localeCompare(b)
    );
    return makeDerivedSeries(days, (day) =>
      safeRatio(durationSecondsMap.get(day) ?? Number.NaN, sessionsMap.get(day) ?? Number.NaN)
    );
  }, [visitDurationSecondsAll, sessionsAll]);

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
      case "bounced_sessions":
        return dailyBouncedSessions;
      case "visit_duration_seconds":
        return dailyVisitDurationSeconds;
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
      case "bounced_sessions":
        return bouncedSessionsAll;
      case "visit_duration_seconds":
        return visitDurationSecondsAll;
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
      setHostnameError(null);
      return;
    }
    const start = breakdownDateRange?.start;
    const end = breakdownDateRange?.end;
    setHostnameError(null);
    fetchBreakdown("hostnames", token ?? undefined, siteId, start, end, 50)
      .then((response) => {
        setHostnameError(null);
        const options = response.rows
          .map((row) => row.label)
          .filter((label) => label && label !== "Unknown");
        setHostnameOptions(options);
      })
      .catch((error) => {
        const message = extractApiErrorMessage(error);
        setHostnameError(message ?? "Unable to load hostname filter options right now.");
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
      setBreakdownData(createEmptyBreakdownMap());
      setBreakdownErrors({});
      return;
    }

    let cancelled = false;
    const start = breakdownDateRange?.start;
    const end = breakdownDateRange?.end;
    setBreakdownErrors({});
    Promise.allSettled(
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
        const next = createEmptyBreakdownMap();
        const nextErrors: BreakdownErrorMap = {};
        results.forEach((result, index) => {
          const dimension = breakdownDimensions[index];
          if (result.status === "rejected") {
            const message = extractApiErrorMessage(result.reason);
            nextErrors[dimension] = message ?? `Unable to load ${breakdownSectionLabels[dimension].toLowerCase()} right now.`;
            return;
          }
          next[result.value.dimension] = breakdownResponseToData(result.value.response);
        });
        setBreakdownData(next);
        setBreakdownErrors(nextErrors);
        results.forEach((result) => {
          if (result.status === "rejected") console.error(result.reason);
        });
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
    bouncedSessions: { day: string; value: number }[];
    visitDurationSeconds: { day: string; value: number }[];
  }) => {
    const pageviews = series.pageviews.reduce((sum, row) => sum + row.value, 0);
    const uniques = series.uniques.reduce((sum, row) => sum + row.value, 0);
    const sessions = series.sessions.reduce((sum, row) => sum + row.value, 0);
    const conversions = series.conversions.reduce((sum, row) => sum + row.value, 0);
    const revenue = series.revenue.reduce((sum, row) => sum + row.value, 0);
    const bouncedSessions = series.bouncedSessions.reduce((sum, row) => sum + row.value, 0);
    const visitDurationSeconds = series.visitDurationSeconds.reduce((sum, row) => sum + row.value, 0);
    const avgPagesPerVisit = safeRatio(pageviews, sessions);
    const bounceRate = series.bouncedSessions.length > 0 ? deriveBounceRate(bouncedSessions, sessions) : Number.NaN;
    const visitDuration =
      series.visitDurationSeconds.length > 0 ? safeRatio(visitDurationSeconds, sessions) : Number.NaN;
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
    bouncedSessions: dailyBouncedSessions,
    visitDurationSeconds: dailyVisitDurationSeconds,
  });
  const scaledTotals = totals;
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

  useEffect(() => {
    if (!canQuery || showSeededBreakdowns || !compareEnabled || !comparisonBounds) {
      setComparisonBreakdownData(createEmptyBreakdownMap());
      setComparisonBreakdownsReady(false);
      return;
    }

    let cancelled = false;
    setComparisonBreakdownsReady(false);
    Promise.allSettled(
      breakdownDimensions.map((dimension) =>
        fetchBreakdown(
          dimension,
          token ?? undefined,
          siteId,
          comparisonBounds.start,
          comparisonBounds.end,
          dimension === "hour_of_day" ? 24 : dimension === "day_of_week" ? 7 : 50,
          hostnameFilter,
          dimension === "hour_of_day" || dimension === "day_of_week" ? timePartingDayType : undefined
        ).then((response) => ({
          dimension,
          response,
        }))
      )
    ).then((results) => {
      if (cancelled) return;
      const next = createEmptyBreakdownMap();
      results.forEach((result) => {
        if (result.status === "rejected") {
          console.error(result.reason);
          return;
        }
        next[result.value.dimension] = breakdownResponseToData(result.value.response);
      });
      setComparisonBreakdownData(next);
      setComparisonBreakdownsReady(true);
    });

    return () => {
      cancelled = true;
    };
  }, [
    canQuery,
    showSeededBreakdowns,
    compareEnabled,
    comparisonBounds,
    token,
    siteId,
    hostnameFilter,
    timePartingDayType,
  ]);

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
    const isCountMetric = [
      "pageviews",
      "uniques",
      "sessions",
      "conversions",
      "revenue",
      "bounced_sessions",
      "visit_duration_seconds",
    ].includes(metric);
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
        bouncedSessions: getComparisonSeries("bounced_sessions"),
        visitDurationSeconds: getComparisonSeries("visit_duration_seconds"),
      })
    : null;
  const previousTotals = previousBounds
    ? computeKpiValues({
        pageviews: getSeriesForBounds("pageviews", previousBounds),
        uniques: getSeriesForBounds("uniques", previousBounds),
        sessions: getSeriesForBounds("sessions", previousBounds),
        conversions: getSeriesForBounds("conversions", previousBounds),
        revenue: getSeriesForBounds("revenue", previousBounds),
        bouncedSessions: getSeriesForBounds("bounced_sessions", previousBounds),
        visitDurationSeconds: getSeriesForBounds("visit_duration_seconds", previousBounds),
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
  const comparisonContextFor = useCallback(
    (
      rows: BreakdownTableRow[],
      total: number,
      totalsByMetric: BreakdownMetricTotals
    ): BreakdownComparisonContext | null => {
      if (!compareEnabled || !comparisonBounds || !comparisonRangeLabel || !comparisonBreakdownsReady) return null;
      return {
        rows,
        total,
        totalsByMetric,
        currentLabel: currentRangeLabel ?? range,
        comparisonLabel: comparisonRangeLabel,
      };
    },
    [compareEnabled, comparisonBounds, comparisonRangeLabel, comparisonBreakdownsReady, currentRangeLabel, range]
  );
  const insightComparisonBounds = comparisonBounds ?? previousBounds;
  useEffect(() => {
    if (
      !canQuery ||
      showSeededBreakdowns ||
      !primaryRangeBounds ||
      hostnameFilter ||
      activeFilters.length > 0
    ) {
      setRemoteInsights([]);
      setRemoteInsightsStatus("fallback");
      return;
    }
    let cancelled = false;
    setRemoteInsightsStatus("loading");
    fetchInsights(
      token ?? undefined,
      siteId,
      selectedMetric,
      primaryRangeBounds.start,
      primaryRangeBounds.end,
      insightComparisonBounds?.start,
      insightComparisonBounds?.end
    )
      .then((response) => {
        if (!cancelled) {
          setRemoteInsights(response.insights ?? []);
          setRemoteInsightsStatus("loaded");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setRemoteInsights([]);
          setRemoteInsightsStatus("error");
          console.error(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    canQuery,
    showSeededBreakdowns,
    token,
    siteId,
    selectedMetric,
    primaryRangeBounds?.start,
    primaryRangeBounds?.end,
    insightComparisonBounds?.start,
    insightComparisonBounds?.end,
    hostnameFilter,
    activeFilters.length,
  ]);
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
    () => {
      if (useSegmentAggregates) return [];
      return forecastHorizon.filter((entry) => {
        if (hasTodayActual) return entry.day >= todayKey;
        if (!lastActualDay) return true;
        return entry.day > lastActualDay;
      });
    },
    [forecastHorizon, hasTodayActual, todayKey, lastActualDay, useSegmentAggregates]
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
    return kpiComparisonValues;
  }, [kpiComparisonValues]);

  // Auto-select chart granularity. Only metrics whose daily values are safely additive
  // roll up to week/month; visitors and rate/average metrics stay daily.
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

  const chartData = bucketedChartData;
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
  const hasCurrentForecastRows = forecast.length > 0;
  const forecastMutedNote = useSegmentAggregates
    ? "Forecasts are site-level. Clear the segment to view the forecast."
    : hasCurrentForecastRows
      ? "Forecast unavailable in selected date range."
      : "Forecast building - needs about 60 complete days of history.";
  const forecastFreshnessText = hasForecast
    ? forecastMeta?.trained_at
      ? `Updated ${formatRelativeTime(forecastMeta.trained_at)}`
      : "Updated recently"
    : "Forecast building";
  const forecastFreshnessDetail = hasForecast
    ? forecastMeta?.trained_at
      ? `Last trained ${formatDateTime(forecastMeta.trained_at)}`
      : "Fresh forecast returned by the API."
    : "Valid will show forecasts here after enough complete daily history has been reduced.";
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
  const comparisonSourceRows = useMemo(
    () =>
      showSeededBreakdowns
        ? []
        : comparisonBreakdownData.sources.rows.map((row) => ({ ...row, label: normalizeSourceLabel(row.label) })),
    [showSeededBreakdowns, comparisonBreakdownData.sources.rows]
  );
  const channelRows = useMemo(
    () =>
      showSeededBreakdowns
        ? aggregateRowsByLabel(
            sourceRows.map((row) => ({
              label: classifyChannelLabel(row.label),
              metrics: row.metrics,
            }))
          )
        : breakdownData.channels.rows,
    [showSeededBreakdowns, sourceRows, breakdownData.channels.rows]
  );
  const comparisonChannelRows = useMemo(
    () =>
      showSeededBreakdowns
        ? aggregateRowsByLabel(
            comparisonSourceRows.map((row) => ({
              label: classifyChannelLabel(row.label),
              metrics: row.metrics,
            }))
          )
        : comparisonBreakdownData.channels.rows,
    [showSeededBreakdowns, comparisonSourceRows, comparisonBreakdownData.channels.rows]
  );
  const sourceMediumRows = useMemo(
    () =>
      showSeededBreakdowns
        ? aggregateRowsByLabel(
            sourceRows.map((row) => ({
              label: buildSourceMediumLabel(row.label),
              metrics: row.metrics,
            }))
          )
        : breakdownData.source_medium.rows,
    [showSeededBreakdowns, sourceRows, breakdownData.source_medium.rows]
  );
  const comparisonSourceMediumRows = useMemo(
    () =>
      showSeededBreakdowns
        ? aggregateRowsByLabel(
            comparisonSourceRows.map((row) => ({
              label: buildSourceMediumLabel(row.label),
              metrics: row.metrics,
            }))
          )
        : comparisonBreakdownData.source_medium.rows,
    [showSeededBreakdowns, comparisonSourceRows, comparisonBreakdownData.source_medium.rows]
  );
  const campaignRows = useMemo(() => {
    if (!showSeededBreakdowns) return breakdownData[campaignDimension].rows;
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
  }, [showSeededBreakdowns, campaignDimension, seededBreakdownTotals, breakdownData]);
  const comparisonCampaignRows = useMemo(
    () => (showSeededBreakdowns ? ([] as BreakdownTableRow[]) : comparisonBreakdownData[campaignDimension].rows),
    [showSeededBreakdowns, comparisonBreakdownData, campaignDimension]
  );
  const acquisitionRows = useMemo(() => {
    if (acquisitionTab === "sources") return sourceRows;
    if (acquisitionTab === "source_medium") return sourceMediumRows;
    if (acquisitionTab === "campaigns") return campaignRows;
    return channelRows;
  }, [acquisitionTab, sourceRows, sourceMediumRows, campaignRows, channelRows]);
  const acquisitionComparisonRows = useMemo(() => {
    if (acquisitionTab === "sources") return comparisonSourceRows;
    if (acquisitionTab === "source_medium") return comparisonSourceMediumRows;
    if (acquisitionTab === "campaigns") return comparisonCampaignRows;
    return comparisonChannelRows;
  }, [acquisitionTab, comparisonSourceRows, comparisonSourceMediumRows, comparisonCampaignRows, comparisonChannelRows]);
  const acquisitionBackendDimension: BreakdownDimension = acquisitionTab === "campaigns" ? campaignDimension : acquisitionTab;
  const acquisitionBreakdownData = breakdownData[acquisitionBackendDimension];
  const acquisitionComparisonBreakdownData = comparisonBreakdownData[acquisitionBackendDimension];
  const acquisitionMetricKeys = showSeededBreakdowns
    ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
    : acquisitionBreakdownData.metricKeys;
  const acquisitionPrimaryMetric = showSeededBreakdowns
    ? ("sessions" as BreakdownMetricKey)
    : acquisitionBreakdownData.primaryMetric;
  const acquisitionTotal = showSeededBreakdowns ? scaledTotals.sessions : acquisitionBreakdownData.total;
  const acquisitionTotalsByMetric = showSeededBreakdowns ? seededBreakdownTotals : acquisitionBreakdownData.totalsByMetric;
  const acquisitionComparisonTotal = acquisitionComparisonBreakdownData.total;
  const acquisitionComparisonTotalsByMetric = acquisitionComparisonBreakdownData.totalsByMetric;
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
  const comparisonPageRows = showSeededBreakdowns ? [] : comparisonBreakdownData.pages.rows;
  const deviceRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildMetricRows(["Mobile", "Desktop", "Tablet"], [0.58, 0.34, 0.08], seededBreakdownTotals)
        : breakdownData.devices.rows,
    [showSeededBreakdowns, seededBreakdownTotals, breakdownData.devices.rows]
  );
  const comparisonDeviceRows = showSeededBreakdowns ? [] : comparisonBreakdownData.devices.rows;
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
  const comparisonCountryRows = showSeededBreakdowns ? [] : comparisonBreakdownData.countries.rows;
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
  const comparisonGoalRows = showSeededBreakdowns ? [] : comparisonBreakdownData.conversions.rows;
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
        error: showSeededBreakdowns ? null : breakdownErrors.pages ?? null,
        dimension: "page",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.pages.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews"] as BreakdownMetricKey[])
          : breakdownData.pages.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.pages.total,
        totalsByMetric: showSeededBreakdowns
          ? ({ uniques: scaledTotals.uniques, sessions: scaledTotals.sessions, pageviews: scaledTotals.pageviews } as BreakdownMetricTotals)
          : breakdownData.pages.totalsByMetric,
        comparison: comparisonContextFor(
          comparisonPageRows,
          comparisonBreakdownData.pages.total,
          comparisonBreakdownData.pages.totalsByMetric
        ),
      },
      {
        title: "Countries",
        rows: countryRows,
        empty: "No country data yet for the selected range.",
        error: showSeededBreakdowns ? null : breakdownErrors.countries ?? null,
        dimension: "country",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.countries.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
          : breakdownData.countries.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.countries.total,
        totalsByMetric: showSeededBreakdowns ? seededBreakdownTotals : breakdownData.countries.totalsByMetric,
        comparison: comparisonContextFor(
          comparisonCountryRows,
          comparisonBreakdownData.countries.total,
          comparisonBreakdownData.countries.totalsByMetric
        ),
      },
      {
        title: "Devices",
        rows: deviceRows,
        empty: "No device data yet for the selected range.",
        error: showSeededBreakdowns ? null : breakdownErrors.devices ?? null,
        dimension: "device",
        primaryMetric: showSeededBreakdowns ? ("pageviews" as BreakdownMetricKey) : breakdownData.devices.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "pageviews", "conversions"] as BreakdownMetricKey[])
          : breakdownData.devices.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.pageviews : breakdownData.devices.total,
        totalsByMetric: showSeededBreakdowns ? seededBreakdownTotals : breakdownData.devices.totalsByMetric,
        comparison: comparisonContextFor(
          comparisonDeviceRows,
          comparisonBreakdownData.devices.total,
          comparisonBreakdownData.devices.totalsByMetric
        ),
      },
      {
        title: "Goal completions",
        rows: goalRows,
        empty: "No goal completions yet for the selected range.",
        error: showSeededBreakdowns ? null : breakdownErrors.conversions ?? null,
        dimension: "goal",
        primaryMetric: showSeededBreakdowns ? ("conversions" as BreakdownMetricKey) : breakdownData.conversions.primaryMetric,
        metricKeys: showSeededBreakdowns
          ? (["uniques", "sessions", "conversions"] as BreakdownMetricKey[])
          : breakdownData.conversions.metricKeys,
        total: showSeededBreakdowns ? scaledTotals.conversions : breakdownData.conversions.total,
        totalsByMetric: showSeededBreakdowns
          ? ({ uniques: scaledTotals.uniques, sessions: scaledTotals.sessions, conversions: scaledTotals.conversions } as BreakdownMetricTotals)
          : breakdownData.conversions.totalsByMetric,
        comparison: comparisonContextFor(
          comparisonGoalRows,
          comparisonBreakdownData.conversions.total,
          comparisonBreakdownData.conversions.totalsByMetric
        ),
      },
    ];
  }, [
    pageRows,
    comparisonPageRows,
    countryRows,
    comparisonCountryRows,
    deviceRows,
    comparisonDeviceRows,
    goalRows,
    comparisonGoalRows,
    showSeededBreakdowns,
    scaledTotals.uniques,
    scaledTotals.sessions,
    scaledTotals.pageviews,
    scaledTotals.conversions,
    breakdownErrors.pages,
    breakdownErrors.countries,
    breakdownErrors.devices,
    breakdownErrors.conversions,
    breakdownData.pages.primaryMetric,
    breakdownData.pages.metricKeys,
    breakdownData.pages.total,
    breakdownData.pages.totalsByMetric,
    breakdownData.countries.primaryMetric,
    breakdownData.countries.metricKeys,
    breakdownData.countries.total,
    breakdownData.countries.totalsByMetric,
    breakdownData.devices.primaryMetric,
    breakdownData.devices.metricKeys,
    breakdownData.devices.total,
    breakdownData.devices.totalsByMetric,
    breakdownData.conversions.primaryMetric,
    breakdownData.conversions.metricKeys,
    breakdownData.conversions.total,
    breakdownData.conversions.totalsByMetric,
    comparisonBreakdownData.pages.total,
    comparisonBreakdownData.pages.totalsByMetric,
    comparisonBreakdownData.countries.total,
    comparisonBreakdownData.countries.totalsByMetric,
    comparisonBreakdownData.devices.total,
    comparisonBreakdownData.devices.totalsByMetric,
    comparisonBreakdownData.conversions.total,
    comparisonBreakdownData.conversions.totalsByMetric,
    comparisonContextFor,
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
    if (selectedMetric !== "uniques") next.set("metric", selectedMetric);
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
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.channels.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.channels.primaryMetric,
      },
      source: {
        rows: sourceRows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.sources.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.sources.primaryMetric,
      },
      source_medium: {
        rows: sourceMediumRows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.source_medium.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.source_medium.primaryMetric,
      },
      campaign: {
        rows: campaignDimension === "campaign" ? campaignRows : breakdownData.campaign.rows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.campaign.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.campaign.primaryMetric,
      },
      content: {
        rows: campaignDimension === "content" ? campaignRows : breakdownData.content.rows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.content.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.content.primaryMetric,
      },
      term: {
        rows: campaignDimension === "term" ? campaignRows : breakdownData.term.rows,
        total: showSeededBreakdowns ? scaledTotals.sessions : breakdownData.term.total,
        primaryMetric: showSeededBreakdowns ? "sessions" : breakdownData.term.primaryMetric,
      },
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
    campaignDimension,
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
  const selectedMetricGoal = metricSupportsGoals(selectedMetric) ? siteGoals[goalKey(selectedMetric)] ?? null : null;
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
  const hasTodayTileActual = Number.isFinite(todayActualValue);
  const hasTodayProjectionBaseline = Number.isFinite(todayForecastEntry?.yhat ?? Number.NaN);
  const todayProjectionValue = hasTodayProjectionBaseline ? (todayForecastEntry?.yhat as number) : Number.NaN;
  const todayProgressPct =
    Number.isFinite(todayActualValue) && Number.isFinite(todayProjectionValue) && todayProjectionValue > 0
      ? clamp((todayActualValue / todayProjectionValue) * 100, 0, 999)
      : Number.NaN;
  const todayActualExceedsProjection =
    hasTodayTileActual && hasTodayProjectionBaseline && todayActualValue > todayProjectionValue;
  const todayTileLabel = todayActualExceedsProjection || !hasTodayProjectionBaseline ? "Today so far" : "Projected today";
  const todayTileValue =
    todayActualExceedsProjection || !hasTodayProjectionBaseline ? todayActualValue : todayProjectionValue;
  const todayBaselineProgressText = Number.isFinite(todayProgressPct)
    ? `${todayProgressPct.toFixed(0)}% of baseline`
    : "baseline unavailable";
  const todayProgressNote =
    hasTodayTileActual && hasTodayProjectionBaseline
      ? todayActualExceedsProjection
        ? `${formatMetricValue(selectedMetric, todayProjectionValue)} baseline · ${todayBaselineProgressText}`
        : `${formatMetricValue(selectedMetric, todayActualValue)} so far · ${todayBaselineProgressText}`
      : hasTodayTileActual
        ? `${formatMetricValue(selectedMetric, todayActualValue)} recorded today`
        : hasTodayProjectionBaseline
          ? "No same-day actuals yet"
          : "No same-day data yet";
  const chartSubtitle = [
    currentRangeLabel ?? range,
    lastCompleteActualDay ? `actual through ${formatShortDate(lastCompleteActualDay)}` : "awaiting actual data",
    hasForecast ? `forecast through ${forecastLabel.toLowerCase()}` : forecastMutedNote,
  ].join(" · ");
  const periodDeltaDisplay = Number.isFinite(selectedMetricDeltaPct)
    ? `${selectedMetricDeltaPct >= 0 ? "↑" : "↓"} ${Math.abs(selectedMetricDeltaPct * 100).toFixed(0)}%`
    : "N/A";
  const periodDeltaNote = kpiComparisonLabel ?? "vs previous period";
  const showTodayProjection = showTodayLine && Number.isFinite(todayTileValue);
  const forecastTileHeading =
    forecastDayCount > 0
      ? `Next ${forecastDayCount} days · total`
      : selectedForecast.kind === "days"
        ? `Next ${selectedForecast.days} days · total`
        : `${forecastLabel} · total`;
  const forecastSummaryGridClass = showTodayProjection
    ? "sm:grid-cols-3"
    : "sm:grid-cols-2";
  const dashboardGoals = Object.values(siteGoals).filter((goal): goal is MetricGoal => Boolean(goal));
  const goalCurrentValues = useMemo(() => {
    const values: Record<string, number> = { ...(scaledTotals as Record<string, number>) };
    goalRows.forEach((row) => {
      values[goalKey("conversions", row.label)] = getBreakdownMetricValue(row, "conversions");
    });
    return values;
  }, [goalRows, scaledTotals]);
  const fallbackInsightItems = useMemo(() => {
    const items: { label: string; text: string }[] = [];
    if (!useSegmentAggregates && forecastMeta?.has_anomaly) {
      items.push({
        label: "Anomaly",
        text: `${selectedMetricLabel} was unusually different from the site's recent pattern. Forecasts may be wider while the trend stabilizes.`,
      });
    }
    const otherAnomalousMetrics = Object.entries(metricAnomalies)
      .filter(([metric, flagged]) => flagged && metric !== selectedMetric)
      .map(([metric]) => metricLabels[metric] ?? metric);
    if (otherAnomalousMetrics.length > 0) {
      const names = otherAnomalousMetrics.slice(0, 3).join(", ");
      items.push({
        label: "Watch",
        text: `${names} also ${otherAnomalousMetrics.length === 1 ? "looks" : "look"} unusual versus recent trend. Switch metric to inspect.`,
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
        text: `${selectedMetricLabel} is ${selectedMetricDeltaPct >= 0 ? "up" : "down"} ${formatInsightPercent(
          Math.abs(selectedMetricDeltaPct)
        )} ${periodDeltaNote}.`,
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
      items.push({
        label: "Status",
        text: `${selectedMetricLabel} is steady for this period. No unusual traffic pattern has been detected yet.`,
      });
    }
    return items.slice(0, 5);
  }, [
    forecastMeta?.has_anomaly,
    useSegmentAggregates,
    metricAnomalies,
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
  const insightItems = useMemo(
    () =>
      remoteInsightsStatus === "loaded"
        ? remoteInsights.map((item) => ({ label: item.label, text: item.text }))
        : fallbackInsightItems,
    [remoteInsightsStatus, remoteInsights, fallbackInsightItems]
  );
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
  const timePartingError =
    [breakdownErrors.hour_of_day, breakdownErrors.day_of_week].filter(Boolean).join(" ") || null;
  const liveStatusMessage = useMemo(() => {
    const breakdownMessages = (Object.entries(breakdownErrors) as [BreakdownDimension, string][])
      .filter(([, message]) => Boolean(message))
      .map(([dimension, message]) => `${breakdownSectionLabels[dimension]}: ${message}`);
    return [
      kpiError ? `Metrics: ${kpiError}` : null,
      forecastError ? `Forecast: ${forecastError}` : null,
      hostnameError ? `Hostnames: ${hostnameError}` : null,
      ...breakdownMessages,
    ]
      .filter(Boolean)
      .join(" ");
  }, [breakdownErrors, forecastError, hostnameError, kpiError]);
  const renderNoteMarkerLabel = (day: string) => (props: { viewBox?: { x?: number; y?: number; height?: number } }) => {
    const viewBox = props.viewBox ?? {};
    const x = Number(viewBox.x ?? 0);
    const y = Number(viewBox.y ?? 0) + Number(viewBox.height ?? 0) - 3;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return <g />;
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
              {siteDisplayName}
            </div>
          </div>
          <div className="flex max-w-full flex-col items-end gap-2">
            <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
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
            {hostnameError && (
              <div className="text-[11px] text-[#8B2635]" style={fontBody}>
                {hostnameError}
              </div>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1180px] space-y-5 px-5 pb-12 pt-0 sm:px-8 print-container">
        <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {liveStatusMessage}
        </div>
        <KPIGrid
          values={scaledTotals}
          comparisonValues={scaledKpiComparisonValues}
          comparisonLabel={kpiComparisonLabel}
          currentRangeLabel={currentRangeLabel}
          comparisonRangeLabel={comparisonRangeLabel}
          showDetailedComparison={compareEnabled}
          selectedMetric={selectedMetric}
          onSelectMetric={setSelectedMetric}
          error={kpiError}
        />
        {!useSegmentAggregates &&
          forecastMeta?.has_anomaly &&
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
                Trend and KPI views use stored segment rollups where available.
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
                  {activeMarkerNotes.map((note) => {
                    const noteContext =
                      note.day !== activeNoteMarkerDay
                        ? [formatShortDate(note.day), note.metric ? formatNoteMetric(note.metric) : null]
                        : [note.metric ? formatNoteMetric(note.metric) : null];
                    const noteContextText = noteContext.filter(Boolean).join(" · ");
                    return (
                      <div key={note.id} className="border-t border-[#EEF2F7] pt-2 first:border-t-0 first:pt-0">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            {noteContextText && (
                              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#9CA3AF]" style={fontMeta}>
                                {noteContextText}
                              </div>
                            )}
                            <div className={noteContextText ? "mt-1 text-[12px] leading-5 text-[#374151]" : "text-[12px] leading-5 text-[#374151]"} style={fontBody}>
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
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          {forecastError && (
            <div className="mt-3 rounded-md border border-[#FECACA] bg-[#FFF7F7] px-3 py-2 text-[12px] text-[#8B2635]" style={fontBody}>
              {forecastError}
            </div>
          )}
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
            <span
              className={`${chartGranularity !== "day" || hasForecast ? "" : "ml-auto"} flex items-center gap-1.5 text-[11px] text-[#4B5563]`}
              title={forecastFreshnessDetail}
              style={fontBody}
            >
              Forecast status <span className="metric-number text-[#6B7280]" style={fontMetric}>{forecastFreshnessText}</span>
            </span>
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
          <div className="mt-4 border-t border-[var(--color-border-subtle)] pt-3">
            <div
              className={`grid gap-y-3 divide-y divide-[var(--color-border-subtle)] ${forecastSummaryGridClass} sm:divide-x sm:divide-y-0`}
            >
              {showTodayProjection ? (
                <div className="py-2 sm:pr-5">
                  <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontBody}>
                    {todayTileLabel}
                  </div>
                  <div className="mt-1 metric-number text-[18px] font-semibold leading-tight text-[#111827]" style={fontMetric}>
                    {formatMetricValue(selectedMetric, todayTileValue)}
                  </div>
                  <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
                    {todayProgressNote}
                  </div>
                </div>
              ) : null}
              <div className={`py-2 ${showTodayProjection ? "sm:px-5" : "sm:pr-5"}`}>
                <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontBody}>
                  {forecastTileHeading}
                </div>
                <div className="mt-1 metric-number text-[22px] font-semibold leading-tight text-[#111827]" style={fontMetric}>
                  {forecastSummary ? formatMetricValue(selectedMetric, forecastSummary.total) : "N/A"}
                </div>
                <div className="mt-1 text-[11px] text-[#7B8190]" style={fontBody}>
                  {forecastSummary ? `Avg ${formatDailyPace(selectedMetric, forecastSummary.average)}` : forecastMutedNote}
                </div>
              </div>
              <div className="py-2 sm:pl-5">
                <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#7B8190]" style={fontBody}>
                  Pace vs prior period
                </div>
                <div
                  className={`mt-1 metric-number text-[18px] font-semibold leading-tight ${
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
        {insightItems.length > 0 ? (
          <section>
            <SectionLabel>Insights</SectionLabel>
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
        ) : null}

        <section>
          <SectionLabel>Breakdowns</SectionLabel>
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
              totalsByMetric={acquisitionTotalsByMetric}
              comparison={comparisonContextFor(
                acquisitionComparisonRows,
                acquisitionComparisonTotal,
                acquisitionComparisonTotalsByMetric
              )}
              rowDimension={acquisitionDimensionKey}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
              emptyState={acquisitionEmptyState}
              error={showSeededBreakdowns ? null : breakdownErrors[acquisitionBackendDimension] ?? null}
            />
            <TableBlock
              title="Top Pages"
              rows={breakdownCards[0]?.rows ?? []}
              metricKeys={breakdownCards[0]?.metricKeys ?? (["pageviews"] as BreakdownMetricKey[])}
              primaryMetric={breakdownCards[0]?.primaryMetric ?? "pageviews"}
              total={breakdownCards[0]?.total}
              totalsByMetric={breakdownCards[0]?.totalsByMetric}
              comparison={breakdownCards[0]?.comparison}
              emptyState={breakdownCards[0]?.empty}
              error={breakdownCards[0]?.error}
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
              totalsByMetric={breakdownCards[1]?.totalsByMetric}
              comparison={breakdownCards[1]?.comparison}
              emptyState={breakdownCards[1]?.empty}
              error={breakdownCards[1]?.error}
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
              totalsByMetric={breakdownCards[2]?.totalsByMetric}
              comparison={breakdownCards[2]?.comparison}
              emptyState={breakdownCards[2]?.empty}
              error={breakdownCards[2]?.error}
              rowDimension={breakdownCards[2]?.dimension}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
            />
          </div>
        </section>
        <section>
          <SectionLabel>Goals & Timing</SectionLabel>
          <div className="grid gap-4 md:grid-cols-2">
            <GoalsProgressCard
              goals={dashboardGoals}
              values={goalCurrentValues}
              dayCount={selectedRangeDayCount}
              rangeLabel={currentRangeLabel ?? range}
              siteId={siteId}
            />
            <TableBlock
              title="Goal completions"
              rows={breakdownCards[3]?.rows ?? []}
              metricKeys={breakdownCards[3]?.metricKeys ?? (["conversions"] as BreakdownMetricKey[])}
              primaryMetric={breakdownCards[3]?.primaryMetric ?? "conversions"}
              total={breakdownCards[3]?.total}
              totalsByMetric={breakdownCards[3]?.totalsByMetric}
              comparison={breakdownCards[3]?.comparison}
              emptyState={breakdownCards[3]?.empty}
              error={breakdownCards[3]?.error}
              rowDimension={breakdownCards[3]?.dimension}
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
            />
            <div className="md:col-span-2">
              <TimePartingHeatmap
                hourRows={showSeededBreakdowns ? seededHourRows : breakdownData.hour_of_day.rows}
                dayRows={showSeededBreakdowns ? seededDayRows : breakdownData.day_of_week.rows}
                primaryMetric={timePartingPrimaryMetric}
                dayType={timePartingDayType}
                setDayType={setTimePartingDayType}
                emptyState={timePartingEmptyState}
                error={timePartingError}
                rangeLabel={currentRangeLabel ?? range}
              />
            </div>
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
  const [siteName, setSiteName] = useState<string | null>(null);
  const [siteNameDraft, setSiteNameDraft] = useState<string>(() => fallbackSiteDisplayName(siteId));
  const [siteNameStatus, setSiteNameStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [siteNameError, setSiteNameError] = useState<string | null>(null);
  const siteDisplayName = useMemo(() => dashboardSiteDisplayName(siteId, siteName), [siteId, siteName]);
  const [timezone, setTimezone] = useState<string>("UTC");
  const [timezoneDraft, setTimezoneDraft] = useState<string>("UTC");
  const [timezoneStatus, setTimezoneStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("idle");
  const [timezoneError, setTimezoneError] = useState<string | null>(null);
  const [billingPlan, setBillingPlan] = useState<"free" | "standard" | "pro">("free");
  const [billingDetails, setBillingDetails] = useState<BillingStatus | null>(null);
  const [hasSubscription, setHasSubscription] = useState<boolean>(false);
  const [billingStatus, setBillingStatus] = useState<"idle" | "loading" | "redirecting" | "error">("idle");
  const [billingMessage, setBillingMessage] = useState<string | null>(null);
  const [importCsvText, setImportCsvText] = useState<string>("");
  const [importPreview, setImportPreview] = useState<HistoricalImportPreviewResponse | null>(null);
  const [importPreviewStatus, setImportPreviewStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [importPreviewMessage, setImportPreviewMessage] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importBatches, setImportBatches] = useState<HistoricalImportBatch[]>([]);
  const [importHistoryStatus, setImportHistoryStatus] = useState<"idle" | "loading" | "error">("idle");
  const [importHistoryMessage, setImportHistoryMessage] = useState<string | null>(null);
  const [deletingImportBatchId, setDeletingImportBatchId] = useState<number | null>(null);
  const [health, setHealth] = useState<SiteHealthResponse | null>(null);
  const [installVerify, setInstallVerify] = useState<SdkInstallVerifyResponse | null>(null);
  const [installVerifyStatus, setInstallVerifyStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [installVerifyMessage, setInstallVerifyMessage] = useState<string | null>(null);
  const [isInstallReviewOpen, setIsInstallReviewOpen] = useState<boolean>(false);
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
  const [alertSettings, setAlertSettings] = useState<SiteAlertSettings | null>(null);
  const [anomalyAlertsEnabled, setAnomalyAlertsEnabled] = useState<boolean>(false);
  const [slackAlertsEnabled, setSlackAlertsEnabled] = useState<boolean>(false);
  const [slackWebhookUrl, setSlackWebhookUrl] = useState<string>("");
  const [slackWebhookUrlSet, setSlackWebhookUrlSet] = useState<boolean>(false);
  const [clearSlackWebhook, setClearSlackWebhook] = useState<boolean>(false);
  const [emailAlertsEnabled, setEmailAlertsEnabled] = useState<boolean>(false);
  const [emailRecipientsDraft, setEmailRecipientsDraft] = useState<string>("");
  const [alertStatus, setAlertStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("idle");
  const [alertMessage, setAlertMessage] = useState<string | null>(null);
  const [goals, setGoals] = useState<SiteGoalsMap>({});
  const [goalMetric, setGoalMetric] = useState<GoalMetric>("revenue");
  const [goalConversionType, setGoalConversionType] = useState<string>("");
  const [goalConversionTypes, setGoalConversionTypes] = useState<string[]>([]);
  const [goalTargetInput, setGoalTargetInput] = useState<string>("");
  const [goalStatus, setGoalStatus] = useState<string | null>(null);
  const [activeSettingsPanel, setActiveSettingsPanel] = useState<SettingsPanel>(() => {
    if (typeof window === "undefined") return "general";
    const initialHash = window.location.hash.replace(/^#/, "");
    return isSettingsPanel(initialHash) ? initialHash : "general";
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onHashChange = () => {
      const nextHash = window.location.hash.replace(/^#/, "");
      if (isSettingsPanel(nextHash)) setActiveSettingsPanel(nextHash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const selectSettingsPanel = useCallback((panel: SettingsPanel) => {
    setActiveSettingsPanel(panel);
    if (typeof window === "undefined") return;
    const nextUrl = `${window.location.pathname}${window.location.search}#${panel}`;
    window.history.replaceState(null, "", nextUrl);
  }, []);

  const refreshSiteGoals = useCallback(async () => {
    if (!canQuery) {
      setGoals({});
      return;
    }
    try {
      const result = await fetchSiteGoals(token ?? undefined, siteId);
      setGoals(mapServerGoals(result.goals));
      setGoalStatus(null);
    } catch (error) {
      setGoals({});
      setGoalStatus(extractApiErrorMessage(error) ?? "Unable to load performance targets right now.");
    }
  }, [canQuery, siteId, token]);

  useEffect(() => {
    void refreshSiteGoals();
  }, [refreshSiteGoals]);

  useEffect(() => {
    if (!canQuery) {
      setGoalConversionTypes([]);
      return;
    }
    let cancelled = false;
    fetchBreakdown("conversions", token ?? undefined, siteId, undefined, undefined, 50)
      .then((result) => {
        if (cancelled) return;
        setGoalConversionTypes(
          Array.from(new Set((result.rows ?? []).map((row) => row.label).filter(Boolean))).sort((a, b) =>
            a.localeCompare(b)
          )
        );
      })
      .catch(() => {
        if (!cancelled) setGoalConversionTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [canQuery, siteId, token]);

  useEffect(() => {
    if (goalMetric !== "conversions") {
      setGoalConversionType("");
    }
  }, [goalMetric]);

  useEffect(() => {
    if (!canQuery) return;
    let cancelled = false;
    setTimezoneStatus("loading");
    fetchSiteSettings(token ?? undefined, siteId)
      .then((settings) => {
        if (cancelled) return;
        const resolvedTimezone = settings.timezone || "UTC";
        const resolvedSiteName = dashboardSiteDisplayName(siteId, settings.site_name);
        setSiteName(settings.site_name ?? null);
        setSiteNameDraft(resolvedSiteName);
        setSiteNameStatus("idle");
        setSiteNameError(null);
        setTimezone(resolvedTimezone);
        setTimezoneDraft(resolvedTimezone);
        setTimezoneStatus("idle");
        setTimezoneError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        const fallbackName = fallbackSiteDisplayName(siteId);
        setSiteName(null);
        setSiteNameDraft(fallbackName);
        setSiteNameStatus("error");
        setSiteNameError(extractApiErrorMessage(error) ?? "Unable to load site name.");
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
        setBillingDetails(status);
        setHasSubscription(Boolean(status.has_subscription));
        setBillingStatus("idle");
      })
      .catch((error) => {
        if (cancelled) return;
        setBillingDetails(null);
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
    fetchSiteHealth(token ?? undefined, siteId)
      .then((result) => {
        if (cancelled) return;
        setHealth(result);
      })
      .catch(() => {
        if (cancelled) return;
        setHealth(null);
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

  const reviewInstallation = async () => {
    if (!canQuery) return;
    setInstallVerifyStatus("loading");
    setInstallVerifyMessage(null);
    try {
      const result = await verifySdkInstall(token ?? undefined, siteId, 15);
      setInstallVerify(result);
      setInstallVerifyStatus("success");
      setInstallVerifyMessage(
        result.has_recent_activity
          ? `${formatNumber(result.recent_reports)} reports received in the last ${result.lookback_minutes} minutes.`
          : `No reports received in the last ${result.lookback_minutes} minutes.`
      );
      const refreshedHealth = await fetchSiteHealth(token ?? undefined, siteId);
      setHealth(refreshedHealth);
    } catch (error) {
      setInstallVerify(null);
      setInstallVerifyStatus("error");
      setInstallVerifyMessage(extractApiErrorMessage(error) ?? "Unable to verify the installation right now.");
    }
  };

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

  const applyAlertSettings = useCallback((settings: SiteAlertSettings) => {
    setAlertSettings(settings);
    setAnomalyAlertsEnabled(Boolean(settings.anomaly_alerts_enabled));
    setSlackAlertsEnabled(Boolean(settings.slack_enabled));
    setSlackWebhookUrlSet(Boolean(settings.slack_webhook_url_set));
    setSlackWebhookUrl("");
    setClearSlackWebhook(false);
    setEmailAlertsEnabled(Boolean(settings.email_enabled));
    setEmailRecipientsDraft((settings.email_recipients ?? []).join("\n"));
  }, []);

  const refreshAlertSettings = useCallback(async () => {
    if (!canQuery) return;
    if (billingPlan !== "standard" && billingPlan !== "pro") {
      setAlertSettings(null);
      setAnomalyAlertsEnabled(false);
      setSlackAlertsEnabled(false);
      setSlackWebhookUrlSet(false);
      setSlackWebhookUrl("");
      setClearSlackWebhook(false);
      setEmailAlertsEnabled(false);
      setEmailRecipientsDraft("");
      setAlertStatus("idle");
      setAlertMessage(null);
      return;
    }
    setAlertStatus("loading");
    setAlertMessage(null);
    try {
      const result = await fetchSiteAlertSettings(token ?? undefined, siteId);
      applyAlertSettings(result);
      setAlertStatus("idle");
    } catch (error) {
      setAlertSettings(null);
      setAlertStatus("error");
      setAlertMessage(extractApiErrorMessage(error) ?? "Unable to load anomaly alert settings right now.");
    }
  }, [applyAlertSettings, billingPlan, canQuery, siteId, token]);

  useEffect(() => {
    void refreshAlertSettings();
  }, [refreshAlertSettings]);

  const selectedGoalConversionType = goalMetric === "conversions" ? goalConversionType || null : null;
  const selectedGoalKey = goalKey(goalMetric, selectedGoalConversionType);
  const existingGoal = goals[selectedGoalKey];
  useEffect(() => {
    setGoalTargetInput(existingGoal ? String(existingGoal.target) : "");
  }, [selectedGoalKey, existingGoal?.target]);

  const sortedGoals = useMemo(
    () =>
      Object.values(goals).sort((a, b) => {
        const metricOrder = goalEligibleMetrics.indexOf(a.metric) - goalEligibleMetrics.indexOf(b.metric);
        if (metricOrder !== 0) return metricOrder;
        return (a.conversionType ?? "").localeCompare(b.conversionType ?? "");
      }),
    [goals]
  );
  const groupedGoals = useMemo(() => {
    const groups: { label: string; goals: MetricGoal[] }[] = [];
    sortedGoals.forEach((goal) => {
      const label = goalLabel(goal);
      const existing = groups.find((group) => group.label === label);
      if (existing) {
        existing.goals.push(goal);
      } else {
        groups.push({ label, goals: [goal] });
      }
    });
    return groups;
  }, [sortedGoals]);
  const conversionGoalOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...goalConversionTypes,
          ...Object.values(goals)
            .map((goal) => (goal.metric === "conversions" ? goal.conversionType ?? "" : ""))
            .filter(Boolean),
        ])
      ).sort((a, b) => a.localeCompare(b)),
    [goalConversionTypes, goals]
  );

  const saveSiteName = async () => {
    const nextName = siteNameDraft.trim();
    if (!nextName) {
      setSiteNameStatus("error");
      setSiteNameError("Site name is required.");
      return;
    }
    setSiteNameStatus("saving");
    setSiteNameError(null);
    try {
      const updated = await updateSiteName(nextName, token ?? undefined, siteId);
      const resolvedName = dashboardSiteDisplayName(updated.site_id, updated.site_name);
      setSiteName(updated.site_name ?? resolvedName);
      setSiteNameDraft(resolvedName);
      setSiteNameStatus("saved");
      window.setTimeout(() => {
        setSiteNameStatus((prev) => (prev === "saved" ? "idle" : prev));
      }, 1200);
    } catch (error) {
      setSiteNameStatus("error");
      setSiteNameError(extractApiErrorMessage(error) ?? "Unable to update site name right now.");
    }
  };

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

  const beginCheckout = async (plan: "solo" | "standard" | "early_adopter_standard" | "pro") => {
    setBillingStatus("redirecting");
    setBillingMessage(null);
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "https://app.validanalytics.io";
      const successUrl = `${origin}/billing/success?site_id=${encodeURIComponent(siteId)}`;
      const cancelUrl = `${origin}/site/${encodeURIComponent(siteId)}/settings`;
      const checkout = await createCheckoutSession(plan, token ?? undefined, siteId, successUrl, cancelUrl);
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
    setImportPreview(null);
    setImportPreviewStatus("idle");
    setImportPreviewMessage(null);
    try {
      setImportCsvText(await file.text());
    } catch {
      setImportStatus("error");
      setImportMessage("Unable to read that CSV file.");
    }
  };

  const previewHistoricalImport = async () => {
    const csvText = importCsvText.trim();
    if (!csvText) {
      setImportPreviewStatus("error");
      setImportPreviewMessage("Paste or upload a CSV before previewing.");
      setImportPreview(null);
      return;
    }
    setImportPreviewStatus("loading");
    setImportPreviewMessage(null);
    setImportStatus("idle");
    setImportMessage(null);
    try {
      const result = await previewHistoricalCsv(csvText, token ?? undefined, siteId);
      setImportPreview(result);
      setImportPreviewStatus(result.valid ? "ready" : "error");
      if (result.valid) {
        setImportPreviewMessage(
          `Ready to import ${formatNumber(result.row_count)} rows across ${formatNumber(result.day_count)} days.`
        );
      } else if (result.live_overlaps.length > 0) {
        setImportPreviewMessage("Remove overlapping live-data dates before importing.");
      } else if (result.errors.length > 0) {
        setImportPreviewMessage(result.errors[0]);
      } else {
        setImportPreviewMessage("Review the warnings before importing.");
      }
    } catch (error) {
      setImportPreview(null);
      setImportPreviewStatus("error");
      setImportPreviewMessage(extractApiErrorMessage(error) ?? "Unable to preview historical data right now.");
    }
  };

  const submitHistoricalImport = async () => {
    const csvText = importCsvText.trim();
    if (!csvText) {
      setImportStatus("error");
      setImportMessage("Paste or upload a CSV before importing.");
      return;
    }
    if (!importPreview?.valid) {
      setImportStatus("error");
      setImportMessage("Preview the CSV and resolve any overlap warnings before importing.");
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
      setImportPreview(null);
      setImportPreviewStatus("idle");
      setImportPreviewMessage(null);
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
    if (billingPlan !== "standard" && billingPlan !== "pro") {
      setAccessStatus("error");
      setAccessMessage("Site access management is available on Standard.");
      return;
    }
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
    if (billingPlan !== "standard" && billingPlan !== "pro") {
      setAccessStatus("error");
      setAccessMessage("Site access management is available on Standard.");
      return;
    }
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

  const parseEmailRecipients = (value: string): string[] =>
    value
      .split(/[\n,;]+/)
      .map((item) => item.trim())
      .filter(Boolean);

  const saveAlertSettings = async () => {
    if (billingPlan !== "standard" && billingPlan !== "pro") {
      setAlertStatus("error");
      setAlertMessage("Anomaly alerts are available on Standard.");
      return;
    }
    const recipients = parseEmailRecipients(emailRecipientsDraft);
    const webhook = slackWebhookUrl.trim();
    const payload: {
      anomaly_alerts_enabled: boolean;
      slack_enabled: boolean;
      slack_webhook_url?: string | null;
      email_enabled: boolean;
      email_recipients: string[];
    } = {
      anomaly_alerts_enabled: anomalyAlertsEnabled,
      slack_enabled: slackAlertsEnabled,
      email_enabled: emailAlertsEnabled,
      email_recipients: recipients,
    };
    if (clearSlackWebhook) {
      payload.slack_webhook_url = "";
    } else if (webhook) {
      payload.slack_webhook_url = webhook;
    }

    setAlertStatus("saving");
    setAlertMessage(null);
    try {
      const result = await updateSiteAlertSettings(payload, token ?? undefined, siteId);
      applyAlertSettings(result);
      setAlertStatus("saved");
      setAlertMessage("Anomaly alert settings saved.");
      window.setTimeout(() => {
        setAlertStatus((prev) => (prev === "saved" ? "idle" : prev));
      }, 1200);
    } catch (error) {
      setAlertStatus("error");
      setAlertMessage(extractApiErrorMessage(error) ?? "Unable to save anomaly alert settings right now.");
    }
  };

  const hasSiteNameChanges = siteNameDraft.trim() !== siteDisplayName.trim();
  const siteNameStatusClassName = siteNameStatus === "error" ? "text-[#8B2635]" : "text-gray-500";
  const siteNameStatusText =
    siteNameStatus === "saving"
      ? "Saving site name..."
      : siteNameStatus === "saved"
        ? "Site name saved."
        : siteNameStatus === "error"
          ? siteNameError
          : "Used across the dashboard and settings navigation.";
  const hasTimezoneChanges = timezoneDraft !== timezone;
  const planDisplayName = billingDetails?.display_plan ?? (billingPlan === "free" ? "Solo" : billingPlan);
  const hasStandardEntitlements = billingPlan === "standard" || billingPlan === "pro";
  const canImportHistoricalData = Boolean(billingDetails?.can_import_historical_data ?? billingPlan === "standard");
  const canManageAnomalyAlerts = Boolean(billingDetails?.can_manage_anomaly_alerts ?? hasStandardEntitlements);
  const canManageSiteAccess = Boolean(billingDetails?.can_manage_site_access ?? hasStandardEntitlements);
  const importStatusClassName = importStatus === "error" ? "text-[#8B2635]" : "text-gray-500";
  const importPreviewStatusClassName = importPreviewStatus === "error" ? "text-[#8B2635]" : "text-gray-500";
  const canSubmitHistoricalImport = Boolean(importPreview?.valid) && importStatus !== "loading";
  const alertStatusClassName = alertStatus === "error" ? "text-[#8B2635]" : "text-gray-500";
  const latestInstallReportAt = installVerify?.last_report_at ?? health?.last_report_at ?? null;
  const installationHasRecentActivity = Boolean(installVerify?.has_recent_activity || health?.last_report_at);
  const installationHasBeenReviewed = Boolean(installVerify || health);
  const installationStatusLabel =
    installVerifyStatus === "loading"
      ? "Checking"
      : installationHasRecentActivity
        ? "Receiving data"
        : installationHasBeenReviewed
          ? "Needs review"
          : "Not reviewed";
  const installationStatusTone =
    installVerifyStatus === "loading" ? "warning" : installationHasRecentActivity ? "ok" : health?.overall_status === "error" ? "error" : "warning";
  const installationSummary = installationHasRecentActivity
    ? `Last event ${formatRelativeTime(latestInstallReportAt)}`
    : "No recent tracking event verified yet.";
  const reducerSummary = health?.latest_reducer_status
    ? `${health.latest_reducer_status}${health.latest_reducer_day ? ` through ${formatShortDate(health.latest_reducer_day)}` : ""}`
    : "No reducer run recorded yet.";
  const forecastSummary = health
    ? health.forecast_metrics_ready.length > 0
      ? `${health.forecast_metrics_ready.join(", ")} ready${
          health.forecast_metrics_building.length > 0 ? `; ${health.forecast_metrics_building.join(", ")} building` : ""
        }`
      : health.forecast_metrics_building.length > 0
        ? `${health.forecast_metrics_building.join(", ")} building`
        : "Forecasts are building."
    : "Forecast status has not loaded.";
  const alertSetupSummary = !canManageAnomalyAlerts
    ? "Available on Standard"
    : anomalyAlertsEnabled
      ? `Enabled for ${[
          slackAlertsEnabled && slackWebhookUrlSet ? "Slack" : null,
          emailAlertsEnabled ? "email" : null,
        ].filter(Boolean).join(" and ") || "selected channels"}`
      : "Not enabled.";

  const billingDescription = (() => {
    if (billingPlan === "standard") {
      const additionalSites = billingDetails?.additional_site_count ?? 0;
      return hasSubscription
        ? `Your Standard subscription is active. Standard includes ${
            billingDetails?.included_sites ?? 3
          } sites${additionalSites > 0 ? `; ${additionalSites} additional site${additionalSites === 1 ? "" : "s"} should be billed separately.` : "."}`
        : "This site is marked Standard but no active subscription is linked yet.";
    }
    if (billingPlan === "pro") {
      return "Your Pro subscription is active for this site.";
    }
    return hasSubscription
      ? "Your Solo subscription is active. Standard is built for business operations: multiple sites, historical imports, anomaly alerts, team access, and all forecast metrics."
      : "This site is on Solo features, but billing is not active yet. Subscribe to Solo to keep this site active commercially.";
  })();

  const billingCheckoutPlan: "solo" | "standard" | "early_adopter_standard" | "pro" =
    billingPlan === "free" && !hasSubscription ? "solo" : billingPlan === "pro" ? "pro" : "standard";
  const billingActionLabel =
    billingPlan === "free"
      ? hasSubscription
        ? "Upgrade To Standard"
        : "Subscribe To Solo"
      : billingPlan === "standard"
        ? "Standard Active"
        : "Manage Pro Subscription";

  const billingActionDisabled = billingStatus === "redirecting" || billingStatus === "loading" || billingPlan === "standard";

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


  const submitGoal = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const target = Number(goalTargetInput);
    if (!Number.isFinite(target) || target <= 0) {
      setGoalStatus("Enter a valid target greater than zero.");
      return;
    }
    setGoalStatus("Saving target...");
    try {
      const result = await upsertSiteGoal(goalMetric, target, 30, selectedGoalConversionType, token ?? undefined, siteId);
      setGoals(mapServerGoals(result.goals));
      setGoalStatus(`${goalLabel({ metric: goalMetric, conversionType: selectedGoalConversionType })} target saved.`);
    } catch (error) {
      setGoalStatus(extractApiErrorMessage(error) ?? "Unable to save that target right now.");
    }
  };

  const clearGoal = async () => {
    setGoalStatus("Removing target...");
    try {
      const result = await deleteSiteGoal(goalMetric, selectedGoalConversionType, token ?? undefined, siteId);
      setGoals(mapServerGoals(result.goals));
      setGoalStatus(`${goalLabel({ metric: goalMetric, conversionType: selectedGoalConversionType })} target removed.`);
      setGoalTargetInput("");
    } catch (error) {
      setGoalStatus(extractApiErrorMessage(error) ?? "Unable to remove that target right now.");
    }
  };

  const editGoal = (goal: MetricGoal) => {
    setGoalMetric(goal.metric);
    setGoalConversionType(goal.metric === "conversions" ? goal.conversionType ?? "" : "");
    setGoalTargetInput(String(goal.target));
    setGoalStatus(null);
  };

  const removeConfiguredGoal = async (goal: MetricGoal) => {
    setGoalStatus("Removing target...");
    try {
      const result = await deleteSiteGoal(goal.metric, goal.metric === "conversions" ? goal.conversionType ?? null : null, token ?? undefined, siteId);
      setGoals(mapServerGoals(result.goals));
      setGoalStatus(`${goalLabel(goal)} target removed.`);
      if (goalKey(goal.metric, goal.conversionType) === selectedGoalKey) setGoalTargetInput("");
    } catch (error) {
      setGoalStatus(extractApiErrorMessage(error) ?? "Unable to remove that target right now.");
    }
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
        <div className="mt-2 border-b border-gray-200 pb-5">
          <h1 className="text-2xl font-semibold text-[#111827]" style={fontHeading}>
            Settings
          </h1>
          <div className="mt-1 text-sm text-gray-500" style={fontBody}>
            {siteDisplayName}
          </div>
        </div>

        <div className="mt-7 grid gap-6 lg:grid-cols-[230px_1fr]">
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <a href={`/site/${encodeURIComponent(siteId)}`} className="text-sm font-semibold text-[#4f46e5]" style={fontBody}>
              ← Back to stats
            </a>
            <nav className="mt-5 grid gap-1 text-sm" style={fontBody}>
              {settingsPanels.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => selectSettingsPanel(id)}
                  className={`border-l-2 px-3 py-2 text-left transition-colors ${
                    activeSettingsPanel === id
                      ? "border-[#4f46e5] bg-[#F1F3F6] font-semibold text-[#111827]"
                      : "border-transparent text-gray-700 hover:bg-gray-100 hover:text-[#111827]"
                  }`}
                >
                  {label}
                </button>
              ))}
            </nav>
          </aside>

          <div className="space-y-5">
            <section id="general" className={`${activeSettingsPanel === "general" ? "" : "hidden"} scroll-mt-6 space-y-5`}>
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
                  Site name
                </div>
                <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                  This is the customer-facing name shown inside Valid.
                </div>
                <div className="mt-4 max-w-md">
                  <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Display name
                  </label>
                  <input
                    className="mt-2 w-full border border-gray-200 bg-white px-3 py-2 text-sm text-[#1F2937]"
                    style={fontBody}
                    value={siteNameDraft}
                    onChange={(event) => setSiteNameDraft(event.target.value)}
                    placeholder={fallbackSiteDisplayName(siteId)}
                  />
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void saveSiteName()}
                    disabled={!hasSiteNameChanges || siteNameStatus === "saving"}
                    className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    {siteNameStatus === "saving" ? "Saving..." : "Save name"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSiteNameDraft(siteDisplayName);
                      setSiteNameStatus("idle");
                      setSiteNameError(null);
                    }}
                    disabled={!hasSiteNameChanges || siteNameStatus === "saving"}
                    className="border border-gray-300 bg-white px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                    style={fontBody}
                  >
                    Reset
                  </button>
                </div>
                <div className={`mt-2 text-[11px] ${siteNameStatusClassName}`} style={fontBody}>
                  {siteNameStatusText}
                </div>
                <div className="mt-4 text-[11px] text-gray-500" style={fontBody}>
                  Tracking site ID: <span className="meta-number text-[#7B8190]">{siteId}</span>
                </div>
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
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                      Site installation
                    </div>
                    <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                      Review whether this site is receiving data and ready for reporting.
                    </div>
                  </div>
                  {installationHasBeenReviewed || installVerifyStatus === "loading" ? (
                    <span
                      className={`rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${statusToneClass(installationStatusTone)}`}
                      style={fontBody}
                    >
                      {installationStatusLabel}
                    </span>
                  ) : null}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setIsInstallReviewOpen(true);
                      void reviewInstallation();
                    }}
                    disabled={installVerifyStatus === "loading"}
                    className="inline-flex border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    {installVerifyStatus === "loading" ? "Checking..." : "Review installation"}
                  </button>
                  <span className="text-[11px] text-gray-500" style={fontBody}>
                    {installationSummary}
                  </span>
                </div>
              </div>
              {isInstallReviewOpen && (
                <div
                  className="fixed inset-0 z-50 flex items-center justify-center bg-[#111827]/50 p-4"
                  role="dialog"
                  aria-modal="true"
                  aria-label="Review installation"
                  onClick={() => setIsInstallReviewOpen(false)}
                >
                  <div
                    className="flex max-h-[90vh] w-full max-w-2xl flex-col border border-gray-200 bg-white shadow-xl"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <div className="flex items-start justify-between gap-3 border-b border-gray-200 px-5 py-4">
                      <div>
                        <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                          Review installation
                        </div>
                        <div className="mt-1 text-[12px] text-gray-500" style={fontBody}>
                          Check whether this site is installed, receiving data, and ready for reporting.
                        </div>
                      </div>
                      <button
                        type="button"
                        aria-label="Close"
                        onClick={() => setIsInstallReviewOpen(false)}
                        className="p-1 text-gray-400 transition-colors hover:text-[#1F2937]"
                      >
                        <CloseIcon />
                      </button>
                    </div>
                    <div className="overflow-auto px-5 py-4">
                      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                        <span
                          className={`rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${statusToneClass(installationStatusTone)}`}
                          style={fontBody}
                        >
                          {installationStatusLabel}
                        </span>
                        <button
                          type="button"
                          onClick={() => void reviewInstallation()}
                          disabled={installVerifyStatus === "loading"}
                          className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                          style={fontBody}
                        >
                          {installVerifyStatus === "loading" ? "Checking..." : "Run review again"}
                        </button>
                      </div>
                      {installVerifyMessage ? (
                        <div
                          className={`mb-4 border px-3 py-2 text-[12px] ${
                            installVerifyStatus === "error"
                              ? "border-[#FECACA] bg-[#FFF7F7] text-[#8B2635]"
                              : "border-[var(--color-border-subtle)] bg-[#FCFEFE] text-gray-600"
                          }`}
                          role="status"
                          aria-live="polite"
                          style={fontBody}
                        >
                          {installVerifyMessage}
                        </div>
                      ) : null}
                      <div className="grid gap-3 sm:grid-cols-2">
                        {[
                          {
                            label: "Script installed",
                            value: installationHasRecentActivity ? "Receiving data" : "Not verified",
                            detail: installVerify
                              ? `${formatNumber(installVerify.recent_reports)} reports in the last ${installVerify.lookback_minutes} minutes`
                              : "Run the review after loading the tracked site in a browser.",
                            status: installationHasRecentActivity ? "ok" : "warning",
                          },
                          {
                            label: "Last event",
                            value: latestInstallReportAt ? formatDateTime(latestInstallReportAt) : "No event recorded",
                            detail: latestInstallReportAt ? formatRelativeTime(latestInstallReportAt) : "No recent report has reached Valid.",
                            status: latestInstallReportAt ? "ok" : "warning",
                          },
                          {
                            label: "Detected hostname",
                            value: health?.detected_hostnames.length ? health.detected_hostnames.join(", ") : "Not detected yet",
                            detail: "Hostnames come from accepted tracking events.",
                            status: health?.detected_hostnames.length ? "ok" : "warning",
                          },
                          {
                            label: "Plan",
                            value: planDisplayName,
                            detail: billingStatusText,
                            status: billingStatus === "error" ? "error" : "ok",
                          },
                          {
                            label: "Reporting data",
                            value: reducerSummary,
                            detail: health?.latest_reduced_at ? `Updated ${formatRelativeTime(health.latest_reduced_at)}` : "Reporting data updates after aggregate publishing.",
                            status: ["success", "completed", "ok"].includes(health?.latest_reducer_status ?? "") ? "ok" : health?.latest_reducer_status ? "warning" : "warning",
                          },
                          {
                            label: "Forecast",
                            value: forecastSummary,
                            detail: health?.latest_standard_published_at ? `Latest aggregate ${formatRelativeTime(health.latest_standard_published_at)}` : "Forecasts build after enough completed daily aggregate history.",
                            status: health?.forecast_metrics_ready.length ? "ok" : "warning",
                          },
                          {
                            label: "Alerts",
                            value: alertSetupSummary,
                            detail: canManageAnomalyAlerts
                              ? alertSettings?.email_delivery_configured || slackWebhookUrlSet
                                ? "Configured destinations can receive anomaly alerts."
                                : "Set Slack or email in Anomaly alerts."
                              : "Upgrade to Standard to send Slack or email anomaly alerts.",
                            status: anomalyAlertsEnabled ? "ok" : "warning",
                          },
                        ].map((item) => (
                          <div key={item.label} className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                                {item.label}
                              </div>
                              <span
                                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${statusToneClass(
                                  item.status
                                )}`}
                                style={fontBody}
                              >
                                {item.status}
                              </span>
                            </div>
                            <div className="mt-2 text-sm font-semibold text-[#1F2937]" style={fontBody}>
                              {item.value}
                            </div>
                            <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                              {item.detail}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

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
                {canManageSiteAccess ? (
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
                ) : (
                  <div className="mt-4 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                    <div className="text-sm text-[#1F2937]" style={fontBody}>
                      Site access management is available on Standard.
                    </div>
                    <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                      Upgrade to invite teammates or give another dashboard user access to this site.
                    </div>
                    <button
                      type="button"
                      onClick={() => void beginCheckout("standard")}
                      disabled={billingActionDisabled}
                      className="mt-3 border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                      style={fontBody}
                    >
                      Upgrade to Standard
                    </button>
                  </div>
                )}
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
                          {member.role === "member" && canManageSiteAccess ? (
                            <button
                              type="button"
                              onClick={() => void removeSiteMember(member.username)}
                              disabled={accessStatus === "saving"}
                              className="border border-gray-300 bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                              style={fontBody}
                            >
                              Remove
                            </button>
                          ) : member.role === "owner" ? (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600" style={fontBody}>
                              Owner
                            </span>
                          ) : (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600" style={fontBody}>
                              Member
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

            <section id="targets" className={`${activeSettingsPanel === "targets" ? "" : "hidden"} scroll-mt-6`}>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#7B8190]" style={fontMeta}>
                  Settings / Performance targets
                </div>
                <h2 className="mt-3 text-2xl font-semibold text-[#111827]" style={fontHeading}>
                  Performance targets
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[#4B5563]" style={fontBody}>
                  Set the monthly pace you want each metric to hit. Valid prorates monthly targets against the selected dashboard period,
                  so a 30-day target still works cleanly for shorter or longer date ranges.
                </p>
              </div>

              <div className="mt-7 border border-gray-200 bg-white p-5">
                <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                  Add a target
                </div>
                <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                  Pick a metric and save the monthly target you want to pace against.
                </div>
                <form
                  className={`mt-5 grid items-end gap-3 ${
                    goalMetric === "conversions"
                      ? "lg:grid-cols-[minmax(0,220px)_minmax(0,220px)_150px_150px_auto_auto]"
                      : "lg:grid-cols-[minmax(0,240px)_150px_150px_auto_auto]"
                  }`}
                  onSubmit={submitGoal}
                >
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      Metric
                    </label>
                    <select
                      className="mt-1 h-10 w-full border border-gray-200 bg-white px-3 text-sm text-[#1F2937]"
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
                  {goalMetric === "conversions" ? (
                    <div>
                      <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                        Conversion type
                      </label>
                      <select
                        className="mt-1 h-10 w-full border border-gray-200 bg-white px-3 text-sm text-[#1F2937]"
                        style={fontBody}
                        value={goalConversionType}
                        onChange={(event) => setGoalConversionType(event.target.value)}
                      >
                        <option value="">All conversions</option>
                        {conversionGoalOptions.map((conversionType) => (
                          <option key={conversionType} value={conversionType}>
                            {conversionType}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      Applies to
                    </label>
                    <div className="mt-1 flex h-10 items-center border border-gray-200 bg-[#FCFEFE] px-3 text-sm font-semibold text-[#4B5563]" style={fontBody}>
                      Every month
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      Target
                    </label>
                    <input
                      type="text"
                      inputMode={goalMetric === "revenue" ? "numeric" : "decimal"}
                      autoComplete="off"
                      className="mt-1 h-10 w-full border border-gray-200 bg-white px-3 text-sm text-[#1F2937]"
                      style={fontBody}
                      value={goalTargetInput}
                      onChange={(event) => setGoalTargetInput(event.target.value)}
                      placeholder={goalMetric === "revenue" ? "10000" : "250"}
                    />
                  </div>
                  <button
                    type="submit"
                    className="h-10 whitespace-nowrap border border-[#4f46e5] bg-[#4f46e5] px-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-white hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    Save target
                  </button>
                  <button
                    type="button"
                    onClick={() => void clearGoal()}
                    className="h-10 whitespace-nowrap border border-gray-300 bg-white px-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                    style={fontBody}
                    disabled={!existingGoal}
                  >
                    Remove
                  </button>
                </form>
                {goalStatus && (
                  <div className="mt-3 text-[12px] text-[#4B5563]" style={fontBody}>
                    {goalStatus}
                  </div>
                )}
              </div>

              <div className="mt-5 border border-gray-200 bg-white p-4">
                <div className="flex gap-3 border-l-2 border-[#4f46e5] pl-4 text-sm leading-6 text-[#4B5563]" style={fontBody}>
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gray-300 text-[11px] font-semibold text-[#7B8190]">
                    i
                  </span>
                  <div>
                    Targets are saved as monthly defaults. The dashboard prorates them for the selected date range, and conversion
                    targets can apply to all conversions or one conversion event.
                  </div>
                </div>
              </div>

              <div className="mt-5 border border-gray-200 bg-white p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                      Configured targets
                    </div>
                    <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                      Grouped by metric. Each saved row applies as a recurring monthly target.
                    </div>
                  </div>
                  {sortedGoals.length > 0 ? (
                    <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                      {formatNumber(sortedGoals.length)} set
                    </div>
                  ) : null}
                </div>

                {groupedGoals.length > 0 ? (
                  <div className="mt-5 space-y-6">
                    {groupedGoals.map((group) => (
                      <div key={group.label}>
                        <div className="flex items-center justify-between gap-3 border-b border-gray-100 pb-2">
                          <div className="text-sm font-semibold text-[#111827]" style={fontBody}>
                            {group.label}
                          </div>
                          <div className="text-[10px] uppercase tracking-[0.14em] text-gray-400" style={fontMeta}>
                            {formatNumber(group.goals.length)} set
                          </div>
                        </div>
                        <div className="divide-y divide-gray-100">
                          {group.goals.map((goal) => (
                            <div
                              key={goalKey(goal.metric, goal.conversionType)}
                              className="grid items-center gap-3 py-3 text-sm md:grid-cols-[130px_minmax(130px,180px)_1fr_auto]"
                            >
                              <div>
                                <span className="inline-flex rounded border border-gray-300 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#4B5563]" style={fontMeta}>
                                  Default
                                </span>
                              </div>
                              <div className="font-semibold text-[#111827]" style={fontBody}>
                                Every month
                              </div>
                              <div className="text-[#4B5563]" style={fontBody}>
                                <span className="metric-number font-semibold text-[#111827]" style={fontMetric}>
                                  {formatMetricValue(goal.metric, goal.target)}
                                </span>{" "}
                                <span className="text-[#7B8190]">/ mo · prorated for selected dashboard ranges</span>
                              </div>
                              <div className="flex justify-end gap-4 text-[12px] font-semibold text-gray-500" style={fontBody}>
                                <button type="button" onClick={() => editGoal(goal)} className="hover:text-[#4f46e5]">
                                  Edit
                                </button>
                                <button type="button" onClick={() => void removeConfiguredGoal(goal)} className="hover:text-[#8B2635]">
                                  Remove
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-5 text-sm text-[#6B7280]" style={fontBody}>
                    No targets configured yet for this site.
                  </div>
                )}
              </div>
            </section>

            <section id="alerts" className={`${activeSettingsPanel === "alerts" ? "" : "hidden"} scroll-mt-6 border border-gray-200 bg-white p-5`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                    Anomaly alerts
                  </div>
                  <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                    Notify your team when Valid flags an unusual recent pattern in forecasted metrics.
                  </div>
                </div>
                {alertStatus === "loading" ? (
                  <span className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Loading
                  </span>
                ) : alertSettings?.updated_at ? (
                  <span className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Updated {formatDateTime(alertSettings.updated_at)}
                  </span>
                ) : null}
              </div>

              {canManageAnomalyAlerts ? (
              <div className="mt-4 space-y-4">
                <label className="flex items-start gap-3 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={anomalyAlertsEnabled}
                    onChange={(event) => setAnomalyAlertsEnabled(event.target.checked)}
                  />
                  <span>
                    <span className="block text-sm font-semibold text-[#1F2937]" style={fontBody}>
                      Enable anomaly alerts
                    </span>
                    <span className="mt-1 block text-[11px] text-gray-500" style={fontBody}>
                      Alerts are sent after forecast training when the latest completed data is unusually different from the site's recent pattern.
                    </span>
                  </span>
                </label>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                    <label className="flex items-center gap-2 text-sm font-semibold text-[#1F2937]" style={fontBody}>
                      <input
                        type="checkbox"
                        checked={slackAlertsEnabled}
                        onChange={(event) => setSlackAlertsEnabled(event.target.checked)}
                      />
                      Slack
                    </label>
                    <div className="mt-2 text-[11px] text-gray-500" style={fontBody}>
                      Paste a Slack incoming webhook URL. Saved webhooks are hidden after save.
                    </div>
                    <input
                      type="password"
                      className="mt-3 w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                      style={fontBody}
                      value={slackWebhookUrl}
                      onChange={(event) => {
                        setSlackWebhookUrl(event.target.value);
                        setClearSlackWebhook(false);
                      }}
                      placeholder={slackWebhookUrlSet && !clearSlackWebhook ? "Webhook saved. Paste a new URL to replace it." : "https://hooks.slack.com/services/..."}
                    />
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {slackWebhookUrlSet && !clearSlackWebhook ? (
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-700" style={fontBody}>
                          Webhook saved
                        </span>
                      ) : null}
                      {clearSlackWebhook ? (
                        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-700" style={fontBody}>
                          Webhook will be removed
                        </span>
                      ) : null}
                      {slackWebhookUrlSet ? (
                        <button
                          type="button"
                          onClick={() => {
                            setClearSlackWebhook(true);
                            setSlackAlertsEnabled(false);
                            setSlackWebhookUrl("");
                          }}
                          className="text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-500 hover:text-[#8B2635]"
                          style={fontBody}
                        >
                          Remove webhook
                        </button>
                      ) : null}
                    </div>
                  </div>

                  <div className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                    <label className="flex items-center gap-2 text-sm font-semibold text-[#1F2937]" style={fontBody}>
                      <input
                        type="checkbox"
                        checked={emailAlertsEnabled}
                        onChange={(event) => setEmailAlertsEnabled(event.target.checked)}
                      />
                      Email
                    </label>
                    <div className="mt-2 text-[11px] text-gray-500" style={fontBody}>
                      Enter one recipient per line or separate recipients with commas.
                    </div>
                    <textarea
                      className="mt-3 min-h-[90px] w-full border border-gray-200 bg-white px-2.5 py-2 text-sm text-[#1F2937]"
                      style={fontBody}
                      value={emailRecipientsDraft}
                      onChange={(event) => setEmailRecipientsDraft(event.target.value)}
                      placeholder="ops@example.com"
                    />
                    <div className="mt-2 text-[11px] text-gray-500" style={fontBody}>
                      {alertSettings?.email_delivery_configured
                        ? "Email delivery is configured for this environment."
                        : "Email recipients can be saved now. Outbound email sends after SMTP is configured."}
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void saveAlertSettings()}
                    disabled={alertStatus === "loading" || alertStatus === "saving"}
                    className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    {alertStatus === "saving" ? "Saving..." : "Save alerts"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void refreshAlertSettings()}
                    disabled={alertStatus === "loading" || alertStatus === "saving"}
                    className="border border-gray-300 bg-white px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 hover:border-gray-400"
                    style={fontBody}
                  >
                    Reset
                  </button>
                </div>
                {alertMessage ? (
                  <div className={`text-[11px] ${alertStatusClassName}`} style={fontBody}>
                    {alertMessage}
                  </div>
                ) : null}
              </div>
              ) : (
                <div className="mt-4 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                  <div className="text-sm text-[#1F2937]" style={fontBody}>
                    Anomaly alerts are available on Standard.
                  </div>
                  <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                    Upgrade when you want Slack or email notifications for unusual traffic, conversion, or revenue patterns.
                  </div>
                  <button
                    type="button"
                    onClick={() => void beginCheckout("standard")}
                    disabled={billingActionDisabled}
                    className="mt-3 border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                    style={fontBody}
                  >
                    Upgrade to Standard
                  </button>
                </div>
              )}
            </section>

            <section id="shields" className={`${activeSettingsPanel === "shields" ? "" : "hidden"} scroll-mt-6 border border-gray-200 bg-white p-5`}>
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

            <section id="billing" className={`${activeSettingsPanel === "billing" ? "" : "hidden"} scroll-mt-6 border border-gray-200 bg-white p-5`}>
              <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                Plan & billing
              </div>
              <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                Manage this site's current plan and forecasting features.
              </div>
              <div className="mt-4 border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                  Subscription
                </div>
                <div className="mt-2 text-sm text-[#1F2937]" style={fontBody}>
                  Current plan: <span className="font-semibold">{planDisplayName}</span>
                </div>
                <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                  {billingStatusText}
                </div>
                <button
                  type="button"
                  onClick={() => void beginCheckout(billingCheckoutPlan)}
                  disabled={billingActionDisabled}
                  className="mt-3 border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                  style={fontBody}
                >
                  {billingActionLabel}
                </button>
                <div className="mt-4 border-t border-gray-100 pt-3">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                    Standard adds
                  </div>
                  <ul className="mt-2 grid gap-1 text-[11px] text-gray-600" style={fontBody}>
                    <li>3 sites included, then $5 per additional site</li>
                    <li>Historical imports and forever aggregate retention</li>
                    <li>Anomaly alerts for Slack and email</li>
                    <li>All forecast metrics when enough history is available</li>
                    <li>Team/site access management</li>
                  </ul>
                  {billingDetails ? (
                    <div className="mt-3 text-[11px] text-gray-500" style={fontBody}>
                      This owner has {formatNumber(billingDetails.owned_site_count)} site
                      {billingDetails.owned_site_count === 1 ? "" : "s"}.{" "}
                      {billingDetails.additional_site_count > 0
                        ? `${formatNumber(billingDetails.additional_site_count)} additional site${
                            billingDetails.additional_site_count === 1 ? "" : "s"
                          } should be billed after the included ${formatNumber(billingDetails.included_sites)}.`
                        : `Included sites: ${formatNumber(billingDetails.included_sites)}.`}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            <section id="imports" className={`${activeSettingsPanel === "imports" ? "" : "hidden"} scroll-mt-6 border border-gray-200 bg-white p-5`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-[#111827]" style={fontBody}>
                    Imports & exports
                  </div>
                  <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                    Import historical data for long-range trends and forecasts.
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
                        setImportPreview(null);
                        setImportPreviewStatus("idle");
                        setImportPreviewMessage(null);
                        setImportStatus("idle");
                        setImportMessage(null);
                      }}
                      placeholder={"day,metric,value\n2026-01-01,pageviews,1200\n2026-01-01,revenue,340.5"}
                    />
                    <div className="mt-1 text-[11px] text-gray-500" style={fontBody}>
                      Required columns: day, metric, value. Metrics: pageviews, uniques, sessions, conversions, revenue.
                    </div>
                  </div>
                  {importPreview || importPreviewMessage ? (
                    <div className="border border-[var(--color-border-subtle)] bg-[#FCFEFE] px-3 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.16em] text-gray-500" style={fontMeta}>
                            Preview
                          </div>
                          <div className={`mt-1 text-[12px] ${importPreviewStatusClassName}`} style={fontBody}>
                            {importPreviewMessage ?? "Preview the CSV before importing."}
                          </div>
                        </div>
                        {importPreview ? (
                          <span
                            className={`rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${statusToneClass(
                              importPreview.valid ? "ok" : "error"
                            )}`}
                            style={fontBody}
                          >
                            {importPreview.valid ? "Ready" : "Needs review"}
                          </span>
                        ) : null}
                      </div>
                      {importPreview ? (
                        <div className="mt-3 grid gap-2 md:grid-cols-3">
                          <div className="border border-gray-100 bg-white px-2.5 py-2">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                              Rows
                            </div>
                            <div className="mt-1 metric-number text-lg text-[#1F2937]" style={fontMetric}>
                              {formatNumber(importPreview.row_count)}
                            </div>
                          </div>
                          <div className="border border-gray-100 bg-white px-2.5 py-2">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                              Dates
                            </div>
                            <div className="mt-1 text-sm text-[#1F2937]" style={fontBody}>
                              {importPreview.start_day && importPreview.end_day
                                ? `${formatShortDate(importPreview.start_day)} - ${formatShortDate(importPreview.end_day)}`
                                : "-"}
                            </div>
                          </div>
                          <div className="border border-gray-100 bg-white px-2.5 py-2">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-gray-500" style={fontMeta}>
                              Metrics
                            </div>
                            <div className="mt-1 text-sm text-[#1F2937]" style={fontBody}>
                              {importPreview.metrics.join(", ") || "-"}
                            </div>
                          </div>
                        </div>
                      ) : null}
                      {importPreview?.errors.length ? (
                        <div className="mt-3 rounded border border-[#FECACA] bg-[#FFF7F7] px-3 py-2 text-[11px] text-[#8B2635]" style={fontBody}>
                          <div className="font-semibold">Fix these rows before importing:</div>
                          <ul className="mt-1 list-disc space-y-1 pl-4">
                            {importPreview.errors.slice(0, 5).map((error) => (
                              <li key={error}>{error}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {importPreview?.live_overlaps.length ? (
                        <div className="mt-3 rounded border border-[#FECACA] bg-[#FFF7F7] px-3 py-2 text-[11px] text-[#8B2635]" style={fontBody}>
                          <div className="font-semibold">This overlaps Valid-collected data.</div>
                          <div className="mt-1">
                            Remove these dates from the CSV before importing:{" "}
                            {importPreview.live_overlaps
                              .slice(0, 6)
                              .map((overlap) => `${formatShortDate(overlap.day)} ${overlap.metric}`)
                              .join(", ")}
                            {importPreview.live_overlaps.length > 6 ? `, and ${importPreview.live_overlaps.length - 6} more` : ""}.
                          </div>
                        </div>
                      ) : null}
                      {importPreview?.replaceable_import_overlaps.length ? (
                        <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800" style={fontBody}>
                          <div className="font-semibold">Some rows replace a previous import.</div>
                          <div className="mt-1">
                            Matching imported rows will be replaced, not double-counted:{" "}
                            {importPreview.replaceable_import_overlaps
                              .slice(0, 6)
                              .map((overlap) => `${formatShortDate(overlap.day)} ${overlap.metric}`)
                              .join(", ")}
                            {importPreview.replaceable_import_overlaps.length > 6
                              ? `, and ${importPreview.replaceable_import_overlaps.length - 6} more`
                              : ""}.
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => void previewHistoricalImport()}
                      disabled={importPreviewStatus === "loading" || !importCsvText.trim()}
                      className="border border-[#4f46e5] bg-[#4f46e5] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[#3730a3]"
                      style={fontBody}
                    >
                      {importPreviewStatus === "loading" ? "Previewing..." : "Preview import"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitHistoricalImport()}
                      disabled={!canSubmitHistoricalImport}
                      className="border border-gray-900 bg-gray-900 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-800"
                      style={fontBody}
                    >
                      {importStatus === "loading" ? "Importing..." : "Import historical data"}
                    </button>
                    {importCsvText ? (
                      <button
                        type="button"
                        onClick={() => {
                          setImportCsvText("");
                          setImportPreview(null);
                          setImportPreviewStatus("idle");
                          setImportPreviewMessage(null);
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
                      ? "Upgrade from Solo to bring in prior analytics data and use it for long-range trends and forecasts."
                      : "This import path uses Standard aggregate storage and is not available for the current plan."}
                  </div>
                  {billingPlan === "free" ? (
                    <button
                      type="button"
                      onClick={() => void beginCheckout("standard")}
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

          </div>
        </div>
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
    return <DashboardLoadingSkeleton label={en.loading} />;
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
    return <DashboardLoadingSkeleton label={en.loading} />;
  }
  if (authEnabled && !token) {
    return <LoginGate />;
  }

  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true }}>
      <ErrorBoundary>
        <Suspense fallback={<DashboardLoadingSkeleton label={en.loading} />}>
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
      </ErrorBoundary>
    </BrowserRouter>
  );
};
