import { ClientConfig, EventEnvelope } from "../types";
import { Logger } from "../utils/logger";

const JITTER_RANGE_MS = 250;

export class EventCollector {
  private buffer: EventEnvelope[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private backoffMs = 1000;
  private readonly maxBackoffMs = 60000;
  private readonly visibilityListener: (() => void) | null = null;

  constructor(
    private readonly config: ClientConfig,
    private readonly logger: Logger,
    private readonly onFailure: () => void,
    private readonly onSuccess: () => void
  ) {
    this.visibilityListener = this.setupVisibilityObservers();
  }

  enqueue(event: EventEnvelope): void {
    this.buffer.push(event);
    this.logger.debug(`Enqueued ${event.kind}. buffer=${this.buffer.length}`);
    if (this.buffer.length >= this.config.maxBatchSize!) {
      void this.flush("max-batch");
      return;
    }
    this.scheduleFlush();
  }

  async flush(reason: string): Promise<void> {
    if (this.buffer.length === 0) {
      return;
    }
    const batch = this.buffer.splice(0, this.buffer.length);
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    this.logger.debug(`Flushing ${batch.length} events because ${reason}`);
    try {
      await this.postBatch(batch);
      this.backoffMs = 1000;
      this.onSuccess();
    } catch (error) {
      this.logger.error("Failed to flush batch", error as Error);
      this.onFailure();
      this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
      this.buffer.unshift(...batch.slice(0, this.config.maxBatchSize!));
    }
  }

  private scheduleFlush(): void {
    if (this.flushTimer) {
      return;
    }
    const jitter = Math.floor(Math.random() * JITTER_RANGE_MS);
    this.flushTimer = setTimeout(() => {
      void this.flush("interval");
    }, this.config.flushIntervalMs! + jitter);
  }

  private async postBatch(batch: EventEnvelope[]): Promise<void> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(this.config.shuffleUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.config.uploadToken}`,
        },
        body: JSON.stringify({
          token: this.config.uploadToken,
          nonce: batch[0]?.nonce,
          batch,
        }),
        signal: controller.signal,
        keepalive: true,
      });
      if (!response.ok) {
        throw new Error(`Shuffle endpoint responded with ${response.status}`);
      }
    } finally {
      clearTimeout(timeout);
    }
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
    const unloadHandler = () => {
      void this.flush("beforeunload");
    };

    document.addEventListener("visibilitychange", visibilityHandler);
    window.addEventListener("beforeunload", unloadHandler);

    return () => {
      document.removeEventListener("visibilitychange", visibilityHandler);
      window.removeEventListener("beforeunload", unloadHandler);
    };
  }

  destroy(): void {
    if (this.visibilityListener) {
      this.visibilityListener();
    }
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
  }
}
