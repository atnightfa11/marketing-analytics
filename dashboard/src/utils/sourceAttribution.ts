const COMMON_SOURCE_MAP: Record<string, string> = {
  "google.com": "Google",
  "duckduckgo.com": "DuckDuckGo",
  "reddit.com": "Reddit",
  "x.com": "X",
  "t.co": "X",
  "linkedin.com": "LinkedIn",
};

const normalizeHost = (value: string): string => value.trim().toLowerCase().replace(/^www\./, "");

const titleCaseWords = (value: string) =>
  value
    .trim()
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

export function normalizeSourceLabel(rawLabel: string): string {
  if (!rawLabel) return "Referral";
  const normalized = normalizeHost(rawLabel);
  if (!normalized) return "Referral";
  if (normalized === "direct") return "Direct";
  if (normalized === "external") return "Referral";

  if (COMMON_SOURCE_MAP[normalized]) return COMMON_SOURCE_MAP[normalized];

  const hostWithoutPath = normalized.split(/[/?#]/, 1)[0];
  if (COMMON_SOURCE_MAP[hostWithoutPath]) return COMMON_SOURCE_MAP[hostWithoutPath];

  if (normalized.includes("utm_")) {
    return titleCaseWords(normalized.replace(/[_=]+/g, " "));
  }

  if (hostWithoutPath.includes(".")) {
    return hostWithoutPath;
  }

  if (normalized === "unknown") return "Referral";
  return titleCaseWords(normalized);
}
