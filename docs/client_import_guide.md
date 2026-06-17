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

The API creates an import batch record, triggers reducer reprocessing across affected days, and retrains forecast metrics. If there is not enough history to produce a fresh forecast after an import or rollback, stale forecast rows are cleared so the dashboard falls back to a building state.

## Import history

`GET /api/import/history?site_id=<site_id>`

Headers:

- `Authorization: Bearer <dashboard_token>`

Returns the most recent import batches with date range, metrics, status, row count, creator, and whether rollback is currently available.

## Rollback

`POST /api/import/batches/<batch_id>/rollback?site_id=<site_id>`

Headers:

- `Authorization: Bearer <dashboard_token>`

Rollback deletes the retained raw import rows for that batch, re-runs the reducer for the affected days, and refreshes forecasts. Rollback is available for completed or failed batches only while the batch's raw import rows are still retained. After raw processing rows are purged, the batch remains in history as an audit record but cannot be rolled back automatically.

## Safety behavior

- CSV rows must be unique by `day + metric`; duplicate rows are rejected instead of summed silently.
- Re-uploading the same `day + metric` replaces the prior imported aggregate row, so repeat uploads do not double-count.
- Imports are rejected when the same `day + metric` already has Valid-collected live data. Remove overlapping dates from the CSV before importing historical data.
- Imported rows are aggregate-only and do not create dimension breakdown rows.
- Each new import is tagged with a batch ID for audit and rollback while retained processing rows are still available.
