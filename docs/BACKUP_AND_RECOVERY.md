# DailyGreen Disaster Recovery & Backup Runbook

## 1. Overview

DailyGreen stores all durable state (circuit breaker trips, execution logs, execution leases, active configurations) inside `.dailygreen-data/`. The Disaster Recovery architecture provides:

- Atomic filesystem snapshots.
- Cryptographic SHA-256 integrity checksum verification.
- Pre-restore automatic rollback snapshots.
- Bounded retention (keeps the 10 most recent backups by default).

---

## 2. Creating a Backup

### Via HTTP REST API
```bash
curl -X POST http://localhost:3000/api/backups \
  -H "Content-Type: application/json" \
  -d '{"description": "Pre-deployment system backup"}'
```

### Via Helper Script
```bash
./scripts/backup.sh "Pre-upgrade snapshot"
```

### Output Format
The backup file is saved to `.dailygreen-data/backups/dg-backup-<timestamp>.json`:
```json
{
  "metadata": {
    "id": "dg-backup-2026-11-03T12-00-00-000Z",
    "created_at": "2026-11-03T12:00:00.000Z",
    "description": "Pre-deployment system backup",
    "state_version": 2
  },
  "state": { ... },
  "config": { ... }
}
```

---

## 3. Listing and Verifying Backups

### List All Backups
```bash
curl -s http://localhost:3000/api/backups | jq .
```

### Verify SHA-256 Checksum
```bash
curl -s http://localhost:3000/api/backups/dg-backup-2026-11-03T12-00-00-000Z/verify | jq .
```

Expected response:
```json
{
  "valid": true,
  "sha256": "4b6c...e901"
}
```

---

## 4. Restoring from Backup

When a restore is requested:
1. DailyGreen first creates an automatic pre-restore safety snapshot so operations can be rolled back if necessary.
2. DailyGreen verifies the target backup archive's SHA-256 integrity hash.
3. DailyGreen atomically writes the restored state and configuration files to disk.

### Execute Restore
```bash
./scripts/restore.sh dg-backup-2026-11-03T12-00-00-000Z
```
Or via HTTP API:
```bash
curl -X POST http://localhost:3000/api/backups/dg-backup-2026-11-03T12-00-00-000Z/restore
```
