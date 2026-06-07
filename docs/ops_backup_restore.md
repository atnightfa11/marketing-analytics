# Backup, Restore, and Incident Basics

## Backup procedure

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
