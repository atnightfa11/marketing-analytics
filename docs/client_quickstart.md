# Valid Client Quickstart

## 1) Create a site key

```bash
python server/scripts/create_site_key.py --site-id live-validanalytics-io --origin "https://validanalytics.io"
```

`site_key` is a publishable browser key. Treat it like a constrained identifier (origin-restricted + rotatable), not a server secret.

## 2) Install one lightweight script (plain HTML)

```html
<script
  src="https://app.validanalytics.io/validanalytics.global.js"
  data-valid-site-key="vsk_xxxxx_xxxxx"
  data-valid-api-base="https://api.validanalytics.io"
  data-valid-sample-rate="1"
  data-valid-autoconversions="true"
></script>
```

`data-valid-site-id` is optional. If omitted, the SDK resolves it from `/api/sdk/bootstrap`.

The SDK auto-bootstraps an upload token, tracks pageviews/session starts/daily presence, and posts to `/api/shuffle`.

Optional attribution controls:

- `data-valid-ignored-referrers` to override payment/referrer ignore hosts.
- `data-valid-attribution-carryover-minutes` to control carry-forward window on return-to-site checkout flows.

## 3) SPA install snippet

```html
<script
  src="https://app.validanalytics.io/validanalytics.global.js"
  data-valid-site-key="vsk_xxxxx_xxxxx"
  data-valid-api-base="https://api.validanalytics.io"
  data-valid-sample-rate="1"
  data-valid-autoconversions="true"
></script>
```

## 4) Verify first data

1. Open your website and navigate a few pages.
2. Confirm `POST https://api.validanalytics.io/api/shuffle` returns `202`.
3. For immediate install confirmation (no reducer wait), call:
   ```bash
   curl -s "https://api.validanalytics.io/api/sdk/verify-install?site_id=live-validanalytics-io&lookback_minutes=15" \
     -H "Authorization: Bearer <dashboard_token>"
   ```
4. Open `https://app.validanalytics.io/site/live-validanalytics-io` and verify metrics populate.
5. Optional aggregate API check:
   ```bash
   curl -s 'https://api.validanalytics.io/api/aggregate?site_id=live-validanalytics-io&metric=pageviews&window=standard'
   ```

## 5) Track ecommerce purchases (explicit)

Use explicit purchase events for revenue tracking:

```html
<script>
  window.ValidAnalytics?.sendPurchase({
    revenueAmount: 79.00,
    revenueCurrency: "USD",
    orderId: "order_1001",
  });
</script>
```

This keeps the base script lightweight while supporting provider-agnostic ecommerce analytics.
