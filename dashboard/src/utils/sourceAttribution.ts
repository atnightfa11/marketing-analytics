const COMMON_SOURCE_MAP: Record<string, string> = {
  "adwords": "Google Ads",
  "bing.com": "Bing",
  "bingads": "Bing Ads",
  "chat.openai.com": "ChatGPT",
  "chatgpt": "ChatGPT",
  "chatgpt.com": "ChatGPT",
  "claude": "Claude",
  "claude.ai": "Claude",
  "copilot": "Copilot",
  "copilot.microsoft.com": "Copilot",
  "ecosia.org": "Ecosia",
  "facebook.com": "Facebook",
  "gemini": "Gemini",
  "gemini.google.com": "Gemini",
  "google.com": "Google",
  "googleads": "Google Ads",
  "instagram.com": "Instagram",
  "duckduckgo.com": "DuckDuckGo",
  "microsoftads": "Microsoft Ads",
  "openai.com": "ChatGPT",
  "perplexity": "Perplexity",
  "perplexity.ai": "Perplexity",
  "pinterest.com": "Pinterest",
  "reddit.com": "Reddit",
  "threads.net": "Threads",
  "tiktok.com": "TikTok",
  "twitter.com": "X",
  "x.com": "X",
  "t.co": "X",
  "linkedin.com": "LinkedIn",
  "youtube.com": "YouTube",
  "yahoo.com": "Yahoo",
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

const AI_ASSISTANT_SOURCE_SET = new Set([
  "chatgpt",
  "chatgpt.com",
  "chat.openai.com",
  "claude",
  "claude.ai",
  "perplexity",
  "perplexity.ai",
  "gemini",
  "gemini.google.com",
  "copilot",
  "copilot.microsoft.com",
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

const EMAIL_SOURCE_SET = new Set(["email", "e-mail", "e_mail", "e mail", "gmail", "newsletter"]);

const PAID_SEARCH_SOURCE_SET = new Set([
  "adwords",
  "bing ads",
  "bingads",
  "google ads",
  "googleads",
  "microsoft ads",
  "microsoftads",
]);

const PAID_SIGNAL_PATTERN = /(^|[\s/_-])(cpc|ppc|paid|retargeting|remarketing|sponsored|display|cpm)($|[\s/_-])/i;

const normalizeSourceKey = (value: string): string => {
  let normalized = value.trim().toLowerCase();
  if (!normalized) return "";
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(normalized)) {
    try {
      normalized = new URL(normalized).hostname;
    } catch {
      // Fall through to the cheaper host cleanup below.
    }
  }
  const host = normalized.split(/[/?#]/, 1)[0].replace(/^www\./, "");
  return host || normalized.replace(/^www\./, "");
};

const matchesSourceSet = (value: string, candidates: Set<string>) => {
  const normalized = normalizeSourceKey(value);
  if (!normalized) return false;
  for (const candidate of candidates) {
    if (normalized === candidate || normalized.endsWith(`.${candidate}`)) return true;
  }
  return false;
};

const isExplicitPaidSource = (value: string): boolean => {
  const normalized = value.trim().toLowerCase();
  const sourceKey = normalizeSourceKey(value);
  return PAID_SIGNAL_PATTERN.test(normalized) || PAID_SEARCH_SOURCE_SET.has(sourceKey);
};

const titleCaseWords = (value: string) =>
  value
    .trim()
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

export function normalizeSourceLabel(rawLabel: string): string {
  if (!rawLabel) return "Referral";
  const normalized = rawLabel.trim().toLowerCase();
  if (!normalized) return "Referral";
  if (normalized === "direct" || normalized === "(direct)") return "Direct";
  if (normalized === "external") return "Referral";

  if (COMMON_SOURCE_MAP[normalized]) return COMMON_SOURCE_MAP[normalized];

  const hostWithoutPath = normalizeSourceKey(normalized);
  if (COMMON_SOURCE_MAP[hostWithoutPath]) return COMMON_SOURCE_MAP[hostWithoutPath];
  for (const [knownHost, label] of Object.entries(COMMON_SOURCE_MAP)) {
    if (hostWithoutPath.endsWith(`.${knownHost}`)) return label;
  }

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
  const rawNormalized = rawLabel.trim().toLowerCase();
  if (normalized === "direct") return "Direct";
  if (normalized === "organic") return "Organic Search";
  if (normalized === "social") return "Organic Social";
  if (matchesSourceSet(normalized, AI_ASSISTANT_SOURCE_SET) || matchesSourceSet(rawNormalized, AI_ASSISTANT_SOURCE_SET)) {
    return "AI Assistants";
  }
  const hasPaidSignal = isExplicitPaidSource(rawNormalized) || isExplicitPaidSource(normalized);
  if (hasPaidSignal && (matchesSourceSet(normalized, SOCIAL_SOURCE_SET) || matchesSourceSet(rawNormalized, SOCIAL_SOURCE_SET))) {
    return "Paid Social";
  }
  if (hasPaidSignal && (matchesSourceSet(normalized, SEARCH_SOURCE_SET) || PAID_SEARCH_SOURCE_SET.has(normalizeSourceKey(rawNormalized)) || PAID_SEARCH_SOURCE_SET.has(normalizeSourceKey(normalized)))) {
    return "Paid Search";
  }
  if (hasPaidSignal) return "Paid Other";
  if (matchesSourceSet(normalized, SOCIAL_SOURCE_SET) || matchesSourceSet(rawNormalized, SOCIAL_SOURCE_SET)) return "Organic Social";
  if (matchesSourceSet(normalized, SEARCH_SOURCE_SET) || matchesSourceSet(rawNormalized, SEARCH_SOURCE_SET)) return "Organic Search";
  if (EMAIL_SOURCE_SET.has(normalized) || EMAIL_SOURCE_SET.has(rawNormalized)) return "Email";
  return "Referral";
}

export function buildSourceMediumLabel(rawLabel: string): string {
  const source = normalizeSourceLabel(rawLabel);
  const channel = classifyChannelLabel(rawLabel);
  if (channel === "Direct") return `${source}/None`;
  if (channel === "Organic Search") return `${source}/Organic`;
  if (channel === "Organic Social") return `${source}/Organic Social`;
  if (channel === "AI Assistants") return `${source}/AI Assistant`;
  if (channel === "Email") return `${source}/Email`;
  if (channel === "Paid Search") return `${source}/Paid`;
  if (channel === "Paid Social") return `${source}/Paid Social`;
  if (channel === "Paid Other") return `${source}/Paid`;
  return `${source}/Referral`;
}
