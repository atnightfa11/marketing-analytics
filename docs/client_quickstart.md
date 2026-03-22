# Valid Client Quickstart

## 1) Create a site key

```bash
python server/scripts/create_site_key.py --site-id live-validanalytics-io --origin "https://validanalytics.io"
```

`site_key` is a publishable browser key. Treat it like a constrained identifier (origin-restricted + rotatable), not a server secret.

## 2) Install one lightweight script (plain HTML)

```html
<script
  src="https://cdn.validanalytics.io/validanalytics.global.js"
  data-valid-site-key="vsk_xxxxx_xxxxx"
  data-valid-api-base="https://api.validanalytics.io"
  data-valid-sample-rate="1"
></script>
```

`data-valid-site-id` is optional. If omitted, the SDK resolves it from `/api/sdk/bootstrap`.

The SDK auto-bootstraps an upload token, tracks pageviews/session starts/daily presence, and posts to `/api/shuffle`.

## 3) SPA install snippet

```html
<script src="https://cdn.validanalytics.io/validanalytics.global.js"></script>
<script>
  window.ValidAnalytics.init({
    siteId: "live-validanalytics-io",
    siteKey: "vsk_xxxxx_xxxxx",
    apiBase: "https://api.validanalytics.io",
    shuffleUrl: "https://api.validanalytics.io/api/shuffle",
    samplingRate: 1,
    epsilon: { presence: 0.5, pageview: 0.5, session: 0.5, conversion: 0.5 }
  });
</script>
```

## 4) Verify first data

1. Open your website and navigate a few pages.
2. Confirm `POST https://api.validanalytics.io/api/shuffle` returns `202`.
3. Open `https://app.validanalytics.io` and verify metrics populate.
