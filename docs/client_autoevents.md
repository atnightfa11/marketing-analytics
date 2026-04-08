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

No form field values, query strings, or other PII are sent in conversion payloads.

## Duplicate suppression

- A route transition emits at most one pageview per normalized path + route action pair.
- Auto conversions use a dedupe window (default 10 seconds, bounded to 5–30 seconds).
