import { rrBit, adjustedProbability } from "./ldp/rr";
import { DailyPresenceMemo } from "./ldp/dailyPresence";
import { EventCollector } from "./collector/eventCollector";
import { getCrypto, getRandomValuesHex, shouldSample } from "./utils/crypto";
import { createLogger, Logger } from "./utils/logger";
import {
  ClientConfig,
  EventEnvelope,
  EventKind,
  PresenceReport,
  SessionEventPayload,
  ConversionEventPayload,
} from "./types";

const CIRCUIT_BREAKER_LIMIT = 10;
const CIRCUIT_BREAKER_DURATION_MS = 5 * 60 * 1000;
const THREE_MINUTES_MS = 3 * 60 * 1000;

let config: ClientConfig | null = null;
let collector: EventCollector | null = null;
let logger: Logger = createLogger(false);
let presenceMemo = new DailyPresenceMemo();
let failureCount = 0;
let breakerUntil = 0;

function ensureConfigured(): { config: ClientConfig; collector: EventCollector } {
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

export function configure(userConfig: ClientConfig): void {
  if (!userConfig.shuffleUrl) {
    throw new Error("shuffleUrl is required.");
  }
  config = {
    ...userConfig,
    flushIntervalMs: userConfig.flushIntervalMs ?? THREE_MINUTES_MS,
    maxBatchSize: userConfig.maxBatchSize ?? 50,
  };
  logger = createLogger(Boolean(userConfig.debug));
  collector = new EventCollector(config, logger, recordFailure, recordSuccess);
  presenceMemo = new DailyPresenceMemo(userConfig.presenceEpsilonCap ?? 1.5);
  logger.debug("Marketing analytics SDK configured.");
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

// Ensure crypto is available immediately when this module loads.
getCrypto();
