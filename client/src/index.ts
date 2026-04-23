import { EventCollector } from "./collector/eventCollector";
import { rrBit, adjustedProbability } from "./ldp/rr";
import { DailyPresenceMemo } from "./ldp/dailyPresence";
import {
  AutoeventsConfig,
  ClientConfig,
  ConversionEventPayload,
  EventEnvelope,
  EventKind,
  PresenceReport,
  PurchaseEventPayload,
  SessionEventPayload,
} from "./types";
import { getCrypto, getRandomValuesHex, shouldSample } from "./utils/crypto";
import { createLogger, Logger } from "./utils/logger";

const CIRCUIT_BREAKER_LIMIT = 10;
const CIRCUIT_BREAKER_DURATION_MS = 5 * 60 * 1000;
const THREE_MINUTES_MS = 3 * 60 * 1000;
const DEFAULT_SESSION_INACTIVITY_MS = 30 * 60 * 1000;
const DEFAULT_CONVERSION_DEDUPE_MS = 10 * 1000;
const DEFAULT_ATTRIBUTION_CARRYOVER_MS = 30 * 60 * 1000;
const ATTRIBUTION_STORAGE_KEY = "__valid_attribution_v1";

const SEARCH_ENGINE_HOSTS = [
  "google.com",
  "bing.com",
  "duckduckgo.com",
  "yahoo.com",
  "search.brave.com",
  "ecosia.org",
  "yandex.com",
  "baidu.com",
];

const SOCIAL_HOSTS = [
  "facebook.com",
  "instagram.com",
  "x.com",
  "twitter.com",
  "linkedin.com",
  "t.co",
  "reddit.com",
  "youtube.com",
  "tiktok.com",
  "threads.net",
  "pinterest.com",
];

const EMAIL_HOSTS = [
  "mail.google.com",
  "outlook.live.com",
  "mail.yahoo.com",
  "proton.me",
  "protonmail.com",
];

const SEARCH_SOURCE_HINTS = [
  "google",
  "bing",
  "duckduckgo",
  "yahoo",
  "search",
  "ecosia",
  "brave",
  "yandex",
  "baidu",
  "qwant",
  "naver",
  "perplexity",
];

const SOCIAL_SOURCE_HINTS = [
  "facebook",
  "fb",
  "instagram",
  "linkedin",
  "reddit",
  "youtube",
  "yt",
  "tiktok",
  "threads",
  "pinterest",
  "discord",
  "bluesky",
  "mastodon",
];

const EMAIL_SOURCE_HINTS = [
  "email",
  "newsletter",
  "gmail",
  "outlook",
  "mailchimp",
  "sendgrid",
  "convertkit",
  "substack",
];

const CLICK_ID_QUERY_PARAMS = new Set([
  "gclid",
  "gbraid",
  "wbraid",
  "dclid",
  "msclkid",
  "fbclid",
  "ttclid",
  "twclid",
  "li_fat_id",
  "yclid",
  "srsltid",
]);

const PAID_MEDIUM_HINTS = [
  "cpc",
  "ppc",
  "paid",
  "display",
  "affiliate",
  "retargeting",
  "remarketing",
];

const SOCIAL_MEDIUM_HINTS = ["social", "social_media", "social-network", "social-networking"];
const EMAIL_MEDIUM_HINTS = ["email", "e-mail", "newsletter"];
const DEFAULT_IGNORED_REFERRER_HOSTS = [
  "paypal.com",
  "stripe.com",
  "checkout.stripe.com",
  "shopify.com",
  "shop.app",
  "paddle.com",
  "klarna.com",
  "afterpay.com",
  "affirm.com",
  "braintreepayments.com",
  "squareup.com",
  "adyen.com",
];

let config: ClientConfig | null = null;
let collector: EventCollector | null = null;
let logger: Logger = createLogger(false);
let presenceMemo = new DailyPresenceMemo();
let failureCount = 0;
let breakerUntil = 0;
let uploadToken: string | null = null;
let uploadTokenExpiresAt: number | null = null;
let refreshPromise: Promise<string | null> | null = null;

let lastNormalizedPath: string | null = null;
let lastPageviewRouteAction = "";
let lastPageviewAt = 0;
let lastActivityAt = 0;
let autoeventsCleanup: Array<() => void> = [];
let conversionDedupCache = new Map<string, number>();
let inMemoryAttribution: AttributionContext | null = null;

