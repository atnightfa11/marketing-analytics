import React, { Suspense, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AggregateWindow,
  BreakdownDimension,
  BreakdownRow,
  fetchAggregate,
  fetchBreakdown,
  fetchForecast,
  ForecastEntry,
  ForecastResponse,
  resolveActiveSiteId,
} from "./api";
import { AlertsPanel } from "./components/AlertsPanel";
import { DeviceBreakdown } from "./components/DeviceBreakdown";
import { KPIGrid } from "./components/KPIGrid";
import { PrivacyControls } from "./components/PrivacyControls";
import { TopCountries } from "./components/TopCountries";
import { TopSources } from "./components/TopSources";
import { useAuth } from "./hooks/useAuth";
import { formatNumber, formatPercent, formatShortDate } from "./utils/format";
import en from "./locales/en.json";

const fontHeading: React.CSSProperties = { fontFamily: '"Playfair Display", serif' };
const fontBody: React.CSSProperties = {
  fontFamily: '"Inter", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
};
const fontNumeric: React.CSSProperties = {
  fontFamily:
    '"Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
};

const metricLabels: Record<string, string> = {
  uniques: "Unique Visitors",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
  avg_pages_per_visit: "Avg. Pages per Visit",
  bounce_rate: "Bounce Rate",
  visit_duration: "Visit Duration",
  revenue: "Revenue",
};

const metricOptions = [
  { key: "pageviews", label: "Pageviews" },
  { key: "uniques", label: "Unique Visitors" },
  { key: "sessions", label: "Sessions" },
  { key: "conversions", label: "Conversions" },
  { key: "revenue", label: "Revenue" },
  { key: "avg_pages_per_visit", label: "Avg. Pages per Visit" },
  { key: "visit_duration", label: "Visit Duration" },
  { key: "bounce_rate", label: "Bounce Rate" },
];
const aggregateMetricKeys = ["pageviews", "uniques", "sessions", "conversions", "revenue"] as const;
const breakdownDimensions: BreakdownDimension[] = ["sources", "pages", "devices", "countries", "conversions"];

