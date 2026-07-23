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

```bash
createdb restore_test
pg_restore --no-owner --dbname=restore_test backup_YYYY-MM-DD.dump
```

Validate:

1. `alembic_version` table exists.
2. `dp_windows`, `breakdown_rollups`, `reducer_watermarks`, `forecasts`, `site_plan`, `site_api_keys` row counts are sane for the restored environment.

## Incident basics

1. **Triage:** health endpoint, logs, job status.
2. **Contain:** disable failing scheduler job/env toggles.
3. **Recover:** restore DB snapshot if needed, rerun reducer/forecast.
4. **Communicate:** summarize impact + recovery window.
