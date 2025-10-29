export interface Logger {
  debug(message: string, meta?: unknown): void;
  warn(message: string, meta?: unknown): void;
  error(message: string, error?: Error): void;
  enable(): void;
}

class ConsoleLogger implements Logger {
  private enabled: boolean;

  constructor(initiallyEnabled: boolean) {
    this.enabled = initiallyEnabled || process.env.NODE_ENV !== "production";
  }

  enable(): void {
    this.enabled = true;
  }

  debug(message: string, meta?: unknown): void {
    if (!this.enabled) return;
    console.debug(`[analytics-sdk] ${message}`, meta ?? "");
  }

  warn(message: string, meta?: unknown): void {
    if (!this.enabled) return;
    console.warn(`[analytics-sdk] ${message}`, meta ?? "");
  }

  error(message: string, error?: Error): void {
    if (!this.enabled) return;
    console.error(`[analytics-sdk] ${message}`, error);
  }
}

export function createLogger(enabled: boolean): Logger {
  return new ConsoleLogger(enabled);
}
