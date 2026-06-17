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
  batch_id?: number | null;
}

export interface HistoricalImportBatch {
  id: number;
  site_id: string;
  source: string;
  status: string;
  imported_rows: number;
  reduced_days: number;
  start_day?: string | null;
  end_day?: string | null;
  metrics: string[];
  created_by?: string | null;
  created_at: string;
  completed_at?: string | null;
  rolled_back_at?: string | null;
  error?: string | null;
  rollback_available: boolean;
}

export interface HistoricalImportHistoryResponse {
  site_id: string;
  batches: HistoricalImportBatch[];
}

export interface HistoricalImportRollbackResponse {
  site_id: string;
  batch_id: number;
  status: string;
  deleted_rows: number;
  reduced_days: number;
}

export interface SiteAccessMember {
  username: string;
  role: "owner" | "member";
  created_by?: string | null;
  created_at?: string | null;
}

export interface SiteAccessListResponse {
  site_id: string;
  members: SiteAccessMember[];
}

export interface SiteIpBlock {
  id: number;
  site_id: string;
  cidr: string;
  label?: string | null;
  created_by?: string | null;
  created_at: string;
}

export interface SiteIpBlockListResponse {
  site_id: string;
  blocks: SiteIpBlock[];
}

export interface SiteHealthCheck {
  key: string;
  label: string;
  status: "ok" | "warning" | "error";
  detail: string;
  action?: string | null;
}

export interface SiteHealthResponse {
  site_id: string;
  plan: "free" | "standard" | "pro";
  overall_status: "ok" | "warning" | "error";
  lookback_minutes: number;
  recent_reports: number;
  counts_by_kind: Record<string, number>;
  last_report_at?: string | null;
  active_site_keys: number;
  detected_hostnames: string[];
  latest_reducer_status?: string | null;
  latest_reducer_day?: string | null;
  latest_reduced_at?: string | null;
  latest_standard_window_start?: string | null;
  latest_standard_published_at?: string | null;
  forecast_metrics_ready: string[];
  forecast_metrics_building: string[];
  checks: SiteHealthCheck[];
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

export async function fetchImportHistory(token?: string, siteId?: string): Promise<HistoricalImportHistoryResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/import/history", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function rollbackImportBatch(
  batchId: number,
  token?: string,
  siteId?: string
): Promise<HistoricalImportRollbackResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    `/api/import/batches/${batchId}/rollback`,
    null,
    {
      headers: authHeaders(token),
      params: { site_id: resolvedSiteId },
    }
  );
  return response.data;
}

export async function fetchSiteAccess(token?: string, siteId?: string): Promise<SiteAccessListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/site-access", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function grantSiteAccess(
  username: string,
  token?: string,
  siteId?: string
): Promise<SiteAccessListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    "/api/site-access",
    {
      site_id: resolvedSiteId,
      username,
      role: "member",
    },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function removeSiteAccess(
  username: string,
  token?: string,
  siteId?: string
): Promise<SiteAccessListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.delete(`/api/site-access/${encodeURIComponent(username)}`, {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function fetchSiteIpBlocks(token?: string, siteId?: string): Promise<SiteIpBlockListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/site-shields/ip-blocks", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function createSiteIpBlock(
  cidr: string,
  label: string | undefined,
  token?: string,
  siteId?: string
): Promise<SiteIpBlockListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.post(
    "/api/site-shields/ip-blocks",
    {
      site_id: resolvedSiteId,
      cidr,
      label,
    },
    { headers: authHeaders(token) }
  );
  return response.data;
}

export async function deleteSiteIpBlock(
  blockId: number,
  token?: string,
  siteId?: string
): Promise<SiteIpBlockListResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.delete(`/api/site-shields/ip-blocks/${blockId}`, {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
  return response.data;
}

export async function fetchSiteHealth(token?: string, siteId?: string): Promise<SiteHealthResponse> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/site-health", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId },
  });
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
