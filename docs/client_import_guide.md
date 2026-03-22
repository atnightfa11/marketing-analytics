# Client Historical Import Guide

Valid supports historical import for migration and immediate forecasting.

## JSON endpoint

`POST /api/import/historical`

Headers:

- `X-Upload-Token: <upload_token>`

Body:

```json
{
  "site_id": "live-validanalytics-io",
  "rows": [
    {"day": "2026-01-01", "metric": "pageviews", "value": 1200},
    {"day": "2026-01-01", "metric": "revenue", "value": 340.5}
  ]
}
```

## CSV-text endpoint

`POST /api/import/historical-csv`

Headers:

- `X-Upload-Token: <upload_token>`

Body:

```json
{
  "site_id": "live-validanalytics-io",
  "csv_text": "day,metric,value\n2026-01-01,pageviews,1200\n2026-01-01,revenue,340.5\n"
}
```

## After import

The API triggers reducer reprocessing across affected days and retrains forecast metrics.
