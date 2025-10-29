export type EventKind =
  | "uniques"
  | "pageviews"
  | "sessions"
  | "conversions";

export interface ClientConfig {
  siteId: string;
  shuffleUrl: string;
  uploadToken: string;
  samplingRate: number;
  epsilon: {
    presence: number;
    pageview: number;
    session: number;
    conversion: number;
  };
  maxBatchSize?: number;
  flushIntervalMs?: number;
  debug?: boolean;
  presenceEpsilonCap?: number;
}

export interface EventEnvelope<T = Record<string, unknown>> {
  site_id: string;
  kind: EventKind;
  payload: T;
  epsilon_used: number;
  sampling_rate: number;
  client_timestamp: string;
  nonce: string;
}

export interface PresenceReport {
  bit: 0 | 1;
  epsilon: number;
  p: number;
  q: number;
  variance: number;
}

export interface SessionEventPayload {
  referrerBucket: string;
  engagementBucket: string;
}

export interface ConversionEventPayload {
  conversionType: string;
}
