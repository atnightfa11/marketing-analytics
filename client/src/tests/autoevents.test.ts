import {
  classifyReferrerBucket,
  isPrivacySignalEnabled,
  normalizeAutoConversionType,
  stripTrackingIdentifiersFromQuery,
  shouldEmitAutoConversion,
  shouldEmitAutoPageview,
} from "../index";

describe("autoevents route suppression", () => {
  it("suppresses duplicate pageview emissions for repeated same-path route changes", () => {
    expect(shouldEmitAutoPageview("/home", "pushState")).toBe(true);
    expect(shouldEmitAutoPageview("/home", "pushState")).toBe(false);
    expect(shouldEmitAutoPageview("/home", "replaceState")).toBe(false);
    expect(shouldEmitAutoPageview("/pricing", "replaceState")).toBe(true);
  });
});

describe("autoconversions helpers", () => {
  it("normalizes conversion types safely", () => {
    expect(normalizeAutoConversionType(" Form Submit ")).toBe("form_submit");
    expect(normalizeAutoConversionType("mailto:Lead")).toBe("mailto_lead");
  });

  it("dedupes repeated conversion keys inside dedupe window", async () => {
    const key = "form_submit:home";
    expect(shouldEmitAutoConversion(key, 10_000)).toBe(true);
    expect(shouldEmitAutoConversion(key, 10_000)).toBe(false);
  });
});

