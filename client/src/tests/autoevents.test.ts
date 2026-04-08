import { normalizeAutoConversionType, shouldEmitAutoConversion, shouldEmitAutoPageview } from "../index";

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
