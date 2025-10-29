#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${BASE_URL:-http://localhost:8000}
echo "Checking liveness..."
curl -fsS "${BASE_URL}/health/liveness" >/dev/null
echo "Checking readiness..."
curl -fsS "${BASE_URL}/health/readiness" >/dev/null

echo "Running migrations..."
alembic upgrade head

echo "Validating reducers..."
python -m app.scheduler.nightly_reduce > /dev/null 2>&1 || true

echo "Checking forecast endpoint..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/forecast/pageviews?site_id=demo")
echo "Forecast status: ${STATUS}"

echo "Deployment verification complete."