type EnsureResult = { config: ClientConfig; collector: EventCollector };
type SourceClassification = {
  bucket: string;
  source: string;
};
type AttributionContext = SourceClassification & {
  capturedAtMs: number;
};
type ReferrerClassificationOptions = {
  ignoredReferrers?: string[];
  carryoverAttribution?: AttributionContext | null;
  nowMs?: number;
  carryoverWindowMs?: number;
};
type SignalNavigator = {
  doNotTrack?: string | null;
  msDoNotTrack?: string | null;
  globalPrivacyControl?: boolean | string | null;
};
type SignalWindow = {
  doNotTrack?: string | null;
};

function ensureConfigured(): EnsureResult {
  const currentConfig = config;
  const currentCollector = collector;
  if (!currentConfig || !currentCollector) {
    throw new Error("Marketing analytics SDK has not been configured.");
  }
  if (breakerUntil && Date.now() < breakerUntil) {
    throw new Error("Circuit breaker open; skipping event submission.");
  }
  return { config: currentConfig, collector: currentCollector };
}

function recordFailure(): void {
  failureCount += 1;
  if (failureCount >= CIRCUIT_BREAKER_LIMIT) {
    breakerUntil = Date.now() + CIRCUIT_BREAKER_DURATION_MS;
    logger.warn("Circuit breaker engaged; pausing dispatch for 5 minutes.");
  }
}

function recordSuccess(): void {
  failureCount = 0;
  breakerUntil = 0;
}

