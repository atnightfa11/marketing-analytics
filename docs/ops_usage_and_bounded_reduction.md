# Bounded reduction and accepted usage

Implemented scope: launch steps 1 and 2 (reducer safety/measurement and usage accounting). Pricing, entitlements, automatic charges, customer notices, and dashboard usage bars are not changed by this release.

## Migration and rollout

Apply Alembic revision `2026_09_24_usage_reducer` before deploying API and worker. It follows `2026_09_17_anomaly_details`, creates usage counters, short-lived ingest receipts and reducer diagnostics, adds the Stripe period-start column and a raw site/day index.

Use a connection reachable from the migration runner. Railway's `postgres.railway.internal` URL works inside Railway; a local `railway run` only injects variables and does not provide access to private DNS. Run migration from a Railway environment with the current migration file or use the public Postgres connection locally. Do not print database credentials.

The migration adds an ordinary index on raw_reports; schedule against retained table size and use a maintenance window if needed. No SDK reinstall is required: the current SDK already supplies event nonces, now retained by request validation.

## Reducer

- Discover work by keyset pagination, then process and commit one site/day at a time.
- PostgreSQL transaction advisory locks serialize reduction and purge for the same site/day.
- Replace only the day whose raw rows are available. Existing aggregate-only days in a larger backfill range remain untouched.
- Commit KPI windows, breakdowns, segments, success watermark and run diagnostics together. On failure roll back that day, preserve its previous outputs, record a failed attempt, and raise to existing worker alert handling. Previously completed days remain committed; rerunning is idempotent.
- Read at most `REDUCER_MAX_REPORTS_PER_SITE_DAY + 1` raw or LDP reports. Default cap is 250,000. Exceeding it fails visibly before publishing partial output. This bounds memory but is not fully streaming sessionization; exceptionally large site/days require further work or measured cap adjustment.
- Flush pending rollup inserts every `REDUCER_WRITE_BATCH_SIZE` rows (default 500). Segment aggregation itself still maintains per-day dictionaries; high cardinality remains a benchmark concern.
- Refuse live reconstruction of a previously purged day from partial raw history. Aggregate-only imports remain supported.
- Use a receipt cutoff captured before reading reports and require raw counts to match the successful watermark before purging. New arrivals prevent premature deletion.

`reducer_runs` records the latest attempt per site/day. `process_peak_rss_bytes` is the process-lifetime high-water mark supplied by the OS, not isolated memory allocated by that job. Duration, raw count and segment count enable cost investigation but do not yet establish per-site hosting costs.

## Usage accounting

Accepted pageviews are counted in the ingestion transaction, with raw/LDP reports and retry receipts. Concurrent increments use database upserts. Usage survives raw purge and is independent of reducer reruns and DP noise.

Only accepted pageviews count. Session/presence/conversion/revenue reports, rejected bot or blocked-IP requests, mismatched sites, late events, and historical-import payloads do not count. Imports continue through their dedicated import endpoint. Exact event retries are deduplicated using a site-scoped event nonce, including when re-batched under a new upload token/batch nonce. Legacy clients without an event nonce use their exact timestamp/kind/payload envelope; identical legacy envelopes are treated as retries.

The batch replay marker is now committed with events rather than before them, allowing a failed ingestion transaction to be retried. Receipts expire after the accepted retry window; token maintenance purges them. Ingestion also rejects old client timestamps against server wall time, so expired receipts cannot be used to replay old events through a backdated collect envelope.

Account grouping follows existing owner-based billing: all sites belonging to a DashboardSite owner share the account key. Sites without a dashboard owner receive isolated site keys. Historical counters retain the owner at acceptance and are not reassigned when site ownership changes.

When exactly one active Stripe period is known for an owner, counters use its exact start/end. Subscription webhooks now store starts and support item-level Stripe period fields. When dates are missing, expired, or conflicting across subscriptions, traffic is retained in explicitly `unassigned_calendar_month` counters. Do not bill or enforce limits from these provisional totals. Existing subscriptions need a fresh subscription event/sync before exact periods are available; this release does not infer missing dates or call Stripe on ingestion.

Counters begin at deployment. An initial partial period cannot be reconstructed from noisy dashboard totals or purged raw data. Delayed renewal webhooks can also produce provisional counts; these require reconciliation before automated enforcement. No usage-based charging or enforcement is enabled in this pass.

Owner-only `GET /api/billing/usage?site_id=...` returns recent per-site counters and account totals grouped by period/basis, with first-recorded timestamps and explicit partial-history wording. It does not expose account-wide usage to invited site members. Settings UI is the next pass.

## Before enforcement

Confirm exact periods are populated, observe one full usage cycle, handle provisional-period reconciliation, and measure real report/segment amplification. Then add customer-visible allowances, notices and approved upgrades. Keep billing based on accepted unnoised pageviews; never charge the SDK's internal session/presence reports as pageviews.
