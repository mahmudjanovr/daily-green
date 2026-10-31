import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
  validateRepoConfig,
  validateSecurityPolicy,
  evaluateExecutionAuthorization,
} from '../src/validation/configValidator';
import { DEFAULT_CONFIG, DEFAULT_POLICY } from '../src/data/defaultConfig';
import { RepoConfig } from '../src/types/index';

describe('Configuration Validation Tests', () => {
  it('accepts valid repository configurations', () => {
    const validRepo: RepoConfig = {
      name: 'org/repo-valid',
      default_branch: 'main',
      enabled: true,
      max_diff_lines: 100,
      timeout_seconds: 300,
      allowed_paths: ['docs/**', 'README.md'],
      denied_paths: [],
      supported_task_types: ['doc_links', 'doc_formatting'],
      allow_ai_tasks: false,
      test_commands: [],
      lint_commands: [],
      curated_tasks: [],
    };

    const res = validateRepoConfig(validRepo, DEFAULT_POLICY);
    assert.strictEqual(res.valid, true);
    assert.strictEqual(res.errors.length, 0);
  });

  it('rejects malformed repository names', () => {
    const invalidNameRepo: RepoConfig = {
      name: 'invalid_name_no_slash',
      default_branch: 'main',
      enabled: true,
      max_diff_lines: 100,
      timeout_seconds: 300,
      allowed_paths: ['docs/**'],
      denied_paths: [],
      supported_task_types: ['doc_links'],
      allow_ai_tasks: false,
      test_commands: [],
      lint_commands: [],
      curated_tasks: [],
    };

    const res = validateRepoConfig(invalidNameRepo, DEFAULT_POLICY);
    assert.strictEqual(res.valid, false);
    assert.ok(res.errors.some((e) => e.includes("must be in strict 'owner/repo' format")));
  });

  it('rejects unsafe allowed_paths with path traversal', () => {
    const unsafeRepo: RepoConfig = {
      name: 'org/safe-repo',
      default_branch: 'main',
      enabled: true,
      max_diff_lines: 100,
      timeout_seconds: 300,
      allowed_paths: ['docs/**', '../sensitive/**'],
      denied_paths: [],
      supported_task_types: ['doc_links'],
      allow_ai_tasks: false,
      test_commands: [],
      lint_commands: [],
      curated_tasks: [],
    };

    const res = validateRepoConfig(unsafeRepo, DEFAULT_POLICY);
    assert.strictEqual(res.valid, false);
    assert.ok(res.errors.some((e) => e.includes('traversal is forbidden')));
  });

  it('rejects repo max_diff_lines exceeding global policy limit', () => {
    const exceedingRepo: RepoConfig = {
      name: 'org/big-diff-repo',
      default_branch: 'main',
      enabled: true,
      max_diff_lines: 300,
      timeout_seconds: 300,
      allowed_paths: ['docs/**'],
      denied_paths: [],
      supported_task_types: ['doc_links'],
      allow_ai_tasks: false,
      test_commands: [],
      lint_commands: [],
      curated_tasks: [],
    };

    const res = validateRepoConfig(exceedingRepo, DEFAULT_POLICY);
    assert.strictEqual(res.valid, false);
    assert.ok(res.errors.some((e) => e.includes('exceeds global security policy limit')));
  });

  it('fails closed when kill-switch is active', () => {
    const disabledConfig = { ...DEFAULT_CONFIG, enabled: false };
    const auth = evaluateExecutionAuthorization(
      disabledConfig,
      'example-org/astro-portfolio',
      false
    );
    assert.strictEqual(auth.authorized, false);
    assert.ok(auth.reason?.includes('kill switch is ACTIVE'));
  });

  it('fails closed when repository is not authorized in allowlist', () => {
    const auth = evaluateExecutionAuthorization(
      DEFAULT_CONFIG,
      'unauthorized-org/malicious-repo',
      false
    );
    assert.strictEqual(auth.authorized, false);
    assert.ok(auth.reason?.includes('not in the explicit allowlist'));
  });

  it('fails closed when circuit breaker has tripped', () => {
    const auth = evaluateExecutionAuthorization(
      DEFAULT_CONFIG,
      'example-org/astro-portfolio',
      true
    );
    assert.strictEqual(auth.authorized, false);
    assert.ok(auth.reason?.includes('Circuit breaker is TRIPPED'));
  });
});
