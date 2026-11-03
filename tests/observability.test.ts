import { test, describe } from 'node:test';
import assert from 'node:assert';
import { logger } from '../src/server/logger';
import { metricsService } from '../src/server/metricsService';

describe('Phase 7: SRE Observability & Structured Logging', () => {
  test('logger redacts sensitive secrets from log messages and metadata objects', () => {
    logger.clearInMemoryLogs();

    const sensitiveToken = 'ghp_1234567890abcdef1234567890abcdef1234';
    const testCorrelationId = 'test-corr-12345';

    logger.info('TestModule', `Authentication attempt with ${sensitiveToken}`, testCorrelationId, {
      token: sensitiveToken,
      nested: { key: sensitiveToken },
    });

    const logs = logger.getRecentLogs(10, 'INFO', testCorrelationId);
    assert.strictEqual(logs.length, 1);

    const entry = logs[0];
    assert.strictEqual(entry.message.includes(sensitiveToken), false);
    assert.ok(entry.message.includes('REDACTED'));
    assert.strictEqual(entry.details?.token?.includes(sensitiveToken), false);
    assert.strictEqual(entry.details?.nested?.key?.includes(sensitiveToken), false);
    assert.strictEqual(entry.correlationId, testCorrelationId);
  });

  test('logger supports level filtering and bounded buffer size', () => {
    logger.clearInMemoryLogs();

    logger.info('ModA', 'Info message');
    logger.warn('ModB', 'Warn message');
    logger.error('ModC', 'Error message');
    logger.audit('ModD', 'Audit message');

    const errorLogs = logger.getRecentLogs(10, 'ERROR');
    assert.strictEqual(errorLogs.length, 1);
    assert.strictEqual(errorLogs[0].level, 'ERROR');

    const auditLogs = logger.getRecentLogs(10, 'AUDIT');
    assert.strictEqual(auditLogs.length, 1);
    assert.strictEqual(auditLogs[0].level, 'AUDIT');
  });

  test('metricsService calculates accurate latency percentiles and request counts', async () => {
    metricsService.recordRequest('GET', '/api/health', 200, 10);
    metricsService.recordRequest('GET', '/api/health', 200, 20);
    metricsService.recordRequest('GET', '/api/health', 200, 30);
    metricsService.recordRequest('GET', '/api/health', 200, 40);
    metricsService.recordRequest('POST', '/api/runs', 400, 50);

    const snapshot = await metricsService.getMetrics();

    assert.strictEqual(snapshot.http.total_requests >= 5, true);
    assert.strictEqual(snapshot.http.success_2xx >= 4, true);
    assert.strictEqual(snapshot.http.client_error_4xx >= 1, true);
    assert.strictEqual(typeof snapshot.http.avg_latency_ms, 'number');
    assert.strictEqual(typeof snapshot.http.p95_latency_ms, 'number');

    // System telemetry
    assert.strictEqual(typeof snapshot.system.uptime_seconds, 'number');
    assert.strictEqual(snapshot.system.memory_usage.heap_used_mb > 0, true);
    assert.strictEqual(typeof snapshot.storage.data_dir_bytes, 'number');

    // Safety invariants verified
    assert.strictEqual(snapshot.security_invariants.max_workers, 1);
    assert.strictEqual(typeof snapshot.security_invariants.dry_run_default, 'boolean');
  });
});
