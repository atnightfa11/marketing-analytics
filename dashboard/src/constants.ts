import type { BreakdownDimension, BreakdownMetricKey } from "./api";

export const LAST_SITE_ID_STORAGE_KEY = "valid_last_site_id";
export const ENABLE_DEMO_MODE = import.meta.env.VITE_ENABLE_DEMO_MODE === "true";

export const metricLabels: Record<string, string> = {
  uniques: "Visitors",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
  avg_pages_per_visit: "Pages per Visit",
  bounce_rate: "Bounce Rate",
  visit_duration: "Visit Duration",
  revenue: "Revenue",
};

export const breakdownMetricInlineLabels: Record<BreakdownMetricKey, string> = {
  uniques: "Visitors",
  sessions: "Sessions",
  pageviews: "Pageviews",
  conversions: "Conversions",
  revenue: "Revenue",
};

export const hourOfDayLabels = [
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

export const dayOfWeekLabels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

export const metricOptions = [
  { key: "uniques", label: "Visitors" },
  { key: "pageviews", label: "Pageviews" },
  { key: "sessions", label: "Sessions" },
  { key: "conversions", label: "Conversions" },
  { key: "revenue", label: "Revenue" },
  { key: "avg_pages_per_visit", label: "Average Pages per Visit" },
  { key: "visit_duration", label: "Visit Duration" },
  { key: "bounce_rate", label: "Bounce Rate" },
] as const;

export const aggregateMetricKeys = ["pageviews", "uniques", "sessions", "conversions", "revenue"] as const;
export const engagementAggregateMetricKeys = ["bounced_sessions", "visit_duration_seconds"] as const;

export const breakdownDimensions: BreakdownDimension[] = [
  "sources",
  "pages",
  "devices",
  "countries",
  "conversions",
  "hour_of_day",
  "day_of_week",
];

export const timezoneOptions = [
  "UTC",
  "America/Chicago",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
] as const;

export const goalEligibleMetrics = ["revenue", "conversions", "pageviews", "sessions", "uniques"] as const;

export const rangeOptions = ["Today", "Yesterday", "Last 7", "Last 30", "Last 90", "MTD", "YTD", "Custom"] as const;

export const forecastOptions = [
  { key: "7d", label: "Next 7 Days", kind: "days", days: 7 },
  { key: "30d", label: "Next 30 Days", kind: "days", days: 30 },
  { key: "60d", label: "Next 60 Days", kind: "days", days: 60 },
  { key: "90d", label: "Next 90 Days", kind: "days", days: 90 },
  { key: "q1", label: "Q1", kind: "quarter", quarter: 1 },
  { key: "q2", label: "Q2", kind: "quarter", quarter: 2 },
  { key: "q3", label: "Q3", kind: "quarter", quarter: 3 },
  { key: "q4", label: "Q4", kind: "quarter", quarter: 4 },
] as const;

export const MS_PER_DAY = 86_400_000;
