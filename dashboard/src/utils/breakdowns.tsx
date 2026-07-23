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
  if (dimension === "country") {
    const country = getCountryDisplay(label);
    return (
      <span className="inline-flex min-w-0 items-center gap-2">
        {country.flag ? <span className="shrink-0 text-[15px] leading-none">{country.flag}</span> : null}
        <span className="truncate">{country.name}</span>
      </span>
    );
  }
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
  channel: "#4F46E5",
  source: "#4F46E5",
  source_medium: "#4F46E5",
  campaign: "#4F46E5",
  content: "#4F46E5",
  term: "#4F46E5",
  page: "#4F46E5",
  country: "#4F46E5",
  device: "#4F46E5",
  goal: "#4F46E5",
  hour_of_day: "#4F46E5",
  day_of_week: "#4F46E5",
  hostname: "#4F46E5",
};

export const getBreakdownBarColor = (rowDimension?: string): string =>
  (rowDimension && breakdownBarColorsByDimension[rowDimension]) || "#4F46E5";

const countryNameFallbacks: Record<string, string> = {
  AD: "Andorra",
  AE: "United Arab Emirates",
  AF: "Afghanistan",
  AG: "Antigua and Barbuda",
  AI: "Anguilla",
  AL: "Albania",
  AM: "Armenia",
  AO: "Angola",
  AR: "Argentina",
  AT: "Austria",
  AU: "Australia",
  AZ: "Azerbaijan",
  BA: "Bosnia and Herzegovina",
  BB: "Barbados",
  BD: "Bangladesh",
  BE: "Belgium",
  BG: "Bulgaria",
  BH: "Bahrain",
  BR: "Brazil",
  BS: "Bahamas",
  BZ: "Belize",
  CA: "Canada",
  CH: "Switzerland",
  CL: "Chile",
  CN: "China",
  CO: "Colombia",
  CR: "Costa Rica",
  CZ: "Czechia",
  DE: "Germany",
  DK: "Denmark",
  DO: "Dominican Republic",
  EC: "Ecuador",
  EE: "Estonia",
  ES: "Spain",
  FI: "Finland",
  FR: "France",
  GB: "United Kingdom",
  GR: "Greece",
  GT: "Guatemala",
  HK: "Hong Kong",
  HR: "Croatia",
  HU: "Hungary",
  ID: "Indonesia",
  IE: "Ireland",
  IL: "Israel",
  IN: "India",
  IS: "Iceland",
  IT: "Italy",
  JP: "Japan",
  KR: "South Korea",
  LI: "Liechtenstein",
  LT: "Lithuania",
  LU: "Luxembourg",
  LV: "Latvia",
  MX: "Mexico",
  MY: "Malaysia",
  NL: "Netherlands",
  NO: "Norway",
  NZ: "New Zealand",
  PA: "Panama",
  PE: "Peru",
  PH: "Philippines",
  PL: "Poland",
  PT: "Portugal",
  RO: "Romania",
  RS: "Serbia",
  SE: "Sweden",
  SG: "Singapore",
  TH: "Thailand",
  TR: "Turkey",
  TW: "Taiwan",
  UA: "Ukraine",
  UK: "United Kingdom",
  US: "United States",
  UY: "Uruguay",
  VN: "Vietnam",
  ZA: "South Africa",
};

const getCountryDisplay = (label: string): { flag: string | null; name: string } => {
  const trimmed = label.trim();
  const code =
    trimmed.length === 2 && /^[a-z]{2}$/i.test(trimmed)
      ? trimmed.toUpperCase()
      : Object.entries(countryNameFallbacks).find(([, name]) => name.toLowerCase() === trimmed.toLowerCase())?.[0] ?? null;
  if (!code) return { flag: null, name: trimmed };
  const flag = String.fromCodePoint(...[...code].map((char) => 0x1f1e6 + char.charCodeAt(0) - 65));
  return { flag, name: countryNameFallbacks[code] ?? code };
};
