# Client Token Bootstrap

Valid uses a site key bootstrap flow so websites do not embed short-lived upload tokens.
Site keys are publishable and must be origin-restricted; rotate on suspicion of leakage.

## Flow

1. Website sends `POST /api/sdk/bootstrap` with `site_key`.
2. API validates:
   - key hash
   - active flag
   - `Origin` against allowed pattern
   - bootstrap rate limits
3. API returns:
   - `upload_token`
   - `expires_at`
   - sdk config metadata
4. SDK refreshes token before expiry and retries once on `401`.

## Security model

- Upload tokens are short-lived and HMAC-signed.
- `/api/shuffle` verifies the token signature, expiry, origin, registered `jti`, revocation status, and replay nonce.
- Argon2 remains appropriate for dashboard passwords and long-lived site keys, but upload-token ingest avoids per-request Argon2 verification for throughput.

## API request

```http
POST /api/sdk/bootstrap
Origin: https://validanalytics.io
Content-Type: application/json

{"site_key":"vsk_xxxxx_xxxxx","site_id":"live-validanalytics-io"}
```

## API response

```json
{
  "upload_token": "....",
  "expires_at": "2026-03-18T00:00:00Z",
  "config": {
    "site_id": "live-validanalytics-io",
    "sampling_rate": 1,
    "epsilon_budget": 1,
    "shuffle_url": "/api/shuffle",
    "token_ttl_seconds": 900
  }
}
```

## Operator commands

Create key:

```bash
python server/scripts/create_site_key.py --site-id live-validanalytics-io --origin "https://validanalytics.io"
```

Wildcard origins require an explicit override flag:

```bash
python server/scripts/create_site_key.py --site-id live-validanalytics-io --origin "https://*.example.com" --allow-wildcard-origin
```

Rotate/deactivate:

```bash
python server/scripts/rotate_site_key.py --site-id live-validanalytics-io --origin "https://validanalytics.io"
python server/scripts/rotate_site_key.py --site-id live-validanalytics-io --key-id <old_key_id> --deactivate-only
```
