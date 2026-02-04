# Real Site Setup (Live vs Demo)

Site IDs are internal identifiers; they do not need to match the domain. Use a stable, unique string like:

- Demo: `local-validanalytics-io`
- Live: `live-validanalytics-io`

## Generate an upload token

Run inside the server container:

```bash
docker compose exec server python scripts/create_upload_token.py \
  --site-id live-validanalytics-io \
  --origin https://validanalytics.io
```

This prints a token and a starter SDK snippet.

## Host the SDK bundle

The SDK build lives at `client/dist/index.js`. Host it on your site (for example at `/sdk/index.js`), then use the snippet from the token script.

If you need to rebuild:

```bash
npm --prefix client run build
```

## Dashboard views

Demo dashboard (seeded data):

- `http://localhost:5173` (uses `VITE_SITE_ID=local-validanalytics-io`)

Live dashboard (real traffic):

- `http://localhost:5174` (uses `VITE_SITE_ID=live-validanalytics-io`)

## Notes

- Free + Standard are the launch tiers; Pro/LDP is deferred.
- The current SDK still applies LDP; we will disable LDP for Free/Standard in the next backend/SDK pass.
