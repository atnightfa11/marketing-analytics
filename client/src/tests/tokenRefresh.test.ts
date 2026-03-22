import { EventCollector } from "../collector/eventCollector";
import { ClientConfig, EventEnvelope } from "../types";

const config: ClientConfig = {
  siteId: "site-a",
  shuffleUrl: "https://api.example.com/api/shuffle",
  samplingRate: 1,
  epsilon: { presence: 1, pageview: 1, session: 1, conversion: 1 },
  maxBatchSize: 50,
  flushIntervalMs: 5000,
};

function makeEvent(): EventEnvelope {
  return {
    site_id: "site-a",
    kind: "pageviews",
    payload: {},
    epsilon_used: 1,
    sampling_rate: 1,
    client_timestamp: new Date().toISOString(),
    nonce: "n1",
  };
}

describe("collector token refresh", () => {
  it("refreshes once on 401 and retries", async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({ ok: true, status: 202 });
    // @ts-ignore
    global.fetch = fetchMock;

    const refresh = jest.fn().mockResolvedValue("token-2");
    const collector = new EventCollector(
      config,
      { debug: () => undefined, warn: () => undefined, error: () => undefined, enable: () => undefined },
      () => undefined,
      () => undefined,
      () => "token-1",
      refresh
    );

    collector.enqueue(makeEvent());
    await collector.flush("test");

    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
