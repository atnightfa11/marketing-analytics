# Client Autoevents

Valid autoevents are enabled by default when `init()` is used.

Tracked automatically:

- Pageview on first load
- SPA route changes (`pushState`, `replaceState`, `popstate`, `hashchange`)
- Session start (30 minute inactivity window)
- Daily presence ping
- Optional conversion capture via `data-valid-conversion`

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

## Duplicate suppression

A route transition emits at most one pageview per normalized path + route action pair.
