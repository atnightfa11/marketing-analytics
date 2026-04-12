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
}

export type BreakdownDimension = "pages" | "sources" | "devices" | "countries";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
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
  siteId?: string
): Promise<AggregateWindow[]> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/aggregate", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId, metric, window },
  });
  return response.data.windows ?? [];
}

export async function fetchBreakdown(
  dimension: BreakdownDimension,
  token?: string,
  siteId?: string,
  start?: string,
  end?: string,
  limit: number = 10
): Promise<BreakdownRow[]> {
  const resolvedSiteId = resolveActiveSiteId(siteId);
  const response = await api.get("/api/breakdown", {
    headers: authHeaders(token),
    params: { site_id: resolvedSiteId, dimension, start, end, limit },
  });
  return response.data.rows ?? [];
}
