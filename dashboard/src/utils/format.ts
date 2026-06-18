export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatCurrency(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDuration(seconds: number): string {
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
}

export function formatMetricValue(metric: string, value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (metric === "revenue") return formatCurrency(value);
  if (metric === "visit_duration") return formatDuration(value);
  if (metric.includes("rate")) return formatPercent(value);
  if (metric === "avg_pages_per_visit") return value.toFixed(2);
  return formatNumber(value);
}

export function formatDailyPace(metric: string, value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (metric === "revenue") return `${formatCurrency(value)}/day`;
  if (Math.abs(value) < 10 && !Number.isInteger(value)) return `${value.toFixed(1)}/day`;
  return `${formatNumber(value)}/day`;
}

export function formatShortDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString();
}
