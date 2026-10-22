import axios, { type InternalAxiosRequestConfig } from "axios";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

const requests: InternalAxiosRequestConfig[] = [];
const previousAdapter = axios.defaults.adapter;
let api: typeof import("./api");

beforeAll(async () => {
  axios.defaults.adapter = async (config) => {
    requests.push(config);
    return { config, data: { message: "Accepted" }, status: 200, statusText: "OK", headers: {} };
  };
  api = await import("./api");
});
beforeEach(() => { requests.length = 0; });
afterAll(() => { axios.defaults.adapter = previousAdapter; });

describe("Account workflow request contracts", () => {
  it("uses credentialed requests without exposing a reusable bearer token", async () => {
    await api.requestPasswordReset("owner@example.test");
    expect(requests[0].withCredentials).toBe(true);
    expect(requests[0].headers.Authorization).toBeUndefined();
    expect(requests[0].url).toBe("/api/auth/password-reset/request");
  });

  it("submits reset secrets in the POST body, never in the URL", async () => {
    await api.confirmPasswordReset("one-time-secret", "new-password");
    expect(requests[0].method).toBe("post");
    expect(requests[0].url).not.toContain("one-time-secret");
    expect(JSON.parse(requests[0].data)).toEqual({ token: "one-time-secret", password: "new-password" });
  });

  it("preserves the setup request identity and explicit billing approval on retry", async () => {
    const payload = { request_id: "stable-id", site_name: "Fourth site", site_domain: "fourth.test", approved_monthly_increase_usd: 5 };
    await api.addWebsite(payload);
    await api.addWebsite(payload);
    expect(requests.map((request) => JSON.parse(request.data))).toEqual([payload, payload]);
    expect(requests.every((request) => request.withCredentials && request.url === "/api/sites")).toBe(true);
  });

  it("checks pending setup without a side effect", async () => {
    await api.pendingSiteSetup();
    expect(requests[0].method).toBe("get");
    expect(requests[0].url).toBe("/api/sites/provisioning");
  });
});
