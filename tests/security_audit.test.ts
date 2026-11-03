import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import { createServer } from '../server';
import http from 'http';

describe('Phase 7: Production Security Audit & Hardening', () => {
  let server: http.Server;
  let serverPort: number;

  before(async () => {
    const app = await createServer();
    await new Promise<void>((resolve) => {
      server = app.listen(0, '127.0.0.1', () => {
        const address = server.address() as any;
        serverPort = address.port;
        resolve();
      });
    });
  });

  after(async () => {
    await new Promise<void>((resolve) => {
      server.close(() => resolve());
    });
  });

  test('server injects mandatory HTTP security headers on all responses', async () => {
    const res = await fetch(`http://127.0.0.1:${serverPort}/api/health`);
    assert.strictEqual(res.status, 200);

    const headers = res.headers;
    assert.strictEqual(headers.get('x-content-type-options'), 'nosniff');
    assert.strictEqual(headers.get('x-frame-options'), 'SAMEORIGIN');
    assert.strictEqual(headers.get('x-xss-protection'), '1; mode=block');
    assert.strictEqual(headers.get('referrer-policy'), 'strict-origin-when-cross-origin');
    assert.ok(headers.get('permissions-policy'));
  });

  test('server generates and returns X-Correlation-ID header on all requests', async () => {
    const res = await fetch(`http://127.0.0.1:${serverPort}/api/health`);
    const correlationId = res.headers.get('x-correlation-id');

    assert.ok(correlationId);
    assert.strictEqual(typeof correlationId, 'string');
    assert.strictEqual(correlationId.length > 0, true);
  });

  test('server propagates client-provided correlation ID cleanly', async () => {
    const customCorrelationId = 'client-uuid-987654321';
    const res = await fetch(`http://127.0.0.1:${serverPort}/api/health`, {
      headers: {
        'x-correlation-id': customCorrelationId,
      },
    });

    const receivedId = res.headers.get('x-correlation-id');
    assert.strictEqual(receivedId, customCorrelationId);
  });

  test('rate limiter throttles excessive POST traffic with 429 Too Many Requests', async () => {
    // Blast 130 requests to /api/ai/classify (rate limit threshold is 120 req/min)
    let rateLimitedEncountered = false;

    for (let i = 0; i < 130; i++) {
      const res = await fetch(`http://127.0.0.1:${serverPort}/api/ai/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Check docs', description: 'Test' }),
      });

      if (res.status === 429) {
        rateLimitedEncountered = true;
        const retryAfter = res.headers.get('retry-after');
        assert.ok(retryAfter);
        break;
      }
    }

    assert.strictEqual(rateLimitedEncountered, true, 'Expected rate limiter to return 429');
  });
});
