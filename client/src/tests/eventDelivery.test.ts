import { webcrypto } from "crypto";
import { EventCollector } from "../collector/eventCollector";
import { ClientConfig, EventEnvelope } from "../types";

Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
const config: ClientConfig = {
  siteId: "delivery-test", shuffleUrl: "https://api.example.test/api/shuffle", samplingRate: 1,
  epsilon: { presence: 1, pageview: 1, session: 1, conversion: 1 }, maxBatchSize: 50, flushIntervalMs: 1000,
};
const logger = { debug: jest.fn(), warn: jest.fn(), error: jest.fn(), enable: jest.fn() };
const event = (nonce = "stable-event"): EventEnvelope => ({
  site_id: config.siteId!, kind: "pageviews", payload: { url: "/" },
  epsilon_used: 1, sampling_rate: 1, client_timestamp: new Date().toISOString(), nonce,
});

describe("event delivery", () => {
  const originalFetch = globalThis.fetch;
  let collector: EventCollector;
  let fetchMock: jest.Mock;

  beforeEach(() => {
    jest.useFakeTimers();
    fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 202 });
    globalThis.fetch = fetchMock;
    collector = new EventCollector(config, logger, jest.fn(), jest.fn(), () => "token", async () => "new-token");
  });
  afterEach(() => {
    collector.destroy();
    jest.useRealTimers();
    globalThis.fetch = originalFetch;
  });

  it("sends within the short flush interval without waiting for another event", async () => {
    collector.enqueue(event());
    await jest.advanceTimersByTimeAsync(1250);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ keepalive: true, credentials: "omit" });
  });

  it("retries network failures automatically with a new request nonce and stable event nonce", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Network disconnected"));
    collector.enqueue(event());
    await collector.flush("initial-load");
    await jest.advanceTimersByTimeAsync(2250);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const first = JSON.parse(fetchMock.mock.calls[0][1].body);
    const retry = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(retry.nonce).not.toBe(first.nonce);
    expect(retry.batch).toEqual(first.batch);
  });

  it("does not send the same batch twice when visibility/pagehide flushes overlap", async () => {
    let finish!: (value: { ok: boolean; status: number }) => void;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    collector.enqueue(event());
    const first = collector.flush("visibilitychange");
    const second = collector.flush("pagehide");
    collector.enqueue(event("second-event"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish({ ok: true, status: 202 });
    await Promise.all([first, second]);
    await jest.advanceTimersByTimeAsync(1250);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).batch[0].nonce).toBe("second-event");
  });

  it("does not restart retries after destruction", async () => {
    fetchMock.mockRejectedValue(new TypeError("Offline"));
    collector.enqueue(event());
    await collector.flush("test");
    collector.destroy();
    await jest.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("flushes new exit events even while the initial request is pending", async () => {
    let finish!: (value: { ok: boolean; status: number }) => void;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    collector.enqueue(event("initial"));
    const initial = collector.flush("initial-load");
    collector.enqueue(event("exit-conversion"));
    const exit = collector.flush("pagehide");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).batch[0].nonce).toBe("exit-conversion");
    finish({ ok: true, status: 202 });
    await Promise.all([initial, exit]);
    await jest.advanceTimersByTimeAsync(1250);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("drops expired retry events rather than keeping an unbounded offline queue", async () => {
    fetchMock.mockRejectedValue(new TypeError("Offline"));
    const oldEvent = event();
    oldEvent.client_timestamp = new Date(Date.now() - 301_000).toISOString();
    collector.enqueue(oldEvent);
    await collector.flush("test");
    await jest.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
