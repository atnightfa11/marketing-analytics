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

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  withCredentials: false,
});

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
    params: { site_id: "demo" },
  });
  return response.data.metrics;
}

export async function fetchForecast(token: string, metric: string): Promise<ForecastEntry[]> {
  const response = await api.get(`/api/forecast/${metric}`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { site_id: "demo" },
  });
  return response.status === 204 ? [] : response.data.forecast;
}
