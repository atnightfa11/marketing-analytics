import type { BreakdownMetricKey } from "../api";
import { DeviceIcon } from "../components/icons";
import type { BreakdownMetricTotals, BreakdownTableRow } from "../types";

export const getBreakdownMetricValue = (row: BreakdownTableRow, metric: BreakdownMetricKey) => row.metrics[metric] ?? 0;

export const aggregateRowsByLabel = (rows: BreakdownTableRow[]) => {
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

export const renderBreakdownLabel = (dimension: string | undefined, label: string) => {
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
  goal: "Conversion type",
  hour_of_day: "Hour",
  day_of_week: "Day",
};

export const renderFilterDimensionLabel = (dimension: string): string =>
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
  goals: "Conversion type",
  "goal events": "Conversion type",
  "time parting": "Time",
};

export const getBreakdownDimensionHeaderLabel = (title: string, rowDimension?: string): string => {
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

export const getBreakdownBarColor = (rowDimension?: string): string =>
  (rowDimension && breakdownBarColorsByDimension[rowDimension]) || "#eef2ff";
