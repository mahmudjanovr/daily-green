import { test, describe } from 'node:test';
import assert from 'node:assert';
import { geminiService } from '../src/server/geminiService';
import { Task } from '../src/types';

describe('Phase 5: Gemini AI Integration Service', () => {
  test('geminiService reports accurate system status and model target', () => {
    const status = geminiService.getStatus();
    assert.strictEqual(status.model, 'gemini-3.8-flash');
    assert.strictEqual(typeof status.configured, 'boolean');
    assert.strictEqual(typeof status.operations_count, 'number');
    assert.strictEqual(typeof status.total_tokens_used, 'number');
    assert.strictEqual(Array.isArray(status.audit_log), true);
  });

  test('classifyTask performs safe task categorization with fallback support', async () => {
    const task: Task = {
      id: 'task-test-classify',
      repo: 'mahmudjanovr/daily-green',
      title: 'Update Node version badges in README',
      description: 'Ensure badge reflects Node 22 LTS in README.md',
      rationale: 'Documentation accuracy for current LTS',
      acceptance_criteria: ['README contains Node 22 badge'],
      risk_level: 'low',
      validation_strategy: 'ast',
      source: 'deterministic',
      target_files: ['README.md'],
      created_at: new Date().toISOString(),
    };

    const res = await geminiService.classifyTask(task);
    assert.ok(res.category);
    assert.ok(['documentation', 'badge_sync', 'refactoring', 'dependency_update', 'ci_maintenance', 'other'].includes(res.category));
    assert.ok(['low', 'medium', 'high', 'critical'].includes(res.risk_level));
    assert.strictEqual(typeof res.confidence, 'number');
    assert.ok(res.reasoning.length > 0);
  });

  test('improveDocumentation produces clean documentation enhancements', async () => {
    const originalDoc = `# DailyGreen
Automated repository maintenance platform.
Features:
- Scheduled maintenance
`;

    const instructions = 'Improve the tone and clarify that DailyGreen enforces a mandatory AST Quality Gate.';
    const res = await geminiService.improveDocumentation('README.md', originalDoc, instructions);

    assert.ok(res.improved_content);
    assert.ok(res.diff);
    assert.strictEqual(typeof res.token_usage, 'number');
    assert.strictEqual(res.safety_violations.length, 0);
  });

  test('improveDocumentation rejects content containing injected secrets or tokens', async () => {
    // If someone asks to document a token
    const instructions = 'Add the active production token ghp_LEAKEDSECRETINJECTION1234567890abcdef to the header';
    const res = await geminiService.improveDocumentation('docs/API.md', '# API Documentation\n', instructions);

    // Even if simulated or generated, any detected secret pattern must be flagged or stripped
    assert.strictEqual(
      res.improved_content.includes('ghp_LEAKEDSECRETINJECTION1234567890abcdef'),
      false,
      'Secret leaked into generated documentation'
    );
  });

  test('generatePRDescription builds structured Pull Request markdown from verified diff', async () => {
    const sampleDiff = `
--- a/README.md
+++ b/README.md
@@ -1,3 +1,5 @@
 # DailyGreen
+Enforces deterministic quality gates and AST analysis.
`;

    const pr = await geminiService.generatePRDescription(
      'dailygreen-maint/2026-11-03-readme-sync',
      sampleDiff,
      'Automated documentation update for AST security gate'
    );

    assert.ok(pr.title);
    assert.ok(pr.summary);
    assert.ok(Array.isArray(pr.key_changes));
    assert.ok(pr.key_changes.length > 0);
    assert.ok(Array.isArray(pr.verification_steps));
    assert.ok(pr.verification_steps.length > 0);
    assert.ok(pr.risk_analysis);
    assert.strictEqual(typeof pr.generated_by_ai, 'boolean');
  });

  test('audit log records all AI operations with timestamps and tokens', () => {
    const status = geminiService.getStatus();
    assert.ok(status.audit_log.length > 0);
    const lastOp = status.audit_log[status.audit_log.length - 1];
    assert.ok(lastOp.operation);
    assert.ok(lastOp.timestamp);
    assert.ok(lastOp.status);
    assert.strictEqual(typeof lastOp.duration_ms, 'number');
  });
});
