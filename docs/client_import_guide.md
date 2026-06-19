# Client Historical Import Guide

Valid supports Standard-plan historical import for migration and forecast context.

Imported data is aggregate-only and is reduced into Standard daily aggregate buckets. Valid does not import user-level, session-level, IP, or user-agent data.

The dashboard should describe this as "Import historical data" rather than naming a specific source. GA4, Plausible, Fathom, Simple Analytics, spreadsheets, and internal reports can all be sources as long as the file is reduced to `day`, `metric`, and `value`.

## JSON endpoint

`POST /api/import/historical`

Headers:

- Browser dashboard requests use the `HttpOnly` login cookie. Manual API calls can use `Authorization: Bearer <dashboard_token>`.

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

- Browser dashboard requests use the `HttpOnly` login cookie. Manual API calls can use `Authorization: Bearer <dashboard_token>`.

Body:

```json
{
  "site_id": "live-validanalytics-io",
  "csv_text": "day,metric,value\n2026-01-01,pageviews,1200\n2026-01-01,revenue,340.5\n"
}
```

## Preview endpoint

`POST /api/import/historical-csv/preview`

Use preview before importing. It parses the CSV, summarizes the date range and metrics, reports invalid or duplicate rows, and checks whether the upload overlaps existing Valid-collected data.

Preview does not write data, run the reducer, or retrain forecasts.

Response highlights:

- `valid`: true only when the file can be imported safely.
- `row_count`, `day_count`, `start_day`, `end_day`, `metrics`: upload summary.
- `errors`: invalid rows or duplicate `day + metric` rows.
- `live_overlaps`: rows that overlap Valid-collected live data. These should be removed before import.
- `replaceable_import_overlaps`: rows that match previous historical import rows. These are safe to replace and will not double-count.

## After import

The API creates an import batch record, triggers reducer reprocessing across affected days, and retrains forecast metrics. If there is not enough history to produce a fresh forecast after an import or rollback, stale forecast rows are cleared so the dashboard falls back to a building state.

## Import history

`GET /api/import/history?site_id=<site_id>`

Headers:

- Browser dashboard requests use the `HttpOnly` login cookie. Manual API calls can use `Authorization: Bearer <dashboard_token>`.

Returns the most recent import batches with date range, metrics, status, row count, creator, and whether rollback is currently available.

## Rollback

`POST /api/import/batches/<batch_id>/rollback?site_id=<site_id>`

Headers:

- Browser dashboard requests use the `HttpOnly` login cookie. Manual API calls can use `Authorization: Bearer <dashboard_token>`.

Rollback deletes the retained raw import rows for that batch, re-runs the reducer for the affected days, and refreshes forecasts. Rollback is available for completed or failed batches only while the batch's raw import rows are still retained. After raw processing rows are purged, the batch remains in history as an audit record but cannot be rolled back automatically.

## Safety behavior

- CSV rows must be unique by `day + metric`; duplicate rows are rejected instead of summed silently.
- Re-uploading the same `day + metric` replaces the prior imported aggregate row, so repeat uploads do not double-count.
- Imports are rejected when the same `day + metric` already has Valid-collected live data. Remove overlapping dates from the CSV before importing historical data; there is no public override for live overlap.
- Imported rows are aggregate-only and do not create dimension breakdown rows.
- Each new import is tagged with a batch ID for audit and rollback while retained processing rows are still available.

## Product expectations

- Show preview/overlap warnings before allowing import.
- Keep import history visible after rollback is no longer available so support can explain what happened.
- Do not present historical import as a raw event migration. Valid imports aggregate reporting rows only.