const rangeOptions = ["Today", "Yesterday", "Last 7", "Last 30", "Last 90", "MTD", "YTD", "Custom"] as const;
const forecastOptions = [
  { key: "7d", label: "7 days", kind: "days", days: 7 },
  { key: "30d", label: "30d", kind: "days", days: 30 },
  { key: "60d", label: "60d", kind: "days", days: 60 },
  { key: "90d", label: "90d", kind: "days", days: 90 },
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
  new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const safeRatio = (numerator: number, denominator: number) =>
  Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0 ? numerator / denominator : Number.NaN;

const deriveBounceRate = (sessions: number, pageviews: number, conversions: number) => {
  if (!Number.isFinite(sessions) || sessions <= 0) return Number.NaN;
  const extraPageviews = Math.max(0, pageviews - sessions);
  const engagedByPageDepth = Math.min(sessions, extraPageviews);
  const engagedByConversions = Math.min(sessions, Math.max(0, conversions));
  const engagedSessions = Math.min(sessions, engagedByPageDepth + engagedByConversions);
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
const formatIsoDate = (date: Date) => date.toISOString().slice(0, 10);
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

interface TableRow {
  label: string;
  value: number;
}

interface DetailTotals {
  sessions: number;
  conversions: number;
  revenue: number;
  bounceRate: number;
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const TableBlock: React.FC<{
  title: string;
  labelHeader: string;
  rows: TableRow[];
  valueLabel: string;
  metricKey: string;
  detailTotals: DetailTotals;
  emptyState?: string;
}> = ({ title, labelHeader, rows, valueLabel, metricKey, detailTotals, emptyState }) => {
  const [showDetails, setShowDetails] = useState(false);
  const maxValue = rows.reduce((max, row) => Math.max(max, row.value), 0);
  const totalValue = rows.reduce((sum, row) => sum + row.value, 0);

  return (
    <div className="border border-gray-200 bg-white p-4">
      <div className="mb-3 text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
        {title}
      </div>
      <div className="flex items-center justify-between border-b border-gray-200 pb-2 text-xs text-gray-500">
        <span style={fontBody}>{labelHeader}</span>
        <span style={fontBody}>{valueLabel}</span>
      </div>
      {rows.length === 0 ? (
        <div className="py-6 text-xs text-gray-400" style={fontBody}>
          {emptyState ?? "Awaiting events. This table will populate after data arrives."}
        </div>
      ) : (
        <div className="divide-y divide-gray-100">
          {rows.map((row, index) => {
            const width = maxValue > 0 ? Math.max(4, (row.value / maxValue) * 100) : 0;
            const share = totalValue > 0 ? row.value / totalValue : 0;
            const bounce =
              totalValue > 0
                ? clamp(detailTotals.bounceRate + (index - (rows.length - 1) / 2) * 0.018, 0.1, 0.9)
                : detailTotals.bounceRate;
            const detailSessions = detailTotals.sessions * share;
            const detailConversions = detailTotals.conversions * share;
            const detailRevenue = detailTotals.revenue * share;
            return (
              <div key={row.label} className="py-2">
                <div className="flex items-center justify-between text-sm text-gray-700">
                  <span style={fontBody}>{row.label}</span>
                  <span className="text-right text-gray-900" style={fontNumeric}>
                    {formatMetricValue(metricKey, row.value)}
                  </span>
                </div>
                <div className="mt-1 h-1 w-full bg-gray-100">
                  <div className="h-1 bg-gray-400" style={{ width: `${width}%` }} />
                </div>
                {showDetails && (
                  <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] text-gray-500">
                    <div>
                      <div className="uppercase tracking-[0.2em]" style={fontBody}>
                        Sessions
                      </div>
                      <div className="mt-1 text-xs text-gray-900" style={fontNumeric}>
                        {formatNumber(detailSessions)}
                      </div>
                    </div>
                    <div>
                      <div className="uppercase tracking-[0.2em]" style={fontBody}>
                        Bounce
                      </div>
                      <div className="mt-1 text-xs text-gray-900" style={fontNumeric}>
                        {formatPercent(bounce)}
                      </div>
                    </div>
                    <div>
                      <div className="uppercase tracking-[0.2em]" style={fontBody}>
                        Conversions
                      </div>
                      <div className="mt-1 text-xs text-gray-900" style={fontNumeric}>
                        {formatNumber(detailConversions)}
                      </div>
                    </div>
                    <div>
                      <div className="uppercase tracking-[0.2em]" style={fontBody}>
                        Revenue
                      </div>
                      <div className="mt-1 text-xs text-gray-900" style={fontNumeric}>
                        {formatMetricValue("revenue", detailRevenue)}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {rows.length > 0 && (
        <button
          type="button"
          onClick={() => setShowDetails((prev) => !prev)}
          className="mx-auto mt-3 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-gray-500"
          style={fontBody}
        >
          {showDetails ? "[x] Details" : "[ ] Details"}
        </button>
      )}
    </div>
  );
};

const Overview: React.FC = () => {
  const { token, authEnabled } = useAuth();
  const canQuery = !authEnabled || Boolean(token);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { siteId: pathSiteId } = useParams<{ siteId?: string }>();
  const querySiteId = searchParams.get("site_id") ?? undefined;
  const hasExplicitSiteSelection = Boolean((querySiteId && querySiteId.trim()) || (pathSiteId && pathSiteId.trim()));
  const showSeededBreakdowns = !hasExplicitSiteSelection;
  const siteId = useMemo(() => resolveActiveSiteId(querySiteId ?? pathSiteId), [querySiteId, pathSiteId]);

  useEffect(() => {
    const query = querySiteId?.trim();
    if (!pathSiteId && query) {
      navigate(`/site/${encodeURIComponent(query)}`, { replace: true });
    }
  }, [navigate, pathSiteId, querySiteId]);
  const [selectedMetric, setSelectedMetric] = useState("pageviews");
  const [range, setRange] = useState<RangeOption>("Last 30");
  const [forecastKey, setForecastKey] = useState<(typeof forecastOptions)[number]["key"]>("30d");
  const [forecast, setForecast] = useState<ForecastEntry[]>([]);
  const [forecastMeta, setForecastMeta] = useState<Pick<ForecastResponse, "mape" | "has_anomaly"> | null>(
    null
  );
  const [aggregateMap, setAggregateMap] = useState<Record<string, AggregateWindow[]>>({});
  const [breakdownRows, setBreakdownRows] = useState<Record<BreakdownDimension, TableRow[]>>({
    sources: [],
    pages: [],
    devices: [],
    countries: [],
    conversions: [],
  });
  const [liveWindows, setLiveWindows] = useState<AggregateWindow[]>([]);
  const [customRange, setCustomRange] = useState<DateRange>({ start: "", end: "" });
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [compareMode, setCompareMode] = useState<"previous" | "custom">("previous");
  const [compareRange, setCompareRange] = useState<DateRange>({ start: "", end: "" });
  const [exportMode, setExportMode] = useState<"current" | "all">("current");
  useEffect(() => {
    if (!canQuery) return;
    const metricsToFetch = [...aggregateMetricKeys];
    Promise.all(
      metricsToFetch.map((metric) =>
        fetchAggregate(metric, "standard", token ?? undefined, siteId).then((data) => ({
          metric,
          data,
        }))
      )
    )
      .then((results) => {
        const next: Record<string, AggregateWindow[]> = {};
        results.forEach((item) => {
          next[item.metric] = item.data;
        });
        setAggregateMap(next);
      })
      .catch(console.error);
  }, [canQuery, token, siteId]);

  useEffect(() => {
    if (!canQuery) return;
    if (!aggregateMetricKeys.includes(selectedMetric as (typeof aggregateMetricKeys)[number])) {
      setForecast([]);
      setForecastMeta(null);
      return;
    }
    fetchForecast(token, selectedMetric, siteId)
      .then((data) => {
        setForecast(data.forecast);
        setForecastMeta({ mape: data.mape, has_anomaly: data.has_anomaly });
      })
      .catch(console.error);
  }, [canQuery, token, selectedMetric, siteId]);

  useEffect(() => {
    if (!canQuery) return;
    const loadLive = () => fetchAggregate("uniques", "live", token ?? undefined, siteId).then(setLiveWindows).catch(console.error);
    loadLive();
    const interval = setInterval(loadLive, 30000);
    return () => clearInterval(interval);
  }, [canQuery, token, siteId]);

  const toDaily = (windows: AggregateWindow[]) => {
    const bucket: Record<string, number> = {};
    windows.forEach((window) => {
      const day = window.window_start.slice(0, 10);
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
    const minDate = parseDay(entries[0].day);
    const maxDate = parseDay(entries[entries.length - 1].day);
    const clampDate = (date: Date) =>
      new Date(Math.min(Math.max(date.getTime(), minDate.getTime()), maxDate.getTime()));
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const endDate = clampDate(today);

    if (rangeKey === "Custom") {
      if (!custom.start || !custom.end) return entries;
      const startCandidate = clampDate(parseDay(custom.start));
      const endCandidate = clampDate(parseDay(custom.end));
      const start = startCandidate <= endCandidate ? startCandidate : endCandidate;
      const end = startCandidate <= endCandidate ? endCandidate : startCandidate;
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= start && day <= end;
      });
    }
    if (rangeKey === "Today") {
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= endDate && day <= endDate;
      });
    }
    if (rangeKey === "Yesterday") {
      const start = new Date(endDate);
      start.setDate(start.getDate() - 1);
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= start && day <= start;
      });
    }
    if (rangeKey === "Last 7" || rangeKey === "Last 30" || rangeKey === "Last 90") {
      const days = rangeKey === "Last 7" ? 7 : rangeKey === "Last 30" ? 30 : 90;
      const start = new Date(endDate);
      start.setDate(start.getDate() - (days - 1));
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= start && day <= endDate;
      });
    }
    if (rangeKey === "MTD") {
      const start = new Date(endDate.getFullYear(), endDate.getMonth(), 1);
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= start && day <= endDate;
      });
    }
    if (rangeKey === "YTD") {
      const start = new Date(endDate.getFullYear(), 0, 1);
      return entries.filter((entry) => {
        const day = parseDay(entry.day);
        return day >= start && day <= endDate;
      });
    }
    return entries;
  };

  const buildRows = (labels: string[], weights: number[], total: number) => {
    if (!Number.isFinite(total) || total <= 0) return [];
    const weightSum = weights.reduce((sum, weight) => sum + weight, 0) || 1;
    return labels.map((label, index) => {
      const share = weights[index] / weightSum;
      const rawValue = total * share;
      const value = Math.round(rawValue);
      return { label, value };
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

  const pageviewsAll = useMemo(() => toDaily(aggregateMap.pageviews ?? []), [aggregateMap]);
  const uniquesAll = useMemo(() => toDaily(aggregateMap.uniques ?? []), [aggregateMap]);
  const sessionsAll = useMemo(() => toDaily(aggregateMap.sessions ?? []), [aggregateMap]);
  const conversionsAll = useMemo(() => toDaily(aggregateMap.conversions ?? []), [aggregateMap]);
  const revenueAll = useMemo(() => toDaily(aggregateMap.revenue ?? []), [aggregateMap]);
  const durationAll = useMemo(() => toDaily(aggregateMap.avg_time_on_site ?? []), [aggregateMap]);

  const dailyPageviews = useMemo(() => filterByRange(pageviewsAll, range, customRange), [pageviewsAll, range, customRange]);
  const dailyUniques = useMemo(() => filterByRange(uniquesAll, range, customRange), [uniquesAll, range, customRange]);
  const dailySessions = useMemo(() => filterByRange(sessionsAll, range, customRange), [sessionsAll, range, customRange]);
  const dailyConversions = useMemo(
    () => filterByRange(conversionsAll, range, customRange),
    [conversionsAll, range, customRange]
  );
  const dailyRevenue = useMemo(() => filterByRange(revenueAll, range, customRange), [revenueAll, range, customRange]);
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
    const conversionsMap = mapByDay(conversionsAll);
    const days = Array.from(new Set([...sessionsMap.keys(), ...pageviewsMap.keys(), ...conversionsMap.keys()])).sort((a, b) =>
      a.localeCompare(b)
    );
    return makeDerivedSeries(days, (day) =>
      deriveBounceRate(sessionsMap.get(day) ?? Number.NaN, pageviewsMap.get(day) ?? Number.NaN, conversionsMap.get(day) ?? 0)
    );
  }, [pageviewsAll, sessionsAll, conversionsAll]);

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

  const dailySelectedAll = useMemo(() => getUnfilteredSeries(selectedMetric), [selectedMetric, aggregateMap]);
  const dailySelected = useMemo(() => getDailySeries(selectedMetric), [selectedMetric, aggregateMap, range, customRange]);
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
    if (!canQuery) return;
    if (showSeededBreakdowns) {
      setBreakdownRows({
        sources: [],
        pages: [],
        devices: [],
        countries: [],
        conversions: [],
      });
      return;
    }

    let cancelled = false;
    const start = breakdownDateRange?.start;
    const end = breakdownDateRange?.end;
    Promise.all(
      breakdownDimensions.map((dimension) =>
        fetchBreakdown(dimension, token ?? undefined, siteId, start, end).then((rows) => ({
          dimension,
          rows,
        }))
      )
    )
      .then((results) => {
        if (cancelled) return;
        const next: Record<BreakdownDimension, TableRow[]> = {
          sources: [],
          pages: [],
          devices: [],
          countries: [],
          conversions: [],
        };
        results.forEach((result) => {
          next[result.dimension] = result.rows.map((row: BreakdownRow) => ({
            label: row.label,
            value: row.value,
          }));
        });
        setBreakdownRows(next);
      })
      .catch(console.error);

    return () => {
      cancelled = true;
    };
  }, [canQuery, showSeededBreakdowns, token, siteId, breakdownDateRange?.start, breakdownDateRange?.end]);

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
    const bounceRate = deriveBounceRate(sessions, pageviews, conversions);
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
  const liveValue = liveWindows.reduce((sum, window) => sum + window.value, 0);
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

  const primaryLabel = metricLabels[selectedMetric] ?? selectedMetric;
  const lastActualDay = dailySelected.length > 0 ? dailySelected[dailySelected.length - 1].day : null;
  const primaryRangeBounds = useMemo(() => {
    if (dailySelected.length === 0) return null;
    return { start: dailySelected[0].day, end: dailySelected[dailySelected.length - 1].day };
  }, [dailySelected]);

  const selectedForecast =
    (forecastOptions.find((option) => option.key === forecastKey) as ForecastOption) ??
    (forecastOptions.find((option) => option.key === "30d") as ForecastOption);
  const forecastWindow = useMemo(
    () => resolveForecastWindow(forecast, lastActualDay, selectedForecast),
    [forecast, lastActualDay, selectedForecast]
  );

  const forecastLabel = forecastWindow.label;
  const forecastHorizon = forecastWindow.entries;

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
    return filterByWindow(entries, bounds.start, bounds.end);
  };

  const getComparisonSeries = (metric: string) => getSeriesForBounds(metric, comparisonBounds);

  const comparisonAligned = useMemo(() => {
    if (!compareEnabled) return new Map<string, number>();
    const compareEntries = getComparisonSeries(selectedMetric);
    if (compareEntries.length === 0 || dailySelected.length === 0) return new Map<string, number>();
    const minLength = Math.min(dailySelected.length, compareEntries.length);
    const primarySlice = dailySelected.slice(dailySelected.length - minLength);
    const compareSlice = compareEntries.slice(compareEntries.length - minLength);
    const map = new Map<string, number>();
    primarySlice.forEach((row, index) => {
      const compareValue = compareSlice[index]?.value;
      if (Number.isFinite(compareValue)) {
        map.set(row.day, compareValue);
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
  const chartData = useMemo(() => {
    const actualSeries = dailySelected.map((row) => ({
      day: row.day,
      actual: row.value,
      compare: comparisonAligned.get(row.day) ?? null,
      projected: null,
      upper: null,
      lower: null,
    }));
    const lastActual = actualSeries.length > 0 ? actualSeries[actualSeries.length - 1].day : null;
    const projectedSeries = forecastHorizon
      .filter((entry) => (!lastActual ? true : entry.day > lastActual))
      .map((entry) => ({
        day: entry.day,
        actual: null,
        projected: entry.yhat,
        upper: entry.yhat_upper,
        lower: entry.yhat_lower,
      }));
    return [...actualSeries, ...projectedSeries].sort((a, b) => a.day.localeCompare(b.day));
  }, [dailySelected, forecastHorizon, comparisonAligned]);

  const hasActual = chartData.some((point) => point.actual !== null);
  const hasCompare = chartData.some((point) => point.compare !== null);
  const hasProjected = chartData.some((point) => point.projected !== null);
  const hasBounds = chartData.some((point) => point.upper !== null || point.lower !== null);

  const selectedTotal = totals.pageviews ?? 0;
  const topSources = useMemo(
    () =>
      showSeededBreakdowns
        ? buildRows(["Organic Search", "Direct", "Referral", "Social", "Email"], [0.36, 0.22, 0.16, 0.14, 0.12], selectedTotal)
        : breakdownRows.sources,
    [showSeededBreakdowns, selectedTotal, breakdownRows.sources]
  );
  const topPages = useMemo(
    () =>
      showSeededBreakdowns
        ? buildRows(["/", "/pricing", "/blog/privacy", "/docs/setup", "/about"], [0.3, 0.22, 0.18, 0.16, 0.14], selectedTotal)
        : breakdownRows.pages,
    [showSeededBreakdowns, selectedTotal, breakdownRows.pages]
  );
  const deviceRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildRows(["Mobile", "Desktop", "Tablet"], [0.58, 0.34, 0.08], selectedTotal)
        : breakdownRows.devices,
    [showSeededBreakdowns, selectedTotal, breakdownRows.devices]
  );
  const regionRows = useMemo(
    () =>
      showSeededBreakdowns
        ? buildRows(
            ["United States", "United Kingdom", "Canada", "Germany", "France", "Netherlands", "Australia", "Sweden", "India", "Japan"],
            [0.28, 0.12, 0.09, 0.08, 0.07, 0.06, 0.06, 0.05, 0.1, 0.09],
            selectedTotal
          )
        : breakdownRows.countries,
    [showSeededBreakdowns, selectedTotal, breakdownRows.countries]
  );
  const overallBounceRate = Number.isFinite(totals.bounce_rate) ? clamp(totals.bounce_rate, 0, 1) : 0.5;
  const detailTotals: DetailTotals = {
    sessions: totals.sessions,
    conversions: totals.conversions,
    revenue: totals.revenue,
    bounceRate: overallBounceRate,
  };
  const mapeValue = forecastMeta?.mape ?? Number.NaN;
  const forecastMape = Number.isFinite(mapeValue) ? `${(mapeValue * 100).toFixed(1)}%` : "—";
  const mapeClass = Number.isFinite(mapeValue)
    ? mapeValue <= 0.1
      ? "text-emerald-600"
      : "text-amber-600"
    : "text-gray-400";
  const chartFormatter = (value: number) => {
    if (selectedMetric === "revenue") return formatCompactCurrency(value);
    if (selectedMetric === "bounce_rate") return formatPercent(value);
    if (selectedMetric === "visit_duration") return formatDuration(value);
    if (selectedMetric === "avg_pages_per_visit") return value.toFixed(2);
    return formatNumber(value);
  };
  const todayKey = new Date().toISOString().slice(0, 10);
  const showTodayLine =
    chartData.length > 0 &&
    todayKey >= chartData[0].day &&
    todayKey <= chartData[chartData.length - 1].day;

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
      const actualEntries = getDailySeries(metric, range, customRange);
      const actualByDay = new Map(actualEntries.map((row) => [row.day, row.value]));
      const lastDay = actualEntries.length > 0 ? actualEntries[actualEntries.length - 1].day : null;
      const metricForecast = forecastMap.get(metric) ?? [];
      const metricWindow = resolveForecastWindow(metricForecast, lastDay, selectedForecast);
      const forecastByDay = new Map(metricWindow.entries.map((entry) => [entry.day, entry]));
      const days = Array.from(new Set([...actualByDay.keys(), ...forecastByDay.keys()])).sort((a, b) =>
        a.localeCompare(b)
      );
      const toCell = (value?: number) => {
        if (!Number.isFinite(value)) return "";
        return metric === "revenue" ? value.toFixed(2) : value.toFixed(0);
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
      if (!Number.isFinite(value)) return "";
      if (isRate || isRatio) return value.toFixed(4);
      if (isDuration) return value.toFixed(1);
      if (isRevenue) return value.toFixed(2);
      return value.toFixed(0);
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
  const forecastTotal = forecastHorizon.reduce((sum, entry) => sum + entry.yhat, 0);
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

  const conversionEvents = useMemo(() => {
    if (!showSeededBreakdowns) {
      return breakdownRows.conversions.map((row) => ({
        label: row.label,
        count: row.value,
        rate: totals.sessions > 0 ? row.value / totals.sessions : 0,
      }));
    }
    if (!Number.isFinite(totals.conversions) || totals.conversions <= 0) return [];
    const labels = ["Demo Request", "Contact Us", "Trial Signup", "Purchase", "Newsletter"];
    const weights = [0.34, 0.22, 0.18, 0.16, 0.1];
    const total = totals.conversions;
    return labels.map((label, index) => {
      const share = weights[index] / weights.reduce((sum, value) => sum + value, 0);
      const count = Math.max(1, Math.round(total * share));
      const rate = totals.sessions > 0 ? count / totals.sessions : 0;
      return { label, count, rate };
    });
  }, [showSeededBreakdowns, breakdownRows.conversions, totals.conversions, totals.sessions]);

  return (
    <div className="min-h-screen bg-[#F9FAFB] print-bg">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
            Valid
          </div>
          <div className="flex flex-wrap items-center gap-4 no-print">
            <span className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Date Range
            </span>
            <select
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
            {range === "Custom" && (
              <div className="flex items-center gap-1">
                <input
                  type="date"
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
            <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.2em] text-gray-500">
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
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
                      className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
                      className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
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
            <span className="ml-3 text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Forecast
            </span>
            <select
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
              style={fontBody}
              value={forecastKey}
              onChange={(event) => setForecastKey(event.target.value as (typeof forecastOptions)[number]["key"])}
            >
              {forecastOptions.map((option) => {
                const referenceDate = lastActualDay ? parseDay(lastActualDay) : new Date();
                const optionLabel =
                  option.kind === "quarter" ? getQuarterWindow(option.quarter, referenceDate).label : option.label;
                return (
                  <option key={option.key} value={option.key}>
                    {optionLabel}
                  </option>
                );
              })}
            </select>
            <span className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              CSV
            </span>
            <select
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#1F2937]"
              style={fontBody}
              value={exportMode}
              onChange={(event) => setExportMode(event.target.value as "current" | "all")}
            >
              <option value="current">Selected metric</option>
              <option value="all">All metrics</option>
            </select>
            <button
              type="button"
              onClick={handleExportCsv}
              className="border border-gray-200 bg-white px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-gray-500"
              style={fontBody}
            >
              Export CSV
            </button>
            <button
              type="button"
              onClick={handleExportPdf}
              className="border border-gray-200 bg-white px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-gray-500"
              style={fontBody}
            >
              Export PDF
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-6 pb-10 pt-6 print-container">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-lg text-[#1F2937]" style={fontHeading}>
              Overview
            </div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Site: {siteId}
            </div>
            {!showSeededBreakdowns && (
              <div className="mt-1 text-[10px] uppercase tracking-[0.2em] text-gray-400" style={fontBody}>
                Live mode: KPI/chart totals and breakdown panels use real data.
              </div>
            )}
          </div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
            Metrics · {range}
          </div>
        </div>
        <KPIGrid
          values={totals}
          comparisonValues={kpiComparisonValues}
          comparisonLabel={kpiComparisonLabel}
          selectedMetric={selectedMetric}
          onSelectMetric={setSelectedMetric}
        />
        <section className="border border-gray-200 bg-white p-4">
          <div className="border-b border-gray-200 pb-3">
            <div className="flex flex-wrap items-center gap-4 text-[10px] uppercase tracking-[0.2em] text-gray-500">
              <span style={fontBody}>
                Live visitors{" "}
                <span className="ml-1 text-[#1F2937]" style={fontNumeric}>
                  {formatNumber(liveValue)}
                </span>
              </span>
              <span style={fontBody}>
                Last updated{" "}
                <span className="ml-1 text-[#1F2937]" style={fontNumeric}>
                  {lastActualDay ? formatShortDate(lastActualDay) : "—"}
                </span>
              </span>
              <span style={fontBody}>
                Forecast {forecastLabel}{" "}
                <span className="ml-1 text-[#1F2937]" style={fontNumeric}>
                  {forecast.length > 0 ? formatMetricValue(selectedMetric, forecastTotal) : "—"}
                </span>
              </span>
              <span style={fontBody}>
                MAPE{" "}
                <span className={`ml-1 ${mapeClass}`} style={fontNumeric}>
                  {forecastMape}
                </span>
              </span>
              {forecastMeta?.has_anomaly && (
                <span className="text-[#8B2635]" style={fontBody}>
                  Anomaly flagged
                </span>
              )}
            </div>
          </div>
          <div className="mt-4">
            {chartData.length === 0 ? (
              <div className="py-10 text-sm text-gray-400" style={fontBody}>
                No chart data yet. Seed events, run the reducer, and reload.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartData}>
                  <CartesianGrid stroke="#E5E7EB" strokeDasharray="2 6" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tickFormatter={formatAxisDate}
                    tick={{ fill: "#6B7280", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={24}
                    interval="preserveStartEnd"
                    tickMargin={8}
                  />
                  <YAxis
                    tickFormatter={chartFormatter}
                    tick={{ fill: "#6B7280", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    width={48}
                  />
                  <Tooltip
                    formatter={(value: number, name: string) => {
                      const label =
                        name === "actual"
                          ? "Actual"
                          : name === "compare"
                            ? "Comparison"
                          : name === "projected"
                            ? "Forecast"
                            : name === "upper"
                              ? "Upper"
                              : name === "lower"
                                ? "Lower"
                                : name;
                      return [formatMetricValue(selectedMetric, value), label];
                    }}
                    labelFormatter={(label) => formatShortDate(String(label))}
                    contentStyle={{
                      borderRadius: 0,
                      borderColor: "#E5E7EB",
                      fontSize: "12px",
                      fontFamily: fontBody.fontFamily,
                    }}
                    cursor={{ stroke: "#E5E7EB" }}
                  />
                  {showTodayLine && (
                    <ReferenceLine
                      x={todayKey}
                      stroke="#D1D5DB"
                      strokeDasharray="3 6"
                      label={{
                        value: "Today",
                        position: "top",
                        fill: "#6B7280",
                        fontSize: 10,
                        fontFamily: fontBody.fontFamily,
                      }}
                    />
                  )}
                  {hasActual && (
                    <Line
                      type="monotone"
                      dataKey="actual"
                      stroke="#1B7F8E"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {compareEnabled && hasCompare && (
                    <Line
                      type="monotone"
                      dataKey="compare"
                      stroke="#9CA3AF"
                      strokeWidth={1.5}
                      strokeDasharray="4 6"
                      strokeOpacity={0.7}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {hasProjected && (
                    <Line
                      type="monotone"
                      dataKey="projected"
                      stroke="#0A5F6F"
                      strokeWidth={2}
                      strokeDasharray="6 6"
                      strokeOpacity={0.85}
                      dot={false}
                      isAnimationActive={false}
                    />
                  )}
                  {hasBounds && (
                    <>
                      <Line
                        type="monotone"
                        dataKey="upper"
                        stroke="#1B7F8E"
                        strokeWidth={1.5}
                        strokeDasharray="2 6"
                        strokeOpacity={0.4}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="lower"
                        stroke="#1B7F8E"
                        strokeWidth={1.5}
                        strokeDasharray="2 6"
                        strokeOpacity={0.4}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </>
                  )}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-gray-500">
            <div className="flex items-center gap-4" style={fontBody}>
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 bg-[#1B7F8E]" />
                Actual
              </span>
              {compareEnabled && hasCompare && (
                <span className="flex items-center gap-2">
                  <span className="h-0.5 w-5 border-b border-dashed border-gray-400 opacity-80" />
                  Comparison
                </span>
              )}
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 border-b border-dashed border-[#0A5F6F] opacity-80" />
                Projected
              </span>
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 border-b border-dotted border-[#1B7F8E] opacity-40" />
                Upper/Lower
              </span>
            </div>
            {forecast.length > 0 && !hasProjected && (
              <span style={fontBody} className="text-[10px] uppercase tracking-[0.2em] text-gray-400">
                No projection available
              </span>
            )}
          </div>
        </section>

        <section className="grid gap-6 md:grid-cols-2">
          <TableBlock
            title="Top Sources"
            labelHeader="Referrer"
            rows={topSources}
            valueLabel={showSeededBreakdowns ? primaryLabel : "Sessions"}
            metricKey={showSeededBreakdowns ? selectedMetric : "sessions"}
            detailTotals={detailTotals}
            emptyState={
              showSeededBreakdowns
                ? "Awaiting events. This table will populate after data arrives."
                : "No source data yet for the selected range."
            }
          />
          <TableBlock
            title="Top Pages"
            labelHeader="Path"
            rows={topPages}
            valueLabel={showSeededBreakdowns ? primaryLabel : "Pageviews"}
            metricKey={showSeededBreakdowns ? selectedMetric : "pageviews"}
            detailTotals={detailTotals}
            emptyState={
              showSeededBreakdowns
                ? "Awaiting events. This table will populate after data arrives."
                : "No page-path data yet for the selected range."
            }
          />
          <TableBlock
            title="Devices"
            labelHeader="Device"
            rows={deviceRows}
            valueLabel={showSeededBreakdowns ? primaryLabel : "Pageviews"}
            metricKey={showSeededBreakdowns ? selectedMetric : "pageviews"}
            detailTotals={detailTotals}
            emptyState={
              showSeededBreakdowns
                ? "Awaiting events. This table will populate after data arrives."
                : "No device data yet for the selected range."
            }
          />
          <TableBlock
            title="Regions"
            labelHeader="Country"
            rows={regionRows}
            valueLabel={showSeededBreakdowns ? primaryLabel : "Pageviews"}
            metricKey={showSeededBreakdowns ? selectedMetric : "pageviews"}
            detailTotals={detailTotals}
            emptyState={
              showSeededBreakdowns
                ? "Awaiting events. This table will populate after data arrives."
                : "No country data yet for the selected range."
            }
          />
        </section>

        <section className="border border-gray-200 bg-white p-4">
          <div className="mb-3 text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
            Conversion Events
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_120px_140px] items-center border-b border-gray-200 pb-2 text-xs text-gray-500">
            <span style={fontBody}>Event</span>
            <span className="text-right" style={fontBody}>
              Total
            </span>
            <span className="text-right" style={fontBody}>
              Conversion Rate
            </span>
          </div>
          {conversionEvents.length === 0 ? (
            <div className="py-6 text-xs text-gray-400" style={fontBody}>
              {showSeededBreakdowns
                ? "Awaiting conversion events. This table will populate after data arrives."
                : "No conversion events yet for the selected range."}
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {conversionEvents.map((event) => (
                <div
                  key={event.label}
                  className="grid grid-cols-[minmax(0,1fr)_120px_140px] items-center py-2 text-sm text-gray-700"
                >
                  <span style={fontBody}>{event.label}</span>
                  <span className="text-right text-gray-900" style={fontNumeric}>
                    {formatNumber(event.count)}
                  </span>
                  <span className="text-right text-gray-900" style={fontNumeric}>
                    {formatPercent(event.rate)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

const Charts: React.FC = () => (
  <div className="min-h-screen bg-[#F9FAFB] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
          Valid
        </div>
      </div>
    </header>
    <main className="mx-auto max-w-6xl px-6 pb-10 pt-6">
      <div className="grid gap-6 md:grid-cols-2">
        <TopSources />
        <TopCountries />
        <DeviceBreakdown />
      </div>
    </main>
  </div>
);

const Alerts: React.FC = () => (
  <div className="min-h-screen bg-[#F9FAFB] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
          Valid
        </div>
      </div>
    </header>
    <main className="mx-auto max-w-6xl px-6 pb-10 pt-6">
      <div className="border border-gray-200 bg-white p-4">
        <AlertsPanel />
      </div>
    </main>
  </div>
);

const Settings: React.FC = () => (
  <div className="min-h-screen bg-[#F9FAFB] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
          Valid
        </div>
      </div>
    </header>
    <main className="mx-auto max-w-6xl px-6 pb-10 pt-6">
      <div className="border border-gray-200 bg-white p-4">
        <PrivacyControls />
      </div>
    </main>
  </div>
);

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
              Session ID: <span style={fontNumeric}>{sessionId}</span>
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

export const App: React.FC = () => {
  const { token, authEnabled, ready } = useAuth();

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
          <Route path="/" element={<Overview />} />
          <Route path="/site/:siteId" element={<Overview />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/billing/success" element={<BillingSuccess />} />
          <Route path="/billing/cancel" element={<BillingCancel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
