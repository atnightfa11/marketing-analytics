const COMMON_SOURCE_MAP: Record<string, string> = {
  "google.com": "Google",
  "duckduckgo.com": "DuckDuckGo",
  "reddit.com": "Reddit",
  "x.com": "X",
  "t.co": "X",
  "linkedin.com": "LinkedIn",
};

const SEARCH_SOURCE_SET = new Set([
  "google",
  "google.com",
  "bing",
  "bing.com",
  "duckduckgo",
  "duckduckgo.com",
  "yahoo",
  "yahoo.com",
  "ecosia",
  "ecosia.org",
  "search.brave.com",
  "baidu.com",
  "yandex.com",
]);

const SOCIAL_SOURCE_SET = new Set([
  "reddit",
  "reddit.com",
  "x",
  "x.com",
  "t.co",
  "linkedin",
  "linkedin.com",
  "facebook",
  "facebook.com",
  "instagram",
  "instagram.com",
  "youtube",
  "youtube.com",
  "tiktok",
  "tiktok.com",
  "threads.net",
  "pinterest.com",
]);

const isLikelyPaid = (value: string) => /(paid|cpc|ppc|adwords|sponsored|campaign)/i.test(value);

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

export function classifyChannelLabel(rawLabel: string): string {
  const source = normalizeSourceLabel(rawLabel);
  const normalized = source.toLowerCase();
  if (normalized === "direct") return "Direct";
  if (isLikelyPaid(normalized) && SOCIAL_SOURCE_SET.has(normalized)) return "Paid Social";
  if (isLikelyPaid(normalized)) return "Paid Search";
  if (SOCIAL_SOURCE_SET.has(normalized)) return "Organic Social";
  if (SEARCH_SOURCE_SET.has(normalized)) return "Organic Search";
  if (normalized === "email") return "Referral";
  return "Referral";
}

export function buildSourceMediumLabel(rawLabel: string): string {
  const source = normalizeSourceLabel(rawLabel);
  const channel = classifyChannelLabel(rawLabel);
  if (channel === "Direct") return `${source}/None`;
  if (channel === "Organic Search") return `${source}/Organic`;
  if (channel === "Organic Social") return `${source}/Organic Social`;
  if (channel === "Paid Search") return `${source}/Paid`;
  if (channel === "Paid Social") return `${source}/Paid Social`;
  return `${source}/Referral`;
}
