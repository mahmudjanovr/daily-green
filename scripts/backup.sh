#!/usr/bin/env bash
# DailyGreen Production Disaster Recovery - Atomic Backup Script
set -euo pipefail

TARGET_HOST="${DAILYGREEN_HOST:-http://localhost:3000}"
DESCRIPTION="${1:-DailyGreen CLI Administrative Backup}"

echo "[DailyGreen SRE] Initiating atomic backup snapshot on ${TARGET_HOST}..."

RESPONSE=$(curl -s -f -X POST "${TARGET_HOST}/api/backups" \
  -H "Content-Type: application/json" \
  -d "{\"description\": \"${DESCRIPTION}\"}")

echo "[DailyGreen SRE] Backup created successfully:"
echo "${RESPONSE}"