describe("source classification", () => {
  it("classifies direct traffic without referrer", () => {
    const result = classifyReferrerBucket("https://example.com/blog", "");
    expect(result.bucket).toBe("direct");
    expect(result.source).toBe("Direct");
  });

  it("classifies search and social referrers", () => {
    const organic = classifyReferrerBucket(
      "https://example.com/blog",
      "https://www.google.com/search?q=valid"
    );
    const social = classifyReferrerBucket(
      "https://example.com/blog",
      "https://x.com/someone/status/123"
    );
    expect(organic.bucket).toBe("organic");
    expect(social.bucket).toBe("social");
  });

  it("treats same-site subdomain referrals as direct", () => {
    const result = classifyReferrerBucket(
      "https://app.neurotypicaltranslator.com/translate",
      "https://neurotypicaltranslator.com/"
    );
    expect(result.bucket).toBe("direct");
    expect(result.source).toBe("Direct");
  });

  it("classifies utm paid and email traffic", () => {
    const paid = classifyReferrerBucket(
      "https://example.com/pricing?utm_source=google&utm_medium=cpc&utm_campaign=summer",
      ""
    );
    const email = classifyReferrerBucket(
      "https://example.com/blog?utm_source=newsletter&utm_medium=email",
      ""
    );
    expect(paid.bucket).toBe("paid");
    expect(paid.source).toBe("google");
    expect(paid.utmSource).toBe("google");
    expect(paid.medium).toBe("cpc");
    expect(paid.campaign).toBe("summer");
    expect(email.bucket).toBe("email");
  });

  it("classifies ad click IDs without storing the click ID value", () => {
    const result = classifyReferrerBucket(
      "https://example.com/pricing?utm_source=google&utm_campaign=brand&gclid=abc123",
      ""
    );
    expect(result.bucket).toBe("paid");
    expect(result.source).toBe("google");
    expect(result.paidClickId).toBe("gclid");
    expect(JSON.stringify(result)).not.toContain("abc123");
  });

  it("classifies known ad source labels as paid", () => {
    const result = classifyReferrerBucket(
      "https://example.com/pricing?utm_source=googleads&utm_campaign=brand",
      ""
    );
    expect(result.bucket).toBe("paid");
    expect(result.source).toBe("googleads");
  });

  it("does not treat organic social click IDs as paid traffic", () => {
    const result = classifyReferrerBucket(
      "https://example.com/blog?utm_source=facebook&fbclid=abc123",
      ""
    );
    expect(result.bucket).toBe("social");
    expect(result.source).toBe("facebook");
  });

  it("classifies AI assistant sources separately", () => {
    const referrer = classifyReferrerBucket(
      "https://example.com/blog",
      "https://www.perplexity.ai/search/example"
    );
    const tagged = classifyReferrerBucket(
      "https://example.com/blog?utm_source=chatgpt",
      ""
    );
    expect(referrer.bucket).toBe("ai");
    expect(referrer.source).toBe("perplexity.ai");
    expect(tagged.bucket).toBe("ai");
    expect(tagged.source).toBe("chatgpt");
  });

  it("classifies source params even without medium", () => {
    const organic = classifyReferrerBucket(
      "https://example.com/blog?source=google",
      ""
    );
    const social = classifyReferrerBucket(
      "https://example.com/blog?utm_source=facebook",
      ""
    );
    const referral = classifyReferrerBucket(
      "https://example.com/blog?ref=partner_program",
      ""
    );
    expect(organic.bucket).toBe("organic");
    expect(social.bucket).toBe("social");
    expect(referral.bucket).toBe("referral");
  });

  it("keeps prior attribution when returning from PayPal", () => {
    const result = classifyReferrerBucket(
      "https://example.com/checkout/success",
      "https://www.paypal.com/checkoutnow",
      {
        carryoverAttribution: {
          bucket: "organic",
          source: "google.com",
          capturedAtMs: 1_000,
        },
        nowMs: 2_000,
        carryoverWindowMs: 30 * 60 * 1000,
      }
    );
    expect(result.bucket).toBe("organic");
    expect(result.source).toBe("google.com");
  });

  it("keeps prior attribution when returning from Stripe Checkout", () => {
    const result = classifyReferrerBucket(
      "https://example.com/order/complete",
      "https://checkout.stripe.com/pay/cs_test_123",
      {
        carryoverAttribution: {
          bucket: "paid",
          source: "google",
          capturedAtMs: 10_000,
        },
        nowMs: 20_000,
        carryoverWindowMs: 30 * 60 * 1000,
      }
    );
    expect(result.bucket).toBe("paid");
    expect(result.source).toBe("google");
  });

  it("keeps prior attribution across same-site navigation", () => {
    const result = classifyReferrerBucket(
      "https://example.com/pricing",
      "https://example.com/blog",
      {
        carryoverAttribution: {
          bucket: "paid",
          source: "google",
          utmSource: "google",
          medium: "cpc",
          campaign: "brand",
          capturedAtMs: 10_000,
        },
        nowMs: 20_000,
        carryoverWindowMs: 30 * 60 * 1000,
      }
    );
    expect(result.bucket).toBe("paid");
    expect(result.source).toBe("google");
    expect(result.campaign).toBe("brand");
  });

  it("falls back to direct if carryover attribution is stale", () => {
    const result = classifyReferrerBucket(
      "https://example.com/order/complete",
      "https://www.paypal.com/checkoutnow",
      {
        carryoverAttribution: {
          bucket: "social",
          source: "reddit.com",
          capturedAtMs: 1_000,
        },
        nowMs: 3_700_000,
        carryoverWindowMs: 30 * 60 * 1000,
      }
    );
    expect(result.bucket).toBe("direct");
    expect(result.source).toBe("Direct");
  });
});

describe("query sanitization", () => {
  it("strips attribution and click-id parameters from published page URLs", () => {
    const sanitized = stripTrackingIdentifiersFromQuery(
      "?utm_source=google&utm_medium=cpc&utm_campaign=brand&gclid=abc123&fbclid=def456&source=newsletter&page=pricing"
    );
    expect(sanitized).toBe("?page=pricing");
  });
});

describe("privacy signals", () => {
  it("detects DNT", () => {
    const enabled = isPrivacySignalEnabled({ doNotTrack: "1" }, null);
    expect(enabled).toBe(true);
  });

  it("detects GPC", () => {
    const enabled = isPrivacySignalEnabled({ globalPrivacyControl: true }, null);
    expect(enabled).toBe(true);
  });

  it("is false when no privacy signal is set", () => {
    const enabled = isPrivacySignalEnabled({ doNotTrack: "0", globalPrivacyControl: false }, { doNotTrack: "0" });
    expect(enabled).toBe(false);
  });
});
