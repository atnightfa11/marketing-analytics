export function formatNumber(value: number): string {
  if (Number.isNaN(value)) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatPercent(value: number): string {
  if (Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatShortDate(value: string): string {
  return new Date(value).toLocaleDateString();
}
