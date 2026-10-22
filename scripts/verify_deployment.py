"""Authenticated, read-only smoke checks. Never migrates, reduces, or bills."""
import datetime as dt
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward authentication to an unexpected host.


def main():
    base = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    site = os.environ.get("SITE_ID")
    token = os.environ.get("DASHBOARD_SESSION_TOKEN")
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("Use HTTPS for remote verification")
    if not site or not token:
        raise ValueError(
            "Set SITE_ID and DASHBOARD_SESSION_TOKEN for an authorized owner. No checks were run."
        )
    opener = build_opener(NoRedirect())

    def get(path, auth=False, allow_empty=False, **params):
        url = base + path + ("?" + urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {token}"} if auth else {}
        try:
            with opener.open(Request(url, headers=headers), timeout=30) as response:
                if response.status == 204 and allow_empty:
                    return None
                if response.status != 200:
                    raise ValueError(f"{path}: unexpected HTTP {response.status}")
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(f"{path}: HTTP {exc.code}") from None

    assert get("/health/liveness")["status"] == "ok", "Liveness failed"
    readiness = get("/health/readiness")
    assert all(readiness["checks"].values()), "Readiness failed"
    details = readiness["details"]
    assert details["dashboard_auth_enabled"], "Dashboard auth is disabled"
    assert details["billing_enabled"], "Commercial billing is disabled"
    expected = os.environ.get("EXPECTED_CODE_FINGERPRINT")
    assert details.get("code_fingerprint"), "Release identity missing"
    if expected:
        assert (
            details["code_fingerprint"] == expected
        ), "API is running a different release"
    print("API release:", details["code_fingerprint"])
    print("Schema:", ", ".join(details.get("schema_heads", [])))
    assert get("/api/auth/me", auth=True)["username"], "Sign-in failed"
    billing = get("/api/billing/status", auth=True, site_id=site)
    assert (
        billing["has_subscription"] and billing["collection_active"]
    ), "Use an active paid/coupon test account"
    health = get("/api/site-health", auth=True, site_id=site)
    assert health["active_site_keys"] > 0, "No active installation key"
    assert (
        health["latest_reducer_status"] == "success"
    ), "Latest reducer did not succeed"
    assert health["latest_reduced_at"], "No reduction time recorded"
    reduced = dt.datetime.fromisoformat(
        health["latest_reduced_at"].replace("Z", "+00:00")
    )
    reduced = (
        reduced.replace(tzinfo=dt.timezone.utc) if reduced.tzinfo is None else reduced
    )
    max_hours = float(os.environ.get("MAX_REDUCER_AGE_HOURS", "48"))
    assert dt.datetime.now(dt.timezone.utc) - reduced <= dt.timedelta(
        hours=max_hours
    ), "Reducer is stale"
    aggregate = get(
        "/api/aggregate", auth=True, site_id=site, metric="pageviews", window="standard"
    )
    assert aggregate["windows"], "No published pageview windows"
    forecast = get("/api/forecast/pageviews", auth=True, allow_empty=True, site_id=site)
    if forecast is None:
        if os.environ.get("REQUIRE_FORECAST", "true").lower() != "false":
            raise ValueError(
                "No current forecast. Use REQUIRE_FORECAST=false only for a known new/sparse site."
            )
        print("Forecast unavailable; explicitly allowed for this site.")
    else:
        assert (
            forecast["forecast"] and forecast["trained_at"]
        ), "Incomplete forecast response"
    print(
        "Read-only API checks passed. Separately verify worker fingerprint, real checkout, email, and backup restore."
    )


if __name__ == "__main__":
    try:
        main()
    except (
        AssertionError,
        ValueError,
        KeyError,
        TypeError,
        URLError,
        TimeoutError,
    ) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
