#!/usr/bin/env bash
# DailyGreen Production Disaster Recovery - Restore Script
set -euo pipefail

TARGET_HOST="${DAILYGREEN_HOST:-http://localhost:3000}"
BACKUP_ID="${1:-}"

if [[ -z "${BACKUP_ID}" ]]; then
  echo "Usage: $0 <backup-id>"
  echo "Example: $0 dg-backup-2026-11-03T12-00-00-000Z"
  exit 1
fi

echo "[DailyGreen SRE] Verifying checksum for backup ${BACKUP_ID}..."
VERIFY=$(curl -s -f "${TARGET_HOST}/api/backups/${BACKUP_ID}/verify")
echo "${VERIFY}"

echo "[DailyGreen SRE] Executing atomic restore with automatic safety rollback snapshot..."
RESTORE=$(curl -s -f -X POST "${TARGET_HOST}/api/backups/${BACKUP_ID}/restore")
echo "${RESTORE}"
echo "[DailyGreen SRE] Restore completed successfully."
