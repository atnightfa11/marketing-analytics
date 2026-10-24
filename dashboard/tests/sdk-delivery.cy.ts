type Batch = { nonce: string; batch: Array<{ kind: string; nonce: string }> };
type SDK = {
  configure(config: object): Promise<void>;
  initAutoevents(): Promise<void>;
  sendConversion(payload: { conversionType: string }): void;
};

describe("Hosted SDK delivery", () => {
  let batches: Batch[];

  const start = (privacySignal = false) => {
    cy.viewport("iphone-x");
    cy.intercept("GET", "/sdk-delivery-test", {
      headers: { "content-type": "text/html" },
      body: '<!doctype html><title>Local SDK test</title><script src="/validanalytics.global.js"></script>',
    });
    cy.visit("/sdk-delivery-test", {
      onBeforeLoad(win) {
        Object.defineProperty(win.navigator, "doNotTrack", { value: "0", configurable: true });
        Object.defineProperty(win.navigator, "globalPrivacyControl", { value: privacySignal, configurable: true });
      },
    });
    cy.window().then(async (win) => {
      const sdk = (win as unknown as { ValidAnalytics: SDK }).ValidAnalytics;
      await sdk.configure({ siteId: "browser-test", uploadToken: "synthetic-token",
        shuffleUrl: `${win.location.origin}/sdk-test-ingest`, samplingRate: 1,
        epsilon: { presence: 1, pageview: 1, session: 1, conversion: 1 } });
      await sdk.initAutoevents();
    });
  };

  beforeEach(() => {
    batches = [];
    cy.intercept("POST", "/sdk-test-ingest", (req) => {
      batches.push(req.body);
      req.reply({ statusCode: 202 });
    }).as("ingest");
  });

  it("sends the initial mobile visit promptly and only counts persisted page restores", () => {
    start();
    cy.wait("@ingest", { requestTimeout: 2000 }).then(() => {
      expect(batches[0].batch.filter((event) => event.kind === "pageviews")).to.have.length(1);
    });
    cy.window().then((win) => {
      win.dispatchEvent(new win.PageTransitionEvent("pageshow", { persisted: false }));
      win.dispatchEvent(new win.PageTransitionEvent("pageshow", { persisted: true }));
    });
    cy.wait("@ingest", { requestTimeout: 2000 }).then(() => {
      expect(batches.flatMap((batch) => batch.batch).filter((event) => event.kind === "pageviews")).to.have.length(2);
    });
  });

  it("sends a queued conversion on pagehide", () => {
    start();
    cy.wait("@ingest");
    cy.window().then((win) => {
      (win as unknown as { ValidAnalytics: SDK }).ValidAnalytics.sendConversion({ conversionType: "form_submit" });
      win.dispatchEvent(new win.PageTransitionEvent("pagehide", { persisted: true }));
    });
    cy.wait("@ingest", { requestTimeout: 2000 }).then(() => {
      expect(batches[1].batch.filter((event) => event.kind === "conversions")).to.have.length(1);
    });
  });

  it("retries a failed browser request without changing event identities", () => {
    let first: Batch;
    cy.intercept({ method: "POST", url: "/sdk-test-ingest", times: 1 }, (req) => {
      first = req.body;
      req.reply({ statusCode: 503 });
    });
    start();
    cy.wait("@ingest", { requestTimeout: 5000 }).then(() => {
      expect(batches[0].nonce).not.to.equal(first.nonce);
      expect(batches[0].batch).to.deep.equal(first.batch);
    });
  });

  it("continues honoring Global Privacy Control", () => {
    start(true);
    cy.wait(1500).then(() => expect(batches).to.have.length(0));
  });
});
