export type EventKind =
  | "uniques"
  | "pageviews"
  | "sessions"
  | "conversions"
  | "revenue";

export interface ClientConfig {
  siteId: string;
  shuffleUrl: string;
  uploadToken?: string;
  siteKey?: string;
  apiBase?: string;
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
  includeQueryInPath?: boolean;
  stripHashInPath?: boolean;
  honorPrivacySignals?: boolean;
  autoRefreshSkewSeconds?: number;
  refreshEndpoint?: string;
  bootstrapEndpoint?: string;
  ignoredReferrers?: string[];
  attributionCarryoverMs?: number;
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
  referrerSource?: string;
  utmSource?: string;
  utmMedium?: string;
  utmCampaign?: string;
  utmContent?: string;
  utmTerm?: string;
  paidClickId?: string;
  engagementBucket: string;
}

export interface ConversionEventPayload {
  conversionType: string;
  revenueAmount?: number;
  revenueCurrency?: string;
  orderId?: string;
}

export interface PurchaseEventPayload {
  revenueAmount: number;
  revenueCurrency: string;
  orderId?: string;
  conversionType?: string;
}

export interface AutoeventsConfig {
  autoConversions?: boolean;
  conversionSelector?: string;
  conversionDedupeWindowMs?: number;
  sessionInactivityMs?: number;
  includeQueryInPath?: boolean;
  stripHashInPath?: boolean;
}
