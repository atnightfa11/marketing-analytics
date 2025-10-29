import { rrBit } from "./rr";
import { PresenceReport } from "../types";

const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;

interface MemoizedPresence {
  epsilonTotal: number;
  report: PresenceReport;
}

export class DailyPresenceMemo {
  private memo = new Map<string, MemoizedPresence>();

  constructor(private epsilonCap: number = 1.5) {}

  private currentDayKey(): string {
    const now = new Date();
    const midnight = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    return midnight.toISOString();
  }

  getDailyPresence(epsilon: number, samplingRate: number): PresenceReport | null {
    const key = this.currentDayKey();
    const entry = this.memo.get(key);
    if (!entry) {
      const rr = rrBit(true, epsilon, samplingRate);
      const report: PresenceReport = {
        bit: rr.bit,
        epsilon,
        p: rr.p,
        q: rr.q,
        variance: rr.variance,
      };
      this.memo.set(key, { epsilonTotal: epsilon, report });
      this.trimOld();
      return report;
    }

    if (entry.epsilonTotal + epsilon > this.epsilonCap) {
      return null;
    }

    entry.epsilonTotal += epsilon;
    this.memo.set(key, entry);
    return entry.report;
  }

  private trimOld(): void {
    const now = Date.now();
    for (const [key] of this.memo) {
      if (now - Date.parse(key) > MILLISECONDS_PER_DAY) {
        this.memo.delete(key);
      }
    }
  }
}
