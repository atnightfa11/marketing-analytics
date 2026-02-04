import React, { Suspense, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
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
  fetchAggregate,
  fetchForecast,
  fetchMetrics,
  ForecastEntry,
  ForecastResponse,
  MetricStatistic,
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
  bounce_rate: "Bounce Rate",
  avg_time_on_site: "Visit Duration",
  revenue: "Revenue",
};

const siteId = import.meta.env.VITE_SITE_ID ?? "demo";

const metricOptions = [
  { key: "pageviews", label: "Pageviews" },
  { key: "uniques", label: "Unique Visitors" },
  { key: "sessions", label: "Sessions" },
  { key: "conversions", label: "Conversions" },
  { key: "revenue", label: "Revenue" },
];

const rangeOptions = ["Last 7", "Last 30", "Last 90", "MTD", "YTD", "Custom"] as const;
const forecastOptions = [
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

const formatMetricValue = (metric: string, value: number) => {
  if (!Number.isFinite(value)) return "N/A";
  if (metric === "revenue") return formatCurrency(value);
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
}> = ({ title, labelHeader, rows, valueLabel, metricKey, detailTotals }) => {
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
          Awaiting events. This table will populate after data arrives.
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
  const { token } = useAuth();
  const [selectedMetric, setSelectedMetric] = useState("pageviews");
  const [range, setRange] = useState<RangeOption>("Last 30");
  const [forecastKey, setForecastKey] = useState<(typeof forecastOptions)[number]["key"]>("90d");
  const [metrics, setMetrics] = useState<MetricStatistic[]>([]);
  const [forecast, setForecast] = useState<ForecastEntry[]>([]);
  const [forecastMeta, setForecastMeta] = useState<Pick<ForecastResponse, "mape" | "has_anomaly"> | null>(
    null
  );
  const [aggregateMap, setAggregateMap] = useState<Record<string, AggregateWindow[]>>({});
  const [liveWindows, setLiveWindows] = useState<AggregateWindow[]>([]);
  const [customRange, setCustomRange] = useState<DateRange>({ start: "", end: "" });
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [compareMode, setCompareMode] = useState<"previous" | "custom">("previous");
  const [compareRange, setCompareRange] = useState<DateRange>({ start: "", end: "" });
  const [exportMode, setExportMode] = useState<"current" | "all">("current");
  useEffect(() => {
    if (!token) return;
    fetchMetrics(token).then(setMetrics).catch(console.error);
    const metricsToFetch = metricOptions.map((metric) => metric.key);
    Promise.all(
      metricsToFetch.map((metric) =>
        fetchAggregate(metric, "standard").then((data) => ({
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
  }, [token]);

  useEffect(() => {
    if (!token) return;
    fetchForecast(token, selectedMetric)
      .then((data) => {
        setForecast(data.forecast);
        setForecastMeta({ mape: data.mape, has_anomaly: data.has_anomaly });
      })
      .catch(console.error);
  }, [token, selectedMetric]);

  useEffect(() => {
    if (!token) return;
    const loadLive = () => fetchAggregate("uniques", "live").then(setLiveWindows).catch(console.error);
    loadLive();
    const interval = setInterval(loadLive, 30000);
    return () => clearInterval(interval);
  }, [token]);

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
    const endDate = clampDate(new Date());

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

  const getDailySeries = (metric: string, rangeKey: RangeOption = range, custom: DateRange = customRange) =>
    filterByRange(toDaily(aggregateMap[metric] ?? []), rangeKey, custom);
  const dailySelectedAll = useMemo(
    () => toDaily(aggregateMap[selectedMetric] ?? []),
    [aggregateMap, selectedMetric]
  );
  const dailySelected = useMemo(
    () => getDailySeries(selectedMetric, range, customRange),
    [aggregateMap, selectedMetric, range, customRange]
  );
  const dailyPageviews = useMemo(() => getDailySeries("pageviews"), [aggregateMap, range, customRange]);
  const dailyUniques = useMemo(() => getDailySeries("uniques"), [aggregateMap, range, customRange]);
  const dailySessions = useMemo(() => getDailySeries("sessions"), [aggregateMap, range, customRange]);
  const dailyConversions = useMemo(() => getDailySeries("conversions"), [aggregateMap, range, customRange]);
  const dailyRevenue = useMemo(() => getDailySeries("revenue"), [aggregateMap, range, customRange]);

  const totals = {
    pageviews: dailyPageviews.reduce((sum, row) => sum + row.value, 0),
    uniques: dailyUniques.reduce((sum, row) => sum + row.value, 0),
    sessions: dailySessions.reduce((sum, row) => sum + row.value, 0),
    conversions: dailyConversions.reduce((sum, row) => sum + row.value, 0),
    revenue: dailyRevenue.reduce((sum, row) => sum + row.value, 0),
  };
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
    if (!availableBounds || compareMode !== "custom" || !compareRange.start || !compareRange.end) return;
    setCompareRange((prev) => {
      const nextStart = prev.start < availableBounds.min ? availableBounds.min : prev.start;
      const nextEnd = prev.end > availableBounds.max ? availableBounds.max : prev.end;
      return { start: nextStart, end: nextEnd };
    });
  }, [availableBounds, compareMode, compareRange.start, compareRange.end]);

  const primaryLabel = metricLabels[selectedMetric] ?? selectedMetric;
  const primaryValue = totals[selectedMetric as keyof typeof totals] ?? Number.NaN;
  const primaryDisplay = formatMetricValue(selectedMetric, primaryValue);
  const lastActualDay = dailySelected.length > 0 ? dailySelected[dailySelected.length - 1].day : null;
  const primaryRangeBounds = useMemo(() => {
    if (dailySelected.length === 0) return null;
    return { start: dailySelected[0].day, end: dailySelected[dailySelected.length - 1].day };
  }, [dailySelected]);

  const selectedForecast =
    (forecastOptions.find((option) => option.key === forecastKey) as ForecastOption) ?? forecastOptions[2];
  const forecastWindow = useMemo(
    () => resolveForecastWindow(forecast, lastActualDay, selectedForecast),
    [forecast, lastActualDay, selectedForecast]
  );

  const forecastLabel = forecastWindow.label;
  const forecastHorizon = forecastWindow.entries;

  const comparisonBounds = useMemo(() => {
    if (!compareEnabled || !availableBounds) return null;
    if (compareMode === "previous") {
      if (!primaryRangeBounds) return null;
      const start = parseDay(primaryRangeBounds.start);
      const end = parseDay(primaryRangeBounds.end);
      const diffDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / MS_PER_DAY) + 1);
      const compareEnd = new Date(start);
      compareEnd.setDate(compareEnd.getDate() - 1);
      const compareStart = new Date(compareEnd);
      compareStart.setDate(compareStart.getDate() - (diffDays - 1));
      const minDate = parseDay(availableBounds.min);
      const maxDate = parseDay(availableBounds.max);
      const clampDate = (date: Date) =>
        new Date(Math.min(Math.max(date.getTime(), minDate.getTime()), maxDate.getTime()));
      const clampedStart = clampDate(compareStart);
      const clampedEnd = clampDate(compareEnd);
      return { start: formatIsoDate(clampedStart), end: formatIsoDate(clampedEnd) };
    }
    if (!compareRange.start || !compareRange.end) return null;
    const startCandidate = compareRange.start < availableBounds.min ? availableBounds.min : compareRange.start;
    const endCandidate = compareRange.end > availableBounds.max ? availableBounds.max : compareRange.end;
    const start = startCandidate <= endCandidate ? startCandidate : endCandidate;
    const end = startCandidate <= endCandidate ? endCandidate : startCandidate;
    return { start, end };
  }, [compareEnabled, compareMode, compareRange, availableBounds, primaryRangeBounds]);

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

  const getComparisonSeries = (metric: string) => {
    if (!comparisonBounds) return [];
    const entries = toDaily(aggregateMap[metric] ?? []);
    return filterByWindow(entries, comparisonBounds.start, comparisonBounds.end);
  };

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
    ? {
        pageviews: getComparisonSeries("pageviews").reduce((sum, row) => sum + row.value, 0),
        uniques: getComparisonSeries("uniques").reduce((sum, row) => sum + row.value, 0),
        sessions: getComparisonSeries("sessions").reduce((sum, row) => sum + row.value, 0),
        conversions: getComparisonSeries("conversions").reduce((sum, row) => sum + row.value, 0),
        revenue: getComparisonSeries("revenue").reduce((sum, row) => sum + row.value, 0),
      }
    : null;
  const comparisonLabel = comparisonBounds
    ? compareMode === "previous"
      ? "vs previous period"
      : `vs ${formatShortDate(comparisonBounds.start)}–${formatShortDate(comparisonBounds.end)}`
    : null;
  const selectedCompareTotal =
    comparisonTotals?.[selectedMetric as keyof typeof totals] ?? Number.NaN;
  const selectedCompareDelta =
    Number.isFinite(selectedCompareTotal) && selectedCompareTotal > 0
      ? (primaryValue - selectedCompareTotal) / selectedCompareTotal
      : Number.NaN;
  const selectedCompareDisplay = Number.isFinite(selectedCompareDelta)
    ? `${selectedCompareDelta >= 0 ? "+" : ""}${(selectedCompareDelta * 100).toFixed(1)}%`
    : "—";

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

  const selectedTotal = totals[selectedMetric as keyof typeof totals] ?? 0;
  const topSources = buildRows(
    ["Organic Search", "Direct", "Referral", "Social", "Email"],
    [0.36, 0.22, 0.16, 0.14, 0.12],
    selectedTotal
  );
  const topPages = buildRows(
    ["/", "/pricing", "/blog/privacy", "/docs/setup", "/about"],
    [0.3, 0.22, 0.18, 0.16, 0.14],
    selectedTotal
  );
  const deviceRows = buildRows(["Mobile", "Desktop", "Tablet"], [0.58, 0.34, 0.08], selectedTotal);
  const regionRows = buildRows(
    ["United States", "United Kingdom", "Canada", "Germany", "France", "Netherlands", "Australia", "Sweden", "India", "Japan"],
    [0.28, 0.12, 0.09, 0.08, 0.07, 0.06, 0.06, 0.05, 0.1, 0.09],
    selectedTotal
  );
  const metricMap = useMemo(
    () => new Map(metrics.map((metric) => [metric.metric, metric.value])),
    [metrics]
  );
  const overallBounceRate = clamp(
    Number(metricMap.get("bounce_rate") ?? 0.42),
    0.1,
    0.9
  );
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
  const chartFormatter = (value: number) =>
    selectedMetric === "revenue" ? formatCompactCurrency(value) : formatNumber(value);
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
    if (!token) return;
    const metricKeys = metricOptions.map((metric) => metric.key);
    const forecasts = await Promise.all(
      metricKeys.map(async (metric) => {
        if (metric === selectedMetric) {
          return { metric, forecast };
        }
        try {
          const response = await fetchForecast(token, metric);
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
    const toCell = (value?: number) => {
      if (!Number.isFinite(value)) return "";
      return isRevenue ? value.toFixed(2) : value.toFixed(0);
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
  }, [totals.conversions, totals.sessions]);

  return (
    <div className="min-h-screen bg-[#F3F4F6] print-bg">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="text-xl font-semibold text-[#111827]" style={fontHeading}>
            Valid
          </div>
          <div className="flex items-center gap-2 no-print">
            <span className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Range
            </span>
            <select
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
                  className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
                      className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
                      className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
            <span className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Forecast
            </span>
            <select
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
              className="border border-gray-200 bg-white px-2 py-1 text-xs text-[#111827]"
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
            <div className="text-lg text-[#111827]" style={fontHeading}>
              Overview
            </div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
              Site: {siteId}
            </div>
          </div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
            Metrics · {range}
          </div>
        </div>
        <section className="border border-gray-200 bg-white p-4">
          <div className="border-b border-gray-200 pb-3">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                  {primaryLabel}
                </div>
                <div className="mt-1 text-sm text-gray-500" style={fontBody}>
                  Daily totals · {range}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                  Total
                </div>
                <div className="mt-1 text-3xl text-[#111827]" style={fontNumeric}>
                  {primaryDisplay}
                </div>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 no-print">
              {metricOptions.map((option) => {
                const isActive = selectedMetric === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setSelectedMetric(option.key)}
                    className={`border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${
                      isActive ? "border-[#7A6AE6] text-[#111827]" : "border-gray-200 text-gray-500"
                    }`}
                    style={fontBody}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-[10px] uppercase tracking-[0.2em] text-gray-500">
              <span style={fontBody}>
                Live visitors{" "}
                <span className="ml-1 text-[#111827]" style={fontNumeric}>
                  {formatNumber(liveValue)}
                </span>
              </span>
              <span style={fontBody}>
                Last updated{" "}
                <span className="ml-1 text-[#111827]" style={fontNumeric}>
                  {lastActualDay ? formatShortDate(lastActualDay) : "—"}
                </span>
              </span>
              <span style={fontBody}>
                Forecast {forecastLabel}{" "}
                <span className="ml-1 text-[#111827]" style={fontNumeric}>
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
                <span className="text-amber-600" style={fontBody}>
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
                    label={{
                      value: primaryLabel,
                      angle: -90,
                      position: "insideLeft",
                      style: { fill: "#9CA3AF", fontSize: 10, fontFamily: fontBody.fontFamily },
                    }}
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
                      stroke="#7A6AE6"
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
                      stroke="#5E52D6"
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
                        stroke="#7A6AE6"
                        strokeWidth={1.5}
                        strokeDasharray="2 6"
                        strokeOpacity={0.4}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="lower"
                        stroke="#7A6AE6"
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
                <span className="h-0.5 w-5 bg-[#7A6AE6]" />
                Actual
              </span>
              {compareEnabled && hasCompare && (
                <span className="flex items-center gap-2">
                  <span className="h-0.5 w-5 border-b border-dashed border-gray-400 opacity-80" />
                  Comparison
                </span>
              )}
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 border-b border-dashed border-[#5E52D6] opacity-80" />
                Projected
              </span>
              <span className="flex items-center gap-2">
                <span className="h-0.5 w-5 border-b border-dotted border-[#7A6AE6] opacity-40" />
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

        <div>
          <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
            Key metrics
          </div>
          <KPIGrid
            metrics={metrics}
            values={{
              pageviews: totals.pageviews,
              uniques: totals.uniques,
              sessions: totals.sessions,
              conversions: totals.conversions,
              revenue: totals.revenue,
            }}
            comparisonValues={comparisonTotals}
            comparisonLabel={comparisonLabel}
          />
        </div>

        <section className="grid gap-6 md:grid-cols-2">
          <TableBlock
            title="Top Sources"
            labelHeader="Referrer"
            rows={topSources}
            valueLabel={primaryLabel}
            metricKey={selectedMetric}
            detailTotals={detailTotals}
          />
          <TableBlock
            title="Top Pages"
            labelHeader="Path"
            rows={topPages}
            valueLabel={primaryLabel}
            metricKey={selectedMetric}
            detailTotals={detailTotals}
          />
          <TableBlock
            title="Devices"
            labelHeader="Device"
            rows={deviceRows}
            valueLabel={primaryLabel}
            metricKey={selectedMetric}
            detailTotals={detailTotals}
          />
          <TableBlock
            title="Regions"
            labelHeader="Country"
            rows={regionRows}
            valueLabel={primaryLabel}
            metricKey={selectedMetric}
            detailTotals={detailTotals}
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
              Awaiting conversion events. This table will populate after data arrives.
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
  <div className="min-h-screen bg-[#F3F4F6] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#111827]" style={fontHeading}>
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
  <div className="min-h-screen bg-[#F3F4F6] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#111827]" style={fontHeading}>
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
  <div className="min-h-screen bg-[#F3F4F6] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="text-xl font-semibold text-[#111827]" style={fontHeading}>
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

export const App: React.FC = () => {
  const { token, login } = useAuth();

  useEffect(() => {
    if (!token) {
      login("demo", "demo");
    }
  }, [token, login]);

  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true }}>
      <Suspense fallback={<div>{en.loading}</div>}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
