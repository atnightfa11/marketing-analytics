# Client Historical Import Guide

Valid supports Standard-plan historical import for migration and immediate forecasting.

Imported data is aggregate-only and is reduced into Standard daily aggregate buckets. Valid does not import user-level, session-level, IP, or user-agent data.

## JSON endpoint

`POST /api/import/historical`

Headers:

- `Authorization: Bearer <dashboard_token>`

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

- `Authorization: Bearer <dashboard_token>`

Body:

```json
{
  "site_id": "live-validanalytics-io",
  "csv_text": "day,metric,value\n2026-01-01,pageviews,1200\n2026-01-01,revenue,340.5\n"
}
```

## After import

The API triggers reducer reprocessing across affected days and retrains forecast metrics.

## Safety behavior

- CSV rows must be unique by `day + metric`; duplicate rows are rejected instead of summed silently.
- Re-uploading the same `day + metric` replaces the prior imported aggregate row, so repeat uploads do not double-count.
- Imports are rejected when the same `day + metric` already has Valid-collected live data. Remove overlapping dates from the CSV before importing historical data.
- Imported rows are aggregate-only and do not create dimension breakdown rows.
