import { shouldEmitAutoPageview } from "../index";

describe("autoevents route suppression", () => {
  it("suppresses duplicate pageview emissions for repeated same-path route changes", () => {
    expect(shouldEmitAutoPageview("/home", "pushState")).toBe(true);
    expect(shouldEmitAutoPageview("/home", "pushState")).toBe(false);
    expect(shouldEmitAutoPageview("/home", "replaceState")).toBe(false);
    expect(shouldEmitAutoPageview("/pricing", "replaceState")).toBe(true);
  });
});
