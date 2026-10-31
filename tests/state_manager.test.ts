import { describe, it } from 'node:test';
import assert from 'node:assert';
import { StateManager, CURRENT_STATE_SCHEMA_VERSION } from '../src/services/stateManager';

describe('StateManager Tests', () => {
  it('initializes with current schema version and safe defaults', () => {
    const mgr = new StateManager(3);
    const state = mgr.getState();
    assert.strictEqual(state.schema_version, CURRENT_STATE_SCHEMA_VERSION);
    assert.strictEqual(state.is_browser_simulated, true);
    assert.ok(typeof state.completed_tasks === 'object');
  });

  it('generates deterministic idempotency keys', () => {
    const mgr = new StateManager(3);
    const key = mgr.getIdempotencyKey('Example-Org/Astro-Portfolio', 'task-123', '2026-10-31');
    assert.strictEqual(key, '2026-10-31:example-org/astro-portfolio:task-123');
  });

  it('records task completion and prevents duplicate task execution', () => {
    const mgr = new StateManager(3);
    const repo = 'test-org/test-repo';
    const taskId = 'doc-fix-1';

    assert.strictEqual(mgr.isTaskAlreadyDone(repo, taskId, '2026-10-31'), false);
    mgr.recordTaskCompletion(repo, taskId, { pr: 12 }, '2026-10-31');
    assert.strictEqual(mgr.isTaskAlreadyDone(repo, taskId, '2026-10-31'), true);
  });

  it('trips circuit breaker after reaching failure threshold', () => {
    const mgr = new StateManager(3);
    const repo = 'failing-org/failing-repo';

    assert.strictEqual(mgr.isCircuitTripped(repo), false);
    assert.strictEqual(mgr.getConsecutiveFailures(repo), 0);

    mgr.recordFailure(repo, 'Failure 1');
    assert.strictEqual(mgr.getConsecutiveFailures(repo), 1);
    assert.strictEqual(mgr.isCircuitTripped(repo), false);

    mgr.recordFailure(repo, 'Failure 2');
    assert.strictEqual(mgr.getConsecutiveFailures(repo), 2);
    assert.strictEqual(mgr.isCircuitTripped(repo), false);

    mgr.recordFailure(repo, 'Failure 3');
    assert.strictEqual(mgr.getConsecutiveFailures(repo), 3);
    assert.strictEqual(mgr.isCircuitTripped(repo), true);

    // Resetting clears the breaker
    mgr.resetFailureCount(repo);
    assert.strictEqual(mgr.isCircuitTripped(repo), false);
    assert.strictEqual(mgr.getConsecutiveFailures(repo), 0);
  });

  it('acquires and releases execution leases preventing collisions', () => {
    const mgr = new StateManager(3);
    const repo = 'leased-org/leased-repo';
    const runA = 'run-aaa';
    const runB = 'run-bbb';

    // Run A acquires lease
    const acquiredA = mgr.acquireRunLease(repo, runA, 1800);
    assert.strictEqual(acquiredA, true);

    // Run B attempts to acquire active lease -> should be denied
    const acquiredB = mgr.acquireRunLease(repo, runB, 1800);
    assert.strictEqual(acquiredB, false);

    // Run A releases lease
    mgr.releaseRunLease(repo, runA);

    // Now Run B can acquire lease
    const acquiredB2 = mgr.acquireRunLease(repo, runB, 1800);
    assert.strictEqual(acquiredB2, true);
  });
});
