import { test, describe } from 'node:test';
import assert from 'node:assert';
import { SchedulerService } from '../src/server/scheduler';

describe('Phase 3: Autonomous Engine & Scheduling Daemon', () => {
  const scheduler = new SchedulerService();

  test('getTimeInTimezone accurately computes local time in Asia/Tashkent (+05:00)', () => {
    // 2026-11-03 04:00:00 UTC -> 2026-11-03 09:00:00 in Asia/Tashkent (+5 hours)
    const fixedDate = new Date('2026-11-03T04:00:00.000Z');
    const result = scheduler.getTimeInTimezone(fixedDate, 'Asia/Tashkent');

    assert.strictEqual(result.hour, 9);
    assert.strictEqual(result.minute, 0);
    assert.strictEqual(result.timeString, '09:00');
  });

  test('getTimeInTimezone accurately computes UTC time', () => {
    const fixedDate = new Date('2026-11-03T17:35:00.000Z');
    const result = scheduler.getTimeInTimezone(fixedDate, 'UTC');

    assert.strictEqual(result.hour, 17);
    assert.strictEqual(result.minute, 35);
    assert.strictEqual(result.timeString, '17:35');
  });

  test('isBackupRunWindow correctly detects the 17:35 UTC backup trigger slot', () => {
    const backupSlotExact = new Date('2026-11-03T17:35:00.000Z');
    assert.strictEqual(scheduler.isBackupRunWindow(backupSlotExact), true);

    const backupSlotWithinWindow = new Date('2026-11-03T17:38:20.000Z');
    assert.strictEqual(scheduler.isBackupRunWindow(backupSlotWithinWindow), true);

    const outsideBackupSlot = new Date('2026-11-03T17:30:00.000Z');
    assert.strictEqual(scheduler.isBackupRunWindow(outsideBackupSlot), false);

    const otherHour = new Date('2026-11-03T09:35:00.000Z');
    assert.strictEqual(scheduler.isBackupRunWindow(otherHour), false);
  });

  test('acquireLease enforces max_workers=1 global concurrency limit', () => {
    const repoA = 'org/repo-a';
    const repoB = 'org/repo-b';

    // Release any previous test leases
    scheduler.releaseLease(repoA);
    scheduler.releaseLease(repoB);

    // Acquire lease for repoA
    const acquiredA = scheduler.acquireLease(repoA, 'run-1', 60);
    assert.strictEqual(acquiredA, true);

    // Attempt to acquire lease for repoB while repoA is executing -> MUST BE DENIED (max_workers=1)
    const acquiredB = scheduler.acquireLease(repoB, 'run-2', 60);
    assert.strictEqual(acquiredB, false, 'Lease must be denied because max_workers=1');

    // Release repoA
    scheduler.releaseLease(repoA, 'run-1');

    // Now repoB can acquire lease
    const acquiredBAfterRelease = scheduler.acquireLease(repoB, 'run-2', 60);
    assert.strictEqual(acquiredBAfterRelease, true);

    scheduler.releaseLease(repoB, 'run-2');
  });

  test('pruneExpiredLeases automatically frees stale leases after TTL expires', () => {
    const repoTest = 'org/repo-expire-test';
    // Acquire lease with negative TTL (-5 seconds, already expired)
    scheduler.acquireLease(repoTest, 'run-stale', -5);

    // Prune leases
    scheduler.pruneExpiredLeases();

    // Now a new lease can be acquired immediately
    const canAcquireNow = scheduler.acquireLease(repoTest, 'run-fresh', 60);
    assert.strictEqual(canAcquireNow, true);
    scheduler.releaseLease(repoTest, 'run-fresh');
  });

  test('computeNextRunIso generates a formatted next run timestamp', () => {
    const nextIso = scheduler.computeNextRunIso('09:00', 'Asia/Tashkent');
    assert.ok(typeof nextIso === 'string');
    assert.ok(nextIso.includes('09:00'));
    assert.ok(nextIso.includes('Asia/Tashkent'));
  });

  test('recordAudit stores audit logs and maintains bounded size', () => {
    scheduler.recordAudit('TICK', 'test-repo', 'Test audit item 1');
    scheduler.recordAudit('TRIGGERED', 'test-repo', 'Test audit item 2');

    const statusPromise = scheduler.getStatus();
    return statusPromise.then((status) => {
      assert.ok(status.audit_trail.length >= 2);
      assert.strictEqual(status.audit_trail[0].event, 'TRIGGERED');
      assert.strictEqual(status.audit_trail[0].repo, 'test-repo');
    });
  });

  test('startDaemon and stopDaemon control daemon lifecycle properly', () => {
    scheduler.stopDaemon();
    assert.strictEqual(scheduler.isDaemonRunning(), false);

    scheduler.startDaemon();
    assert.strictEqual(scheduler.isDaemonRunning(), true);

    scheduler.stopDaemon();
    assert.strictEqual(scheduler.isDaemonRunning(), false);
  });
});
