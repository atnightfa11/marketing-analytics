# Client Autoevents

Valid autoevents are enabled by default when `init()` is used.

Tracked automatically:

- Pageview on first load
- Pageview on a persisted back/forward-cache restore (not on ordinary tab focus or the initial `pageshow`)
- SPA route changes (`pushState`, `replaceState`, `popstate`, `hashchange`)
- Session start (30 minute inactivity window)
- Daily presence ping
- Optional conversion capture via:
  - explicit `data-valid-conversion`
  - form submits (`form_submit`)
  - `mailto:` links (`mailto_click`)
  - `tel:` links (`tel_click`)
  - outbound links (`outbound_click`)

## Path normalization

- Hash is stripped by default.
- Query string is excluded by default.
- Override:
  - `includeQueryInPath: true`
  - `stripHashInPath: false`

## Conversion capture

```html
<button data-valid-conversion="signup">Start trial</button>
<form data-valid-conversion="contact_request">...</form>
```

Script-tag controls:

- `data-valid-autoconversions="true|false"` (default: `true`)
- `data-valid-conversion-selector="..."` (optional override)
- `data-valid-ignored-referrers="paypal.com,checkout.stripe.com,shop.app"` (optional override)
- `data-valid-attribution-carryover-minutes="30"` (optional override)

No form field values, query strings, or other PII are sent in conversion payloads.

## Ecommerce purchase/revenue tracking

Autoconversions stay lightweight. Purchases/revenue are explicit events.

JavaScript API:

```js
window.ValidAnalytics?.sendPurchase({
  revenueAmount: 49.99,
  revenueCurrency: "USD",
  orderId: "ord_12345",
});
```

Or use conversion tags with optional revenue metadata:

```html
<button
  data-valid-conversion="purchase"
  data-valid-revenue="49.99"
  data-valid-currency="USD"
  data-valid-order-id="ord_12345"
>
  Complete purchase
</button>
```

`sendPurchase` records:
- one conversion event (`conversion_type=purchase`)
- one revenue event (`value=amount`, `currency`, `order_id`)

Revenue amounts are provider-agnostic and work for any ecommerce stack.

## Payment-referrer attribution carry-forward

By default, Valid ignores common payment-domain referrers (`paypal.com`, `checkout.stripe.com`, `shopify.com`, etc.) when classifying new session source on return-to-site pages.

If the visitor had a prior non-direct attribution within the carryover window, Valid preserves that original source instead of attributing the session to the payment processor domain.

## Duplicate suppression

- A route transition emits at most one pageview per normalized path + route action pair.
- Auto conversions use a dedupe window (default 10 seconds, bounded to 5–30 seconds).

## Delivery

- The initial visit is flushed immediately after setup. Subsequent events flush after about one second (up to 250ms jitter) or when the batch fills.
- Hidden-page/pagehide events flush queued events with credential-less `fetch(..., { keepalive: true })`, even if an earlier request is still pending. No `beforeunload` listener is required.
- Failed requests retry with bounded backoff and an in-memory queue (at most 500 events; retry events older than five minutes are discarded). Request nonces change on retry, while event nonces stay stable so the server can deduplicate already accepted events.
- Solo/Standard ingestion does not apply the optional Pro shuffle delay. DNT/GPC checks, origin checks, bot filtering, and event expiry remain enforced.
- Delivery is best effort, not guaranteed: browser shutdown, offline expiry, blockers, and failed token bootstrap can still prevent collection. No browser-persistent event queue or visitor identifier is added.
- `npm run build` in `client/` also refreshes the hosted bundle in `dashboard/public/`. Build the client before the dashboard so the deployed script includes SDK fixes. Existing installations using that hosted script URL do not need a new snippet.
