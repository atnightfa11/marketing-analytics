import axios from "axios";

export interface MetricStatistic {
  metric: string;
  value: number;
  variance: number;
  standard_error: number;
  ci80: { low: number; high: number };
  ci95: { low: number; high: number };
  has_anomaly: boolean;
}

export interface ForecastEntry {
  day: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
}

export interface ForecastResponse {
  forecast: ForecastEntry[];
  mape: number;
  has_anomaly: boolean;
  z_score: number;
}

export interface AggregateWindow {
  window_start: string;
  window_end: string;
  value: number;
  variance: number;
  ci80: { low: number; high: number };
  ci95: { low: number; high: number };
}

export interface BreakdownRow {
  label: string;
  value: number;
  metrics: Record<string, number>;
}

export type BreakdownMetricKey = "uniques" | "sessions" | "pageviews" | "conversions";

export interface BreakdownResponse {
  site_id: string;
  dimension: BreakdownDimension;
  total: number;
  primary_metric: BreakdownMetricKey;
  metric_keys: BreakdownMetricKey[];
  totals: Partial<Record<BreakdownMetricKey, number>>;
  rows: BreakdownRow[];
}

export type BreakdownDimension =
  | "pages"
  | "sources"
  | "devices"
  | "countries"
  | "conversions"
  | "hour_of_day"
  | "day_of_week"
  | "hostnames";

export type TimePartingDayType = "all" | "weekday" | "weekend";

export interface SiteSettings {
  site_id: string;
  timezone: string;
}

export interface BillingStatus {
  site_id: string;
  plan: "free" | "standard" | "pro";
  has_subscription: boolean;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

export interface HistoricalImportResponse {
  site_id: string;
  imported_rows: number;
  reduced_days: number;
}

export interface DashboardSiteSummary {
  site_id: string;
  site_name: string;
  allowed_origin: string;
  plan: "free" | "standard" | "pro";
}

export interface DashboardNote {
  id: number;
  site_id: string;
  day: string;
  body: string;
  metric?: string | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

const fallbackApiBase =
  typeof window !== "undefined" && window.location.hostname.endsWith("validanalytics.io")
    ? "https://api.validanalytics.io"
    : "http://localhost:8000";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? fallbackApiBase,
  withCredentials: false,
});

const defaultSiteId = import.meta.env.VITE_SITE_ID ?? "demo";

export function resolveActiveSiteId(explicitSiteId?: string): string {
  if (explicitSiteId?.trim()) {
    return explicitSiteId.trim();
  }
  if (typeof window !== "undefined") {
    const querySiteId = new URLSearchParams(window.location.search).get("site_id")?.trim();
    if (querySiteId) {
      return querySiteId;
    }
    const pathMatch = window.location.pathname.match(/^\/site\/([^/?#]+)/);
    if (pathMatch?.[1]) {
      return decodeURIComponent(pathMatch[1]).trim();
    }
  }
  return defaultSiteId;
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const hadToken = Boolean(localStorage.getItem("ma_token"));
      localStorage.removeItem("ma_token");
      if (hadToken && typeof window !== "undefined") {
        window.location.reload();
      }
    }
    return Promise.reject(err);
  }
);

function authHeaders(token?: string): Record<string, string> | undefined {
  if (!token) return undefined;
  return { Authorization: `Bearer ${token}` };
}

export async function fetchMetrics(token?: string, siteId?: string): Promise<MetricStatistic[]> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/metrics", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data.metrics;
}

export async function fetchForecast(token: string | undefined, metric: string, siteId?: string): Promise<ForecastResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get(`/api/forecast/${metric}`, {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  if (response.status === 204) {
    return { forecast: [], mape: Number.NaN, has_anomaly: false, z_score: 0 };
  }
  return response.data;
}

export async function fetchAggregate(
  metric: string,
  window: "live" | "standard",
  token?: string,
  siteId?: string,
  hostname?: string
): Promise<AggregateWindow[]> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/aggregate", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId, metric, window, hostname },
  });
  return response.data.windows ?? [];
}

export async function fetchSiteSettings(token?: string, siteId?: string): Promise<SiteSettings> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/site-settings", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function fetchDashboardSites(token?: string): Promise<DashboardSiteSummary[]> {
  const response = await api.get("/api/sites", {
    headers: authHeaders(token),
  });
  return response.data.sites ?? [];
}

export async function fetchDashboardNotes(
  token: string | undefined,
  siteId?: string,
  start?: string,
  end?: string
): Promise<DashboardNote[]> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/notes", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId, start, end },
  });
  return response.data.notes ?? [];
}

export async function createDashboardNote(
  payload: { day: string; body: string; metric?: string | null },
  token?: string,
  siteId?: string
): Promise<DashboardNote> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    "/api/notes",
    {
      site_id: resolvedSiteId,
      day: payload.day,
      body: payload.body,
      metric: payload.metric ?? null,
    },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function deleteDashboardNote(noteId: number, token?: string, siteId?: string): Promise<void> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  await api.delete(`/api/notes/${noteId}`, {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
}

export async function updateSiteTimezone(timezone: string, token?: string, siteId?: string): Promise<SiteSettings> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.put(
    "/api/site-settings",
    { timezone },
    {
      headers: authHeaders(token),
      params: { site_id: resolvedSiteId },
    }
  );
  return response.data;
}

export async function fetchBillingStatus(token?: string, siteId?: string): Promise<BillingStatus> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/billing/status", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function createCheckoutSession(
  plan: "standard" | "pro",
  token?: string,
  siteId?: string,
  successUrl?: string,
  cancelUrl?: string
): Promise<CheckoutSessionResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    "/api/checkout/session",
    {
      site_id: resolvedSiteId,
      plan,
      success_url: successUrl,
      cancel_url: cancelUrl,
    },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function importHistoricalCsv(
  csvText: string,
  token?: string,
  siteId?: string
): Promise<HistoricalImportResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    "/api/import/historical-csv",
    {
      site_id: resolvedSiteId,
      csv_text: csvText,
    },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function fetchBreakdown(
  dimension: BreakdownDimension,
  token?: string,
  siteId?: string,
  start?: string,
  end?: string,
  limit: number = 10,
  hostname?: string,
  dayType?: TimePartingDayType
): Promise<BreakdownResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/breakdown", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId, dimension, start, end, limit, hostname, day_type: dayType },
  });
  return response.data;
}