function buildEnvelope<T extends Record<string, unknown>>(
  activeConfig: ClientConfig,
  kind: EventKind,
  payload: T,
  epsilon: number,
  samplingRate: number
): EventEnvelope<T> {
  return {
    site_id: activeConfig.siteId,
    kind,
    payload,
    epsilon_used: epsilon,
    sampling_rate: samplingRate,
    client_timestamp: new Date().toISOString(),
    nonce: getRandomValuesHex(16),
  };
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function getUploadTokenValue(): string | null {
  return uploadToken;
}

async function bootstrapTokenIfNeeded(): Promise<void> {
  if (!config) return;
  if (uploadToken && uploadTokenExpiresAt && uploadTokenExpiresAt - nowSeconds() > (config.autoRefreshSkewSeconds ?? 60)) {
    return;
  }
  await refreshUploadToken();
}

async function refreshUploadToken(): Promise<string | null> {
  if (!config?.siteKey) {
    return uploadToken;
  }
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const endpoint = config?.bootstrapEndpoint ?? "/api/sdk/bootstrap";
    const apiBase = config?.apiBase ?? "";
    const response = await fetch(`${apiBase}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        site_key: config?.siteKey,
        site_id: config?.siteId && config.siteId !== "pending-site" ? config.siteId : undefined,
      }),
    });
    if (!response.ok) {
      logger.error(`Token bootstrap failed with ${response.status}`);
      return null;
    }
    const body = (await response.json()) as {
      upload_token: string;
      expires_at: string;
      config?: {
        site_id?: string;
        sampling_rate?: number;
        shuffle_url?: string;
      };
    };

    if (body.config && config) {
      if (body.config.site_id) {
        if (config.siteId && config.siteId !== "pending-site" && config.siteId !== body.config.site_id) {
          logger.warn(`Bootstrap site_id mismatch (${config.siteId} -> ${body.config.site_id}); applying server value.`);
        }
        config.siteId = body.config.site_id;
      }

      if (body.config.shuffle_url) {
        config.shuffleUrl = body.config.shuffle_url.startsWith("http")
          ? body.config.shuffle_url
          : `${config.apiBase ?? ""}${body.config.shuffle_url}`;
      }

      if (
        typeof body.config.sampling_rate === "number"
        && Number.isFinite(body.config.sampling_rate)
        && body.config.sampling_rate > 0
        && body.config.sampling_rate <= 1
      ) {
        config.samplingRate = body.config.sampling_rate;
      }
    }

    uploadToken = body.upload_token;
    uploadTokenExpiresAt = Math.floor(new Date(body.expires_at).getTime() / 1000);
    return uploadToken;
  })();
  const token = await refreshPromise;
  refreshPromise = null;
  return token;
}

function normalizePath(
  input: string,
  includeQuery: boolean,
  stripHash: boolean
): string {
  const url = new URL(input, window.location.origin);
  const query = includeQuery ? stripTrackingIdentifiersFromQuery(url.search) : "";
  const hash = stripHash ? "" : url.hash;
  return `${url.pathname}${query}${hash}`;
}

export function stripTrackingIdentifiersFromQuery(search: string): string {
  if (!search) return "";
  const query = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(query);
  for (const key of CLICK_ID_QUERY_PARAMS) {
    params.delete(key);
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

function isSignalAffirmative(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (value == null) return false;
  const normalized = String(value).trim().toLowerCase();
  return normalized === "1" || normalized === "yes" || normalized === "true";
}

export function isPrivacySignalEnabled(
  navigatorInput?: SignalNavigator | null,
  windowInput?: SignalWindow | null
): boolean {
  const nav = navigatorInput ?? (
    typeof navigator !== "undefined" ? (navigator as unknown as SignalNavigator) : null
  );
  const win = windowInput ?? (
    typeof window !== "undefined" ? (window as unknown as SignalWindow) : null
  );

  const dntEnabled = isSignalAffirmative(nav?.doNotTrack)
    || isSignalAffirmative(nav?.msDoNotTrack)
    || isSignalAffirmative(win?.doNotTrack);
  const gpcEnabled = isSignalAffirmative(nav?.globalPrivacyControl);

  return dntEnabled || gpcEnabled;
}

function isTrackingAllowed(activeConfig: ClientConfig): boolean {
  if (activeConfig.honorPrivacySignals === false) return true;
  return !isPrivacySignalEnabled();
}

function parseUrl(value: string, base: string): URL | null {
  try {
    return new URL(value, base);
  } catch {
    return null;
  }
}

function normalizeHost(hostname: string): string {
  return hostname
    .trim()
    .toLowerCase()
    .replace(/^\*\./, "")
    .replace(/^\./, "")
    .replace(/^www\./, "");
}

function hostMatches(hostname: string, candidates: string[]): boolean {
  const host = normalizeHost(hostname);
  return candidates.some((candidate) => {
    const normalized = normalizeHost(candidate);
    return host === normalized || host.endsWith(`.${normalized}`);
  });
}

function normalizeHostCandidate(input: string): string {
  const value = input.trim();
  if (!value) return "";

  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    const parsed = parseUrl(value, "https://example.invalid");
    if (parsed?.hostname) {
      return normalizeHost(parsed.hostname);
    }
  }

  const hostOnly = value.split("/")[0];
  return normalizeHost(hostOnly);
}

function normalizeIgnoredReferrers(referrers?: string[]): string[] {
  const candidates = referrers?.length ? referrers : DEFAULT_IGNORED_REFERRER_HOSTS;
  const normalized = new Set<string>();
  for (const candidate of candidates) {
    const host = normalizeHostCandidate(candidate);
    if (host) normalized.add(host);
  }
  return [...normalized];
}

function getSessionStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function parseStoredAttribution(raw: string | null): AttributionContext | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<AttributionContext>;
    if (
      typeof parsed.bucket === "string"
      && typeof parsed.source === "string"
      && typeof parsed.capturedAtMs === "number"
      && Number.isFinite(parsed.capturedAtMs)
    ) {
      return {
        bucket: parsed.bucket,
        source: parsed.source,
        capturedAtMs: parsed.capturedAtMs,
      };
    }
  } catch {
    // ignore malformed persisted values
  }
  return null;
}

function getAttributionContext(): AttributionContext | null {
  if (inMemoryAttribution) {
    return inMemoryAttribution;
  }
  const storage = getSessionStorage();
  if (!storage) return null;
  const parsed = parseStoredAttribution(storage.getItem(ATTRIBUTION_STORAGE_KEY));
  if (parsed) {
    inMemoryAttribution = parsed;
  }
  return parsed;
}

function setAttributionContext(source: SourceClassification, nowMs: number): void {
  if (!source.bucket || source.bucket === "direct") {
    return;
  }
  const context: AttributionContext = {
    bucket: source.bucket,
    source: source.source,
    capturedAtMs: nowMs,
  };
  inMemoryAttribution = context;
  const storage = getSessionStorage();
  if (!storage) return;
  try {
    storage.setItem(ATTRIBUTION_STORAGE_KEY, JSON.stringify(context));
  } catch {
    // ignore storage write failures
  }
}

function resolveCarryoverAttribution(
  options: ReferrerClassificationOptions | undefined
): SourceClassification | null {
  const carryover = options?.carryoverAttribution;
  if (!carryover) return null;

  const nowMs = options?.nowMs ?? Date.now();
  const windowMs = options?.carryoverWindowMs ?? DEFAULT_ATTRIBUTION_CARRYOVER_MS;
  if (windowMs <= 0) return null;
  if (nowMs - carryover.capturedAtMs > windowMs) return null;

  if (!carryover.bucket || !carryover.source) return null;
  return { bucket: carryover.bucket, source: carryover.source };
}

function directSource(): SourceClassification {
  return { bucket: "direct", source: "Direct" };
}

function classifyByMedium(utmMedium: string): string | null {
  if (!utmMedium) return null;
  const medium = utmMedium.trim().toLowerCase();
  if (!medium) return null;
  if (PAID_MEDIUM_HINTS.some((hint) => medium.includes(hint))) return "paid";
  if (EMAIL_MEDIUM_HINTS.some((hint) => medium.includes(hint))) return "email";
  if (SOCIAL_MEDIUM_HINTS.some((hint) => medium.includes(hint))) return "social";
  if (medium === "organic") return "organic";
  if (medium === "referral" || medium === "app" || medium === "link") return "referral";
  return null;
}

function sourceLabelFromHost(hostname: string): string {
  const host = normalizeHost(hostname);
  return host || "Unknown";
}

function classifyBySource(utmSource: string): string | null {
  if (!utmSource) return null;
  const source = utmSource.trim().toLowerCase();
  if (!source) return null;
  if (source === "direct" || source === "(direct)") return "direct";
  if (EMAIL_SOURCE_HINTS.some((hint) => source.includes(hint))) return "email";
  if (SOCIAL_SOURCE_HINTS.some((hint) => source === hint || source.includes(hint))) return "social";
  if (SEARCH_SOURCE_HINTS.some((hint) => source === hint || source.includes(hint))) return "organic";
  return null;
}

export function classifyReferrerBucket(currentHref?: string, referrerHref?: string): {
  bucket: string;
  source: string;
};
export function classifyReferrerBucket(
  currentHref?: string,
  referrerHref?: string,
  options?: ReferrerClassificationOptions
): SourceClassification;
export function classifyReferrerBucket(
  currentHref?: string,
  referrerHref?: string,
  options?: ReferrerClassificationOptions
): SourceClassification {
  const fallbackOrigin = "https://example.invalid";
  const activeHref = currentHref ?? (typeof window !== "undefined" ? window.location.href : fallbackOrigin);
  const currentUrl = parseUrl(activeHref, fallbackOrigin);
  if (!currentUrl) {
    return directSource();
  }

  const utmSource = (
    currentUrl.searchParams.get("utm_source")
    ?? currentUrl.searchParams.get("source")
    ?? currentUrl.searchParams.get("ref")
    ?? ""
  ).trim().toLowerCase();
  const utmMedium = (
    currentUrl.searchParams.get("utm_medium")
    ?? currentUrl.searchParams.get("medium")
    ?? ""
  ).trim().toLowerCase();
  const hasPaidClickId = [
    "gclid",
    "msclkid",
    "fbclid",
    "ttclid",
    "li_fat_id",
  ].some((key) => Boolean(currentUrl.searchParams.get(key)));

  if (hasPaidClickId) {
    return { bucket: "paid", source: utmSource || "Paid" };
  }

  const mediumBucket = classifyByMedium(utmMedium);
  if (mediumBucket) {
    return { bucket: mediumBucket, source: utmSource || mediumBucket };
  }

  const sourceBucket = classifyBySource(utmSource);
  if (sourceBucket) {
    return { bucket: sourceBucket, source: sourceBucket === "direct" ? "Direct" : utmSource };
  }

  if (utmSource) {
    return { bucket: "referral", source: utmSource };
  }

  const activeReferrer = referrerHref ?? (typeof document !== "undefined" ? document.referrer : "");
  if (!activeReferrer) {
    return directSource();
  }

  const referrerUrl = parseUrl(activeReferrer, currentUrl.origin);
  if (!referrerUrl) {
    return directSource();
  }

  if (normalizeHost(referrerUrl.hostname) === normalizeHost(currentUrl.hostname)) {
    return directSource();
  }

  const ignoredReferrers = normalizeIgnoredReferrers(options?.ignoredReferrers);
  if (hostMatches(referrerUrl.hostname, ignoredReferrers)) {
    return resolveCarryoverAttribution(options) ?? directSource();
  }

  if (hostMatches(referrerUrl.hostname, SEARCH_ENGINE_HOSTS)) {
    return { bucket: "organic", source: sourceLabelFromHost(referrerUrl.hostname) };
  }
  if (hostMatches(referrerUrl.hostname, SOCIAL_HOSTS)) {
    return { bucket: "social", source: sourceLabelFromHost(referrerUrl.hostname) };
  }
  if (hostMatches(referrerUrl.hostname, EMAIL_HOSTS)) {
    return { bucket: "email", source: sourceLabelFromHost(referrerUrl.hostname) };
  }
  return { bucket: "referral", source: sourceLabelFromHost(referrerUrl.hostname) };
}

function maybeSendSessionStart(sessionInactivityMs: number): void {
  const now = Date.now();
  const lastSeen = lastActivityAt;
  if (!lastSeen || now - lastSeen > sessionInactivityMs) {
    const source = classifyReferrerBucket(undefined, undefined, {
      ignoredReferrers: config?.ignoredReferrers,
      carryoverAttribution: getAttributionContext(),
      nowMs: now,
      carryoverWindowMs: config?.attributionCarryoverMs ?? sessionInactivityMs,
    });
    sendSessionStart({
      referrerBucket: source.bucket,
      referrerSource: source.source,
      engagementBucket: "start",
    });
    setAttributionContext(source, now);
  }
  lastActivityAt = now;
}

function emitPageviewForCurrentRoute(routeAction: string, autoConfig: AutoeventsConfig): void {
  const includeQuery = autoConfig.includeQueryInPath ?? config?.includeQueryInPath ?? false;
  const stripHash = autoConfig.stripHashInPath ?? config?.stripHashInPath ?? true;
  const normalized = normalizePath(window.location.href, includeQuery, stripHash);
  if (!shouldEmitAutoPageview(normalized, routeAction)) {
    return;
  }
  sendPageview(normalized, { auto: true, route_action: routeAction });
}

export function shouldEmitAutoPageview(normalizedPath: string, routeAction: string): boolean {
  const now = Date.now();
  if (normalizedPath === lastNormalizedPath) {
    if (routeAction === lastPageviewRouteAction) {
      return false;
    }
    if (now - lastPageviewAt < 750) {
      return false;
    }
  }

  lastNormalizedPath = normalizedPath;
  lastPageviewRouteAction = routeAction;
  lastPageviewAt = now;
  return true;
}

function resetAutoevents(): void {
  for (const dispose of autoeventsCleanup) {
    dispose();
  }
  autoeventsCleanup = [];
  conversionDedupCache = new Map();
}

function sanitizeConversionHint(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) return "";
  return trimmed.replace(/[^a-z0-9_-]/g, "_").slice(0, 64);
}

export function normalizeAutoConversionType(value: string | null | undefined): string {
  return sanitizeConversionHint(value);
}

function sanitizeRevenueAmount(value: unknown): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return parsed;
}

function sanitizeCurrencyCode(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const normalized = value.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(normalized)) return undefined;
  return normalized;
}

function sanitizeOrderId(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const normalized = value.trim();
  if (!normalized) return undefined;
  return normalized.slice(0, 128);
}

function dedupeConversionEvent(key: string, dedupeWindowMs: number): boolean {
  const now = Date.now();
  const last = conversionDedupCache.get(key);
  if (typeof last === "number" && now - last < dedupeWindowMs) {
    return false;
  }
  conversionDedupCache.set(key, now);
  if (conversionDedupCache.size > 1000) {
    const cutoff = now - dedupeWindowMs;
    for (const [entryKey, ts] of conversionDedupCache.entries()) {
      if (ts < cutoff) conversionDedupCache.delete(entryKey);
    }
  }
  return true;
}

export function shouldEmitAutoConversion(
  key: string,
  dedupeWindowMs: number = DEFAULT_CONVERSION_DEDUPE_MS
): boolean {
  return dedupeConversionEvent(key, dedupeWindowMs);
}

export async function configure(userConfig: ClientConfig): Promise<void> {
  if (!userConfig.shuffleUrl && !userConfig.apiBase) {
    throw new Error("shuffleUrl or apiBase is required.");
  }
  if (!userConfig.siteId && !userConfig.siteKey) {
    throw new Error("siteId or siteKey is required.");
  }

  const resolvedShuffleUrl = userConfig.shuffleUrl ?? `${userConfig.apiBase ?? ""}/api/shuffle`;
  const resolvedSiteId = userConfig.siteId ?? "pending-site";
  const normalizedIgnoredReferrers = normalizeIgnoredReferrers(userConfig.ignoredReferrers);
  config = {
    ...userConfig,
    siteId: resolvedSiteId,
    shuffleUrl: resolvedShuffleUrl,
    flushIntervalMs: userConfig.flushIntervalMs ?? THREE_MINUTES_MS,
    maxBatchSize: userConfig.maxBatchSize ?? 50,
    includeQueryInPath: userConfig.includeQueryInPath ?? false,
    stripHashInPath: userConfig.stripHashInPath ?? true,
    honorPrivacySignals: userConfig.honorPrivacySignals ?? true,
    autoRefreshSkewSeconds: userConfig.autoRefreshSkewSeconds ?? 60,
    ignoredReferrers: normalizedIgnoredReferrers,
    attributionCarryoverMs: userConfig.attributionCarryoverMs ?? DEFAULT_ATTRIBUTION_CARRYOVER_MS,
  };
  logger = createLogger(Boolean(userConfig.debug));

  uploadToken = userConfig.uploadToken ?? null;
  uploadTokenExpiresAt = null;

  if (!uploadToken && config.siteKey) {
    await bootstrapTokenIfNeeded();
    if (!uploadToken) {
      throw new Error("Token bootstrap failed.");
    }
  }
  if (!config.siteId || config.siteId === "pending-site") {
    throw new Error("siteId is unresolved; set data-valid-site-id or allow bootstrap config.");
  }
  collector = new EventCollector(config, logger, recordFailure, recordSuccess, getUploadTokenValue, refreshUploadToken);
  presenceMemo = new DailyPresenceMemo(userConfig.presenceEpsilonCap ?? 1.5);
  logger.debug("Marketing analytics SDK configured.");
}

export async function initAutoevents(autoConfig: AutoeventsConfig = {}): Promise<void> {
  const { config: activeConfig } = ensureConfigured();
  if (!isTrackingAllowed(activeConfig)) {
    logger.debug("Privacy signal detected (DNT/GPC); autoevents are disabled.");
    return;
  }
  resetAutoevents();
  await bootstrapTokenIfNeeded();

  const sessionInactivityMs = autoConfig.sessionInactivityMs ?? DEFAULT_SESSION_INACTIVITY_MS;
  maybeSendSessionStart(sessionInactivityMs);
  emitPageviewForCurrentRoute("initial-load", autoConfig);
  reportPresence();

  const onPopState = () => {
    maybeSendSessionStart(sessionInactivityMs);
    emitPageviewForCurrentRoute("popstate", autoConfig);
  };
  const onHashChange = () => {
    maybeSendSessionStart(sessionInactivityMs);
    emitPageviewForCurrentRoute("hashchange", autoConfig);
  };
  window.addEventListener("popstate", onPopState);
  window.addEventListener("hashchange", onHashChange);
  autoeventsCleanup.push(() => window.removeEventListener("popstate", onPopState));
  autoeventsCleanup.push(() => window.removeEventListener("hashchange", onHashChange));

  const historyMethods: Array<"pushState" | "replaceState"> = ["pushState", "replaceState"];
  for (const method of historyMethods) {
    const original = window.history[method].bind(window.history);
    (window.history[method] as typeof window.history.pushState) = ((...args: unknown[]) => {
      const result = original(...(args as [unknown, string, (string | URL | null | undefined)]));
      maybeSendSessionStart(sessionInactivityMs);
      emitPageviewForCurrentRoute(method, autoConfig);
      return result;
    }) as typeof window.history.pushState;
    autoeventsCleanup.push(() => {
      (window.history[method] as typeof window.history.pushState) = original as typeof window.history.pushState;
    });
  }

  const autoConversionsEnabled = autoConfig.autoConversions ?? true;
  if (autoConversionsEnabled) {
    const dedupeWindowMs = Math.max(5000, Math.min(30000, autoConfig.conversionDedupeWindowMs ?? DEFAULT_CONVERSION_DEDUPE_MS));
    const selector = autoConfig.conversionSelector ?? "[data-valid-conversion]";

    const conversionMetaFromNode = (node: HTMLElement | null): Pick<ConversionEventPayload, "revenueAmount" | "revenueCurrency" | "orderId"> => {
      if (!node) return {};
      return {
        revenueAmount: sanitizeRevenueAmount(
          node.getAttribute("data-valid-revenue")
          ?? node.getAttribute("data-valid-revenue-amount")
        ) ?? undefined,
        revenueCurrency: sanitizeCurrencyCode(
          node.getAttribute("data-valid-currency")
          ?? node.getAttribute("data-valid-revenue-currency")
        ),
        orderId: sanitizeOrderId(node.getAttribute("data-valid-order-id")),
      };
    };

    const emitConversion = (
      type: string,
      signature: string,
      payload: Pick<ConversionEventPayload, "revenueAmount" | "revenueCurrency" | "orderId"> = {}
    ) => {
      const cleanType = sanitizeConversionHint(type);
      if (!cleanType) return;
      const dedupeKey = `${cleanType}:${signature}`;
      if (!dedupeConversionEvent(dedupeKey, dedupeWindowMs)) {
        return;
      }
      sendConversion({ conversionType: cleanType, ...payload });
    };

    const onClick = (event: Event) => {
      const target = event.target as HTMLElement | null;
      const node = target?.closest(selector) as HTMLElement | null;
      if (node) {
        const conversionType = sanitizeConversionHint(node.getAttribute("data-valid-conversion"));
        if (conversionType) {
          emitConversion(conversionType, `attr:${node.tagName}`, conversionMetaFromNode(node));
          return;
        }
      }

      const link = target?.closest("a[href]") as HTMLAnchorElement | null;
      if (!link) return;
      const rawHref = link.getAttribute("href") ?? "";
      const href = rawHref.trim();
      if (!href) return;
      if (href.toLowerCase().startsWith("mailto:")) {
        emitConversion("mailto_click", "mailto");
        return;
      }
      if (href.toLowerCase().startsWith("tel:")) {
        emitConversion("tel_click", "tel");
        return;
      }
      try {
        const resolved = new URL(href, window.location.origin);
        const isExternal = resolved.host !== window.location.host;
        if (isExternal && (resolved.protocol === "http:" || resolved.protocol === "https:")) {
          emitConversion("outbound_click", `outbound:${resolved.host}${resolved.pathname}`);
        }
      } catch {
        // ignore invalid URLs
      }
    };
    document.addEventListener("click", onClick, true);
    autoeventsCleanup.push(() => document.removeEventListener("click", onClick, true));

    const onSubmit = (event: Event) => {
      const form = event.target as HTMLFormElement | null;
      if (!form) return;
      const markedElement = form.closest(selector) as HTMLElement | null;
      const explicitType = sanitizeConversionHint(markedElement?.getAttribute("data-valid-conversion"));
      if (explicitType) {
        emitConversion(
          explicitType,
          `form:${form.getAttribute("id") ?? form.getAttribute("name") ?? "anon"}`,
          conversionMetaFromNode(markedElement)
        );
        return;
      }

      emitConversion(
        "form_submit",
        `form:${form.getAttribute("id") ?? form.getAttribute("name") ?? "anon"}:${window.location.pathname}`
      );
    };
    document.addEventListener("submit", onSubmit, true);
    autoeventsCleanup.push(() => document.removeEventListener("submit", onSubmit, true));
  }
}

export function enableDebug(): void {
  logger.enable();
}

export function sendPageview(url: string, metadata: Record<string, unknown> = {}): boolean {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
  if (!isTrackingAllowed(activeConfig)) {
    logger.debug("Privacy signal detected (DNT/GPC); skipping pageview.");
    return false;
  }
  if (!shouldSample(activeConfig.samplingRate)) {
    logger.debug("Pageview dropped by sampling.");
    return false;
  }

  const rr = rrBit(true, activeConfig.epsilon.pageview, activeConfig.samplingRate);
  const envelope = buildEnvelope(
    activeConfig,
    "pageviews",
    {
      url,
      randomized_bit: rr.bit,
      probability_true: rr.p,
      probability_false: rr.q,
      variance: rr.variance,
      metadata,
    },
    activeConfig.epsilon.pageview,
    activeConfig.samplingRate
  );
  activeCollector.enqueue(envelope);
  return true;
}

export function sendSessionStart(payload: SessionEventPayload): boolean {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
  if (!isTrackingAllowed(activeConfig)) {
    logger.debug("Privacy signal detected (DNT/GPC); skipping session start.");
    return false;
  }
  if (!shouldSample(activeConfig.samplingRate)) {
    logger.debug("Session start dropped by sampling.");
    return false;
  }

  const rr = rrBit(true, activeConfig.epsilon.session, activeConfig.samplingRate);
  const envelope = buildEnvelope(
    activeConfig,
    "sessions",
    {
      randomized_bit: rr.bit,
      probability_true: rr.p,
      probability_false: rr.q,
      variance: rr.variance,
      referrer_bucket: payload.referrerBucket,
      referrer_source: payload.referrerSource,
      engagement_bucket: payload.engagementBucket,
    },
    activeConfig.epsilon.session,
    activeConfig.samplingRate
  );
  activeCollector.enqueue(envelope);
  return true;
}

export function sendConversion(payload: ConversionEventPayload): boolean {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
  if (!isTrackingAllowed(activeConfig)) {
    logger.debug("Privacy signal detected (DNT/GPC); skipping conversion.");
    return false;
  }
  if (!shouldSample(activeConfig.samplingRate)) {
    logger.debug("Conversion dropped by sampling.");
    return false;
  }

  const conversionType = sanitizeConversionHint(payload.conversionType);
  if (!conversionType) {
    logger.warn("Skipping conversion with empty conversionType.");
    return false;
  }
  const orderId = sanitizeOrderId(payload.orderId);
  const revenueAmount = sanitizeRevenueAmount(payload.revenueAmount);
  const revenueCurrency = sanitizeCurrencyCode(payload.revenueCurrency);

  const rr = rrBit(true, activeConfig.epsilon.conversion, activeConfig.samplingRate);
  const envelope = buildEnvelope(
    activeConfig,
    "conversions",
    {
      conversion_type: conversionType,
      ...(orderId ? { order_id: orderId } : {}),
      randomized_bit: rr.bit,
      probability_true: rr.p,
      probability_false: rr.q,
      variance: rr.variance,
    },
    activeConfig.epsilon.conversion,
    activeConfig.samplingRate
  );
  activeCollector.enqueue(envelope);

  if (revenueAmount !== null) {
    const revenueEnvelope = buildEnvelope(
      activeConfig,
      "revenue",
      {
        value: revenueAmount,
        ...(revenueCurrency ? { currency: revenueCurrency } : {}),
        conversion_type: conversionType,
        ...(orderId ? { order_id: orderId } : {}),
        randomized_bit: rr.bit,
        probability_true: rr.p,
        probability_false: rr.q,
        variance: rr.variance,
      },
      activeConfig.epsilon.conversion,
      activeConfig.samplingRate
    );
    activeCollector.enqueue(revenueEnvelope);
  }

  return true;
}

export function sendPurchase(payload: PurchaseEventPayload): boolean {
  return sendConversion({
    conversionType: payload.conversionType ?? "purchase",
    revenueAmount: payload.revenueAmount,
    revenueCurrency: payload.revenueCurrency,
    orderId: payload.orderId,
  });
}

export function reportPresence(): PresenceReport | null {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
  if (!isTrackingAllowed(activeConfig)) {
    logger.debug("Privacy signal detected (DNT/GPC); skipping presence.");
    return null;
  }
  const report = presenceMemo.getDailyPresence(
    activeConfig.epsilon.presence,
    activeConfig.samplingRate
  );
  if (!report) {
    logger.warn("Presence epsilon cap hit; skipping presence report.");
    return null;
  }
  activeCollector.enqueue(
    buildEnvelope(
      activeConfig,
      "uniques",
      {
        randomized_bit: report.bit,
        probability_true: report.p,
        probability_false: report.q,
        variance: report.variance,
      },
      activeConfig.epsilon.presence,
      activeConfig.samplingRate
    )
  );
  return report;
}

export function flush(): Promise<void> {
  const { collector: activeCollector } = ensureConfigured();
  return activeCollector.flush("manual");
}

export function getAdjustedProbability(epsilon: number, samplingRate: number): {
  p: number;
  q: number;
} {
  return adjustedProbability(epsilon, samplingRate);
}

export function destroyAutoevents(): void {
  resetAutoevents();
}

export async function init(configInput: ClientConfig, autoConfig: AutoeventsConfig = {}): Promise<void> {
  await configure(configInput);
  await initAutoevents(autoConfig);
}

declare global {
  interface Window {
    ValidAnalytics?: {
      configure: typeof configure;
      init: typeof init;
      initAutoevents: typeof initAutoevents;
      sendPageview: typeof sendPageview;
      sendSessionStart: typeof sendSessionStart;
      sendConversion: typeof sendConversion;
      sendPurchase: typeof sendPurchase;
      reportPresence: typeof reportPresence;
      flush: typeof flush;
      destroyAutoevents: typeof destroyAutoevents;
    };
  }
}

if (typeof window !== "undefined") {
  window.ValidAnalytics = {
    configure,
    init,
    initAutoevents,
    sendPageview,
    sendSessionStart,
    sendConversion,
    sendPurchase,
    reportPresence,
    flush,
    destroyAutoevents,
  };

  const currentScript = document.currentScript as HTMLScriptElement | null;
  if (currentScript?.dataset?.validSiteKey) {
    const apiBase = currentScript.dataset.validApiBase ?? "";
    const siteId = currentScript.dataset.validSiteId ?? "pending-site";
    const sampleRate = Number(currentScript.dataset.validSampleRate ?? "1");
    const debug = currentScript.dataset.validDebug === "true";
    const honorPrivacySignals = currentScript.dataset.validHonorPrivacySignals !== "false";
    const autoConversions = currentScript.dataset.validAutoconversions !== "false";
    const conversionSelector = currentScript.dataset.validConversionSelector;
    const ignoredReferrers = (currentScript.dataset.validIgnoredReferrers ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const attributionCarryoverMinutes = Number(currentScript.dataset.validAttributionCarryoverMinutes ?? "");
    const attributionCarryoverMs = Number.isFinite(attributionCarryoverMinutes) && attributionCarryoverMinutes > 0
      ? attributionCarryoverMinutes * 60 * 1000
      : undefined;
    void init({
      siteId,
      apiBase,
      siteKey: currentScript.dataset.validSiteKey,
      shuffleUrl: `${apiBase}/api/shuffle`,
      samplingRate: Number.isFinite(sampleRate) ? sampleRate : 1,
      epsilon: {
        presence: 0.5,
        pageview: 0.5,
        session: 0.5,
        conversion: 0.5,
      },
      debug,
      honorPrivacySignals,
      ignoredReferrers: ignoredReferrers.length ? ignoredReferrers : undefined,
      attributionCarryoverMs,
    }, {
      autoConversions,
      conversionSelector,
    });
  }
}

// Validate crypto eagerly in browser environments.
if (typeof window !== "undefined") {
  getCrypto();
}
