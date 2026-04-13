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

  it("classifies utm paid and email traffic", () => {
    const paid = classifyReferrerBucket(
      "https://example.com/pricing?utm_source=google&utm_medium=cpc",
      ""
    );
    const email = classifyReferrerBucket(
      "https://example.com/blog?utm_source=newsletter&utm_medium=email",
      ""
    );
    expect(paid.bucket).toBe("paid");
    expect(email.bucket).toBe("email");
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
});

describe("query sanitization", () => {
  it("strips click-id parameters while preserving utm/source tags", () => {
    const sanitized = stripTrackingIdentifiersFromQuery(
      "?utm_source=google&utm_medium=cpc&gclid=abc123&fbclid=def456&source=newsletter"
    );
    expect(sanitized).toBe("?utm_source=google&utm_medium=cpc&source=newsletter");
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
