import { ClientConfig, EventEnvelope } from "../types";
import { Logger } from "../utils/logger";
import { getRandomValuesHex } from "../utils/crypto";

const JITTER_RANGE_MS = 250;

function browserTimeZone(): string | null {
  if (typeof Intl === "undefined") {
    return null;
  }
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return typeof timeZone === "string" && /^[A-Za-z0-9._/+:-]{1,64}$/.test(timeZone) ? timeZone : null;
  } catch {
    return null;
  }
}

export class EventCollector {
  private buffer: EventEnvelope[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private backoffMs = 1000;
  private readonly maxBackoffMs = 60000;
  private readonly inFlight = new Set<Promise<void>>();
  private destroyed = false;
  private readonly visibilityListener: (() => void) | null = null;

  constructor(
    private readonly config: ClientConfig,
    private readonly logger: Logger,
    private readonly onFailure: () => void,
    private readonly onSuccess: () => void,
    private readonly getUploadToken: () => string | null,
    private readonly refreshUploadToken: () => Promise<string | null>
  ) {
    this.visibilityListener = this.setupVisibilityObservers();
  }

  enqueue(event: EventEnvelope): void {
    if (this.destroyed) return;
    this.buffer.push(event);
    this.logger.debug(`Enqueued ${event.kind}. buffer=${this.buffer.length}`);
    if (this.buffer.length >= this.config.maxBatchSize!) {
      void this.flush("max-batch");
      return;
    }
    this.scheduleFlush();
  }

  async flush(reason: string): Promise<void> {
    const leavingPage = reason === "visibilitychange" || reason === "pagehide";
    if (this.inFlight.size && !leavingPage) {
      await Promise.all(this.inFlight);
      return;
    }
    if (this.buffer.length === 0 || this.destroyed) {
      await Promise.all(this.inFlight);
      return;
    }
    const batch = this.buffer.splice(0, this.config.maxBatchSize ?? 50);
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    this.logger.debug(`Flushing ${batch.length} events because ${reason}`);
    // A page-exit flush must not wait for a previous request to acknowledge:
    // mobile browsers can suspend the page before that callback runs.
    const request = this.postBatch(batch).then(() => {
      this.backoffMs = 1000;
      this.onSuccess();
    }).catch((error: unknown) => {
      this.logger.error("Failed to flush batch", error as Error);
      this.onFailure();
      this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
      // Preserve event nonces across retries; the API deduplicates accepted events.
      // Keep the in-memory queue bounded during extended network outages.
      this.buffer = [...batch, ...this.buffer]
        .filter((event) => Date.now() - Date.parse(event.client_timestamp) <= 300_000)
        .slice(-500);
    }).finally(() => {
      this.inFlight.delete(request);
      if (this.buffer.length > 0) this.scheduleFlush(this.backoffMs);
    });
    this.inFlight.add(request);
    return request;
  }

  private scheduleFlush(delayMs = this.config.flushIntervalMs ?? 1000): void {
    if (this.flushTimer || this.destroyed) {
      return;
    }
    const jitter = Math.floor(Math.random() * JITTER_RANGE_MS);
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      void this.flush("interval");
    }, delayMs + jitter);
  }

  private async postBatch(batch: EventEnvelope[]): Promise<void> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const token = this.getUploadToken();
      if (!token) {
        throw new Error("Upload token unavailable");
      }
      const response = await this.sendBatch(batch, token, controller.signal);
      if (response.status === 401) {
        const refreshed = await this.refreshUploadToken();
        if (refreshed) {
          const retry = await this.sendBatch(batch, refreshed, controller.signal);
          if (retry.ok) {
            return;
          }
          throw new Error(`Shuffle endpoint responded with ${retry.status} after refresh`);
        }
      }
      if (!response.ok) {
        throw new Error(`Shuffle endpoint responded with ${response.status}`);
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  private sendBatch(batch: EventEnvelope[], token: string, signal: AbortSignal): Promise<Response> {
    const timeZone = browserTimeZone();
    return fetch(this.config.shuffleUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(timeZone ? { "X-Timezone": timeZone } : {}),
      },
      body: JSON.stringify({
        token,
        // Request replay protection is separate from stable per-event identity.
        nonce: getRandomValuesHex(16),
        batch,
      }),
      signal,
      keepalive: true,
      credentials: "omit",
    });
  }

  private setupVisibilityObservers(): (() => void) | null {
    if (typeof window === "undefined" || typeof document === "undefined") {
      return null;
    }

    const visibilityHandler = () => {
      if (document.visibilityState === "hidden") {
        void this.flush("visibilitychange");
      }
    };
    const pageHideHandler = () => {
      void this.flush("pagehide");
    };
    const onlineHandler = () => {
      void this.flush("online");
    };

    document.addEventListener("visibilitychange", visibilityHandler);
    window.addEventListener("pagehide", pageHideHandler);
    window.addEventListener("online", onlineHandler);

    return () => {
      document.removeEventListener("visibilitychange", visibilityHandler);
      window.removeEventListener("pagehide", pageHideHandler);
      window.removeEventListener("online", onlineHandler);
    };
  }

  destroy(): void {
    this.destroyed = true;
    if (this.visibilityListener) {
      this.visibilityListener();
    }
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
  }
}
