# API Docs Snapshot

`openapi.yaml` in this folder is the production API schema snapshot for `https://api.validanalytics.io`.

## Refresh command

```bash
curl -sS https://api.validanalytics.io/openapi.json | jq . > docs/api/openapi.yaml
```

Notes:

- The file is stored in JSON-formatted OpenAPI (valid YAML) for deterministic updates.
- Treat `https://api.validanalytics.io/openapi.json` as the canonical source of truth for deployed routes.
