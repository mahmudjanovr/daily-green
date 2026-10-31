import { describe, it } from 'node:test';
import assert from 'node:assert';
import { evaluateQualityGate } from '../src/services/qualityGate';
import { DEFAULT_POLICY } from '../src/data/defaultConfig';
import { CommandResult, RepoConfig, Task } from '../src/types/index';

const mockRepo: RepoConfig = {
  name: 'example-org/astro-portfolio',
  default_branch: 'main',
  enabled: true,
  max_diff_lines: 100,
  timeout_seconds: 300,
  allowed_paths: ['docs/**', 'README.md'],
  denied_paths: [],
  supported_task_types: ['doc_formatting', 'doc_typos'],
  allow_ai_tasks: false,
  test_commands: [],
  lint_commands: [],
  curated_tasks: [],
};

const validTask: Task = {
  id: 'fix-typo-readme',
  repo: 'example-org/astro-portfolio',
  title: 'Fix typo in README',
  description: 'Corrects typo',
  rationale: 'Documentation cleanliness',
  acceptance_criteria: ['Typo corrected'],
  risk_level: 'low',
  validation_strategy: 'typo_verification',
  source: 'deterministic',
  target_files: ['README.md'],
  created_at: new Date().toISOString(),
};

describe('Quality Gate Tests', () => {
  it('rejects changes if baseline pre-tests failed', async () => {
    const failedBaseline: CommandResult = {
      command: ['npm', 'run', 'build'],
      exit_code: 1,
      stdout: '',
      stderr: 'Build syntax error in existing repo',
      duration_seconds: 0.5,
      timed_out: false,
      passed: false,
    };

    const diff = '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-teh\n+the\n';
    const res = await evaluateQualityGate(
      validTask,
      diff,
      { 'README.md': 'the\n' },
      mockRepo,
      DEFAULT_POLICY,
      failedBaseline
    );

    assert.strictEqual(res.passed, false);
    assert.ok(res.reason.includes('Baseline tests failed prior to applying changes'));
  });

  it('rejects empty diffs (never fabricates empty commits)', async () => {
    const res = await evaluateQualityGate(
      validTask,
      '   \n',
      { 'README.md': 'content\n' },
      mockRepo,
      DEFAULT_POLICY
    );

    assert.strictEqual(res.passed, false);
    assert.ok(res.reason.includes('Diff is empty. Zero changes applied'));
  });

  it('rejects unallowlisted modified files', async () => {
    const badTask: Task = {
      ...validTask,
      target_files: ['src/App.tsx'],
    };
    const diff = '--- a/src/App.tsx\n+++ b/src/App.tsx\n@@ -1 +1 @@\n-old\n+new\n';

    const res = await evaluateQualityGate(
      badTask,
      diff,
      { 'src/App.tsx': 'new\n' },
      mockRepo,
      DEFAULT_POLICY
    );

    assert.strictEqual(res.passed, false);
    assert.ok(res.reason.includes('outside allowed paths'));
  });

  it('rejects diff containing sensitive credentials', async () => {
    const diffWithSecret = `--- a/README.md
+++ b/README.md
@@ -1 +1 @@
+AWS_KEY = AKIAIOSFODNN7EXAMPLE
`;

    const res = await evaluateQualityGate(
      validTask,
      diffWithSecret,
      { 'README.md': 'AWS_KEY = AKIAIOSFODNN7EXAMPLE\n' },
      mockRepo,
      DEFAULT_POLICY
    );

    assert.strictEqual(res.passed, false);
    assert.ok(res.reason.includes('Security checks failed'));
  });

  it('passes valid diff and seals patch with cryptographic SHA-256 hash', async () => {
    const cleanDiff = `--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
 Welcome
-teh portfolio
+the portfolio
`;

    const res = await evaluateQualityGate(
      validTask,
      cleanDiff,
      { 'README.md': 'Welcome\nthe portfolio\n' },
      mockRepo,
      DEFAULT_POLICY
    );

    assert.strictEqual(res.passed, true);
    assert.ok(res.patch_hash);
    assert.strictEqual(res.patch_hash?.length, 64);
    assert.ok(res.tree_sha);
  });
});
