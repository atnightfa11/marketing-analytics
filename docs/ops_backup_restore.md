# Backup, Restore, and Incident Basics

## Backup requirement

After `raw_reports` purge, aggregate tables are the durable customer history. Losing `dp_windows` or `breakdown_rollups` means losing customer analytics history, even if privacy-sensitive raw processing rows are gone.

For launch, keep Postgres on Railway unless there is a separate reliability or compliance reason to move. The required work is:

1. Confirm Railway Postgres volume backups are enabled for production.
2. Enable Railway Postgres point-in-time recovery if available for the production database.
3. Confirm the backup/PITR retention windows and document them separately from raw-report primary retention.
4. Run a restore drill into a separate staging database before broad paid launch.
5. Keep manual logical backups available for incidents where a point-in-time restore is not enough or a local audit copy is needed.

Current Railway references:

- Railway volume backups can be scheduled daily, weekly, or monthly and restored from the service Backups tab.
- Railway Postgres point-in-time recovery restores into a new sibling Postgres service at a selected timestamp inside the archive window.

You do not need a second live production database solely for this requirement.

## Manual logical backup

Daily Postgres logical backup:

```bash
pg_dump "$DATABASE_URL" --format=custom --file=backup_$(date +%F).dump
```

Keep at least 14 daily backups and 8 weekly backups.

Backups may contain `raw_reports` rows that have already been purged from the primary database. Privacy and retention language should distinguish primary-table retention from backup retention until backup lifecycle controls are tightened.

## Restore drill

Use a **separate temporary PostgreSQL database**, not the production service. It can be a staging database on Railway once the outage ends; no second permanently running production database is required. For provider-level resilience, also keep an encrypted logical backup in storage independent of the production Railway project/provider, with a documented deletion schedule and access limited to operators.

Before starting any restored application, disable scheduled jobs and outbound side effects. Do not copy production Stripe/SMTP/Slack credentials into staging; leave billing disabled and production workers stopped. A restore must not charge customers, send alerts, or ingest real traffic.

```bash
createdb restore_test
pg_restore --no-owner --dbname=restore_test backup_YYYY-MM-DD.dump
```

Validate:

1. `alembic_version` table exists.
2. Compare `dp_windows`, `breakdown_rollups`, `segment_rollups`, `reducer_watermarks`, `forecasts`, `historical_import_batches`, `dashboard_notes`, `site_goals`, `dashboard_users`, access and billing records against counts captured at backup time. Include `site_provisioning` for this release.
3. Compare per-site/day/metric aggregate totals for sampled recent and old dates against backup-time totals. Verify chart reads and site authorization with staging-only credentials.
4. Record backup identifier, timestamp, restore duration, counts/totals checked, and exceptions. Confirm recovery-point and recovery-time expectations rather than assuming that the existence of a backup proves recoverability.
5. Delete the temporary restore and copies according to the backup policy. Treat backup files as sensitive: they include password hashes, credentials, and possibly already-purged processing material. Never commit them or attach them to tickets.

October 21 status: no production backup configuration or restore drill was verified during the outage. This remains a launch prerequisite, not a completed checkbox.

## Incident basics

1. **Triage:** health endpoint, logs, job status.
2. **Contain:** disable failing scheduler job/env toggles.
3. **Recover:** restore DB snapshot if needed, rerun reducer/forecast.
4. **Communicate:** summarize impact + recovery window.
