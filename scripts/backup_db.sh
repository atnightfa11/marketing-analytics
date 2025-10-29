#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL=${DATABASE_URL:?DATABASE_URL required}
S3_BUCKET=${S3_BUCKET:?S3_BUCKET required}
RETENTION_DAYS=${RETENTION_DAYS:-30}

timestamp=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
backup_file="/tmp/marketing-analytics-${timestamp}.sql.gz"

echo "Creating database backup..."
pg_dump "${DATABASE_URL}" | gzip -9 > "${backup_file}"

echo "Uploading to S3..."
aws s3 cp "${backup_file}" "s3://${S3_BUCKET}/backups/${timestamp}.sql.gz"

echo "Pruning old backups..."
aws s3 ls "s3://${S3_BUCKET}/backups/" | while read -r line; do
  create_date=$(echo "$line" | awk '{print $1" "$2}')
  create_date_seconds=$(date -d"$create_date" +%s)
  cutoff_seconds=$(date -d"-${RETENTION_DAYS} days" +%s)
  if [[ ${create_date_seconds} -lt ${cutoff_seconds} ]]; then
    file_name=$(echo "$line" | awk '{print $4}')
    if [[ -n ${file_name} ]]; then
      aws s3 rm "s3://${S3_BUCKET}/backups/${file_name}"
    fi
  fi
done

rm -f "${backup_file}"
echo "Backup complete."
