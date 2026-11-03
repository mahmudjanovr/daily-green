import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { BackupService } from '../src/server/backupService';
import { serverPersistence } from '../src/server/persistence';

describe('Phase 7: Disaster Recovery & Atomic Backup Service', () => {
  const testDir = path.join(os.tmpdir(), `dg_backup_test_${Date.now()}`);
  let backupService: BackupService;

  before(async () => {
    await fs.promises.mkdir(testDir, { recursive: true });
    backupService = new BackupService(testDir);
  });

  after(async () => {
    try {
      await fs.promises.rm(testDir, { recursive: true, force: true });
    } catch {
      // Ignore
    }
  });

  test('createBackup creates an atomic snapshot sealed with SHA-256', async () => {
    const backup = await backupService.createBackup('Test unit backup snapshot');

    assert.ok(backup.id);
    assert.ok(backup.filename.endsWith('.json'));
    assert.strictEqual(backup.description, 'Test unit backup snapshot');
    assert.strictEqual(typeof backup.sha256_hash, 'string');
    assert.strictEqual(backup.sha256_hash.length, 64);
    assert.strictEqual(backup.verified, true);
    assert.strictEqual(backup.size_bytes > 0, true);

    const fullPath = path.join(testDir, backup.filename);
    assert.strictEqual(fs.existsSync(fullPath), true);
  });

  test('listBackups discovers and parses created backup snapshots', async () => {
    const list = await backupService.listBackups();
    assert.strictEqual(list.length >= 1, true);
    const item = list[0];
    assert.ok(item.id);
    assert.strictEqual(item.verified, true);
    assert.strictEqual(item.sha256_hash.length, 64);
  });

  test('verifyBackup confirms valid archive and detects corruption', async () => {
    const backup = await backupService.createBackup('Integrity check test');
    const verification = await backupService.verifyBackup(backup.id);

    assert.strictEqual(verification.valid, true);
    assert.strictEqual(verification.sha256, backup.sha256_hash);

    // Now corrupt the archive file deliberately
    const filePath = path.join(testDir, backup.filename);
    await fs.promises.writeFile(filePath, 'CORRUPT_JSON_DATA', 'utf8');

    const corruptVerification = await backupService.verifyBackup(backup.id);
    assert.strictEqual(corruptVerification.valid, false);
    assert.ok(corruptVerification.error);
  });

  test('restoreBackup restores state cleanly after creating safety snapshot', async () => {
    // 1. Create a known state
    const originalState = await serverPersistence.getState();
    const backup = await backupService.createBackup('Pre-mutation state');

    // 2. Mutate state
    await serverPersistence.saveState({
      ...originalState,
      consecutive_failures: { 'test/mutation-repo': 99 },
    });

    const mutatedState = await serverPersistence.getState();
    assert.strictEqual(mutatedState.consecutive_failures['test/mutation-repo'], 99);

    // 3. Restore from backup
    const res = await backupService.restoreBackup(backup.id);
    assert.strictEqual(res.success, true);
    assert.ok(res.pre_restore_backup_id);

    // 4. Verify state was restored
    const restoredState = await serverPersistence.getState();
    assert.strictEqual(restoredState.consecutive_failures['test/mutation-repo'], undefined);
  });

  test('pruneBackups respects maximum retention bound', async () => {
    // Create multiple backups
    for (let i = 0; i < 5; i++) {
      await backupService.createBackup(`Retention test ${i}`);
    }

    const beforePrune = await backupService.listBackups();
    assert.strictEqual(beforePrune.length >= 5, true);

    const deletedCount = await backupService.pruneBackups(3);
    assert.strictEqual(deletedCount >= 2, true);

    const afterPrune = await backupService.listBackups();
    assert.strictEqual(afterPrune.length, 3);
  });
});
