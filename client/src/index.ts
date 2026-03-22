import { EventCollector } from "./collector/eventCollector";
import { rrBit, adjustedProbability } from "./ldp/rr";
import { DailyPresenceMemo } from "./ldp/dailyPresence";
import { AutoeventsConfig, ClientConfig, ConversionEventPayload, EventEnvelope, EventKind, PresenceReport, SessionEventPayload } from "./types";
import { getCrypto, getRandomValuesHex, shouldSample } from "./utils/crypto";
import { createLogger, Logger } from "./utils/logger";

const CIRCUIT_BREAKER_LIMIT = 10;
const CIRCUIT_BREAKER_DURATION_MS = 5 * 60 * 1000;
const THREE_MINUTES_MS = 3 * 60 * 1000;
const DEFAULT_SESSION_INACTIVITY_MS = 30 * 60 * 1000;

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

type EnsureResult = { config: ClientConfig; collector: EventCollector };

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
  const query = includeQuery ? url.search : "";
  const hash = stripHash ? "" : url.hash;
  return `${url.pathname}${query}${hash}`;
}

function maybeSendSessionStart(sessionInactivityMs: number): void {
  const now = Date.now();
  if (!lastActivityAt || now - lastActivityAt > sessionInactivityMs) {
    sendSessionStart({
      referrerBucket: document.referrer ? "external" : "direct",
      engagementBucket: "start",
    });
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
  config = {
    ...userConfig,
    siteId: resolvedSiteId,
    shuffleUrl: resolvedShuffleUrl,
    flushIntervalMs: userConfig.flushIntervalMs ?? THREE_MINUTES_MS,
    maxBatchSize: userConfig.maxBatchSize ?? 50,
    includeQueryInPath: userConfig.includeQueryInPath ?? false,
    stripHashInPath: userConfig.stripHashInPath ?? true,
    autoRefreshSkewSeconds: userConfig.autoRefreshSkewSeconds ?? 60,
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
  ensureConfigured();
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

  const selector = autoConfig.conversionSelector ?? "[data-valid-conversion]";
  const onClick = (event: Event) => {
    const target = event.target as HTMLElement | null;
    const node = target?.closest(selector) as HTMLElement | null;
    if (!node) return;
    const conversionType = node.getAttribute("data-valid-conversion");
    if (!conversionType) return;
    sendConversion({ conversionType });
  };
  document.addEventListener("click", onClick, true);
  autoeventsCleanup.push(() => document.removeEventListener("click", onClick, true));
}

export function enableDebug(): void {
  logger.enable();
}

export function sendPageview(url: string, metadata: Record<string, unknown> = {}): boolean {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
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
  if (!shouldSample(activeConfig.samplingRate)) {
    logger.debug("Conversion dropped by sampling.");
    return false;
  }

  const rr = rrBit(true, activeConfig.epsilon.conversion, activeConfig.samplingRate);
  const envelope = buildEnvelope(
    activeConfig,
    "conversions",
    {
      conversion_type: payload.conversionType,
      randomized_bit: rr.bit,
      probability_true: rr.p,
      probability_false: rr.q,
      variance: rr.variance,
    },
    activeConfig.epsilon.conversion,
    activeConfig.samplingRate
  );
  activeCollector.enqueue(envelope);
  return true;
}

export function reportPresence(): PresenceReport | null {
  const { config: activeConfig, collector: activeCollector } = ensureConfigured();
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
    });
  }
}

// Validate crypto eagerly in browser environments.
if (typeof window !== "undefined") {
  getCrypto();
}
