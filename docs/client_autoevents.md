# Client Autoevents

Valid autoevents are enabled by default when `init()` is used.

Tracked automatically:

- Pageview on first load
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
