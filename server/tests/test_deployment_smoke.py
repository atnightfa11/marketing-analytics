import datetime as dt
import io
import json
import runpy
from pathlib import Path
from urllib.parse import urlsplit

import pytest


@pytest.mark.parametrize("missing_forecast,allow_missing", [(False, False), (True, False), (True, True)])
def test_smoke_is_read_only_and_requires_forecast_unless_explicitly_allowed(monkeypatch, missing_forecast, allow_missing):
    module = runpy.run_path(str(Path(__file__).parents[2] / "scripts/verify_deployment.py"))
    monkeypatch.setenv("BASE_URL", "https://example.test")
    monkeypatch.setenv("SITE_ID", "authorized-test")
    monkeypatch.setenv("DASHBOARD_SESSION_TOKEN", "test-session")
    monkeypatch.setenv("REQUIRE_FORECAST", "false" if allow_missing else "true")
    monkeypatch.setenv("EXPECTED_CODE_FINGERPRINT", "reviewed-code")
    replies = {
        "/health/liveness": {"status": "ok"},
        "/health/readiness": {"checks": {"database": True, "schema_current": True}, "details": {
            "dashboard_auth_enabled": True, "billing_enabled": True, "code_fingerprint": "reviewed-code", "schema_heads": ["current-head"]}},
        "/api/auth/me": {"username": "owner"},
        "/api/billing/status": {"has_subscription": True, "collection_active": True},
        "/api/site-health": {"active_site_keys": 1, "latest_reducer_status": "success", "latest_reduced_at": dt.datetime.now(dt.timezone.utc).isoformat()},
        "/api/aggregate": {"windows": [{"value": 10}]},
        "/api/forecast/pageviews": {"forecast": [{"yhat": 10}], "trained_at": "today"},
    }
    requests = []

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            path = urlsplit(request.full_url).path
            response = Response(json.dumps(replies[path]).encode())
            if path == "/api/forecast/pageviews" and missing_forecast:
                response.status = 204
            return response

    monkeypatch.setitem(module["main"].__globals__, "build_opener", lambda *args: Opener())
    if missing_forecast and not allow_missing:
        with pytest.raises(ValueError, match="No current forecast"):
            module["main"]()
    else:
        module["main"]()
    assert requests and all(request.get_method() == "GET" for request in requests)
    assert all("test-session" not in request.full_url for request in requests)


def test_smoke_refuses_unconfigured_auth_before_network(monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[2] / "scripts/verify_deployment.py"))
    monkeypatch.setenv("BASE_URL", "https://example.test")
    monkeypatch.delenv("DASHBOARD_SESSION_TOKEN", raising=False)
    with pytest.raises(ValueError, match="No checks were run"):
        module["main"]()
