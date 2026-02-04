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

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  withCredentials: false,
});

const siteId = import.meta.env.VITE_SITE_ID ?? "demo";

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("ma_token");
      window.location.href = "/";
    }
    return Promise.reject(err);
  }
);

export async function fetchMetrics(token: string): Promise<MetricStatistic[]> {
  const response = await api.get("/api/metrics", {
    headers: { Authorization: `Bearer ${token}` },
    params: { site_id: siteId },
  });
  return response.data.metrics;
}

export async function fetchForecast(token: string, metric: string): Promise<ForecastResponse> {
  const response = await api.get(`/api/forecast/${metric}`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { site_id: siteId },
  });
  if (response.status === 204) {
    return { forecast: [], mape: Number.NaN, has_anomaly: false, z_score: 0 };
  }
  return response.data;
}

export async function fetchAggregate(metric: string, window: "live" | "standard"): Promise<AggregateWindow[]> {
  const response = await api.get("/api/aggregate", {
    params: { site_id: siteId, metric, window },
  });
  return response.data.windows ?? [];
}
