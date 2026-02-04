#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_upload_token(api_base: str, payload: dict[str, object]) -> dict[str, object]:
    url = f"{api_base.rstrip('/')}/api/upload-token"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as response:  # nosec - internal utility for local/dev use
        return json.loads(response.read().decode("utf-8"))


def build_snippet(
    sdk_import: str,
    site_id: str,
    shuffle_url: str,
    token: str,
    sampling_rate: float,
) -> str:
    return "\n".join(
        [
            "import { configure, sendPageview } from \"" + sdk_import + "\";",
            "",
            "configure({",
            f"  siteId: \"{site_id}\",",
            f"  shuffleUrl: \"{shuffle_url}\",",
            f"  uploadToken: \"{token}\",",
            f"  samplingRate: {sampling_rate},",
            "  epsilon: { presence: 1.0, pageview: 1.0, session: 1.0, conversion: 1.0 },",
            "});",
            "",
            "sendPageview(window.location.pathname);",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an upload token and print a starter SDK snippet.")
    parser.add_argument("--site-id", required=True, help="Site identifier (any unique string).")
    parser.add_argument("--origin", required=True, help="Allowed origin, e.g. https://validanalytics.io")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("VALID_API_BASE_URL", "http://localhost:8000"),
        help="API base URL.",
    )
    parser.add_argument(
        "--shuffle-url",
        default=None,
        help="Override shuffle URL (defaults to {api-base}/api/shuffle).",
    )
    parser.add_argument(
        "--sampling-rate", type=float, default=1.0, help="Sampling rate to encode in the token."
    )
    parser.add_argument(
        "--epsilon-budget", type=float, default=1.0, help="Epsilon budget encoded in the token."
    )
    parser.add_argument(
        "--ttl-seconds", type=int, default=None, help="Optional TTL override for the token."
    )
    parser.add_argument(
        "--sdk-import",
        default="/sdk/index.js",
        help="Import path for the SDK bundle (self-hosted or bundled).",
    )

    args = parser.parse_args()
    payload: dict[str, object] = {
        "site_id": args.site_id,
        "allowed_origin": args.origin,
        "epsilon_budget": args.epsilon_budget,
        "sampling_rate": args.sampling_rate,
    }
    if args.ttl_seconds:
        payload["ttl_seconds"] = args.ttl_seconds

    try:
        response = request_upload_token(args.api_base, payload)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        print(f"Upload token request failed: {detail}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Upload token request failed: {exc}", file=sys.stderr)
        return 1

    token = str(response.get("token", ""))
    expires_at = response.get("expires_at", "unknown")
    shuffle_url = args.shuffle_url or f"{args.api_base.rstrip('/')}/api/shuffle"

    print("Token:", token)
    print("Expires:", expires_at)
    print("")
    print("SDK snippet:")
    print(build_snippet(args.sdk_import, args.site_id, shuffle_url, token, args.sampling_rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
