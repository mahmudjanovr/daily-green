import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
  scanContentForSecrets,
  redactSecrets,
  countDiffLines,
  validatePathSafety,
  isPathAllowed,
  computePatchHash,
  runSecurityChecks,
} from '../src/services/security';
import { DEFAULT_POLICY } from '../src/data/defaultConfig';
import { RepoConfig } from '../src/types/index';

const mockRepo: RepoConfig = {
  name: 'example-org/astro-portfolio',
  default_branch: 'main',
  enabled: true,
  max_diff_lines: 100,
  timeout_seconds: 300,
  allowed_paths: ['docs/**', 'README.md'],
  denied_paths: ['package.json'],
  supported_task_types: ['doc_links', 'doc_formatting', 'doc_typos'],
  allow_ai_tasks: false,
  test_commands: [],
  lint_commands: [],
  curated_tasks: [],
};

describe('Security Service Tests', () => {
  it('detects sensitive secrets across all supported patterns', () => {
    assert.ok(scanContentForSecrets('AKIAIOSFODNN7EXAMPLE').includes('AWS Access Key'));
    assert.ok(
      scanContentForSecrets('ghp_123456789012345678901234567890123456').includes('GitHub Classic Token')
    );
    assert.ok(
      scanContentForSecrets(
        'github_pat_11AAAAAAA0123456789012345678901234567890123456789012345678901234567890123456789012'
      ).includes('GitHub Fine-Grained Token')
    );
    assert.ok(
      scanContentForSecrets('-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----').includes(
        'Private Key Block'
      )
    );
    assert.ok(
      scanContentForSecrets('api_key = "abcdef1234567890abcdef1234567890"').includes(
        'Generic High-Entropy Secret'
      )
    );
    assert.ok(
      scanContentForSecrets('https://user:mysecretpassword@github.com/repo').includes(
        'URL Embedded Credentials'
      )
    );
  });

  it('redacts secrets reliably without leaking tokens', () => {
    const raw = 'Connecting using ghp_123456789012345678901234567890123456 and AKIAIOSFODNN7EXAMPLE';
    const cleaned = redactSecrets(raw);
    assert.ok(!cleaned.includes('ghp_'));
    assert.ok(!cleaned.includes('AKIAIOSFODNN7EXAMPLE'));
    assert.ok(cleaned.includes('***REDACTED_GITHUB_TOKEN***'));
    assert.ok(cleaned.includes('***REDACTED_AWS_KEY***'));
  });

  it('validates path safety and strictly blocks traversals', () => {
    assert.strictEqual(validatePathSafety('docs/guide.md'), true);
    assert.strictEqual(validatePathSafety('README.md'), true);
    assert.strictEqual(validatePathSafety('../evil.sh'), false);
    assert.strictEqual(validatePathSafety('docs/../../etc/passwd'), false);
    assert.strictEqual(validatePathSafety('/absolute/path'), false);
  });

  it('enforces path allowlist and denylist according to policy', () => {
    // Allowed
    assert.strictEqual(isPathAllowed('README.md', mockRepo, DEFAULT_POLICY).allowed, true);
    assert.strictEqual(isPathAllowed('docs/guide.md', mockRepo, DEFAULT_POLICY).allowed, true);

    // Outside allowlist
    assert.strictEqual(isPathAllowed('src/App.tsx', mockRepo, DEFAULT_POLICY).allowed, false);

    // Denied path
    assert.strictEqual(isPathAllowed('package.json', mockRepo, DEFAULT_POLICY).allowed, false);

    // Disallowed extension
    assert.strictEqual(isPathAllowed('docs/script.sh', mockRepo, DEFAULT_POLICY).allowed, false);
    assert.strictEqual(isPathAllowed('docs/binary.exe', mockRepo, DEFAULT_POLICY).allowed, false);

    // Denied workflow
    assert.strictEqual(
      isPathAllowed('.github/workflows/ci.yml', mockRepo, DEFAULT_POLICY).allowed,
      false
    );
  });

  it('counts diff lines correctly', () => {
    const diff = `--- a/README.md
+++ b/README.md
@@ -1,3 +1,3 @@
 Welcome
-teh project
+the project
 Details`;
    assert.strictEqual(countDiffLines(diff), 2);
  });

  it('computes deterministic SHA-256 patch seal', async () => {
    const diff = '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n';
    const hash1 = await computePatchHash(diff);
    const hash2 = await computePatchHash(diff);
    assert.strictEqual(hash1, hash2);
    assert.strictEqual(hash1.length, 64);
  });
});
