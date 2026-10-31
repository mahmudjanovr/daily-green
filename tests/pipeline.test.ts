import { describe, it } from 'node:test';
import assert from 'node:assert';
import { executeMaintenancePipeline } from '../src/pipeline/pipelineEngine';
import { DEFAULT_CONFIG } from '../src/data/defaultConfig';
import { RepoConfig, VirtualFile } from '../src/types/index';
import { StateManager } from '../src/services/stateManager';

const testRepo: RepoConfig = {
  name: 'example-org/astro-portfolio',
  default_branch: 'main',
  enabled: true,
  max_diff_lines: 100,
  timeout_seconds: 300,
  allowed_paths: ['docs/**', 'README.md'],
  denied_paths: [],
  supported_task_types: ['doc_formatting', 'doc_typos'],
  allow_ai_tasks: false,
  baseline_command: ['npm', 'run', 'build'],
  test_commands: [['npm', 'run', 'build']],
  lint_commands: [['npm', 'run', 'lint']],
  curated_tasks: [],
};

describe('Pipeline Engine Execution Tests', () => {
  it('executes the 7-stage pipeline in dry-run simulation mode successfully', async () => {
    const stateMgr = new StateManager(3);
    const files: VirtualFile[] = [
      {
        path: 'README.md',
        content: '# Readme\n\nWelcome to teh project.\n',
      },
    ];

    const stagesPassed: number[] = [];
    const logs: string[] = [];

    const res = await executeMaintenancePipeline({
      config: DEFAULT_CONFIG,
      repo: testRepo,
      stateMgr,
      files,
      onStageChange: (stageNum, status) => {
        if (status === 'success') stagesPassed.push(stageNum);
      },
      onLog: (msg) => logs.push(msg),
    });

    assert.strictEqual(res.success, true);
    assert.strictEqual(res.report.status, 'dry_run_completed');
    assert.ok(res.task);
    assert.strictEqual(res.task?.source, 'deterministic');
    assert.ok(res.diff.includes('-Welcome to teh project.'));
    assert.ok(res.diff.includes('+Welcome to the project.'));
    assert.strictEqual(res.qualityGate?.passed, true);
    assert.ok(res.qualityGate?.patch_hash);

    // All 7 stages reached
    assert.ok(stagesPassed.includes(1));
    assert.ok(stagesPassed.includes(2));
    assert.ok(stagesPassed.includes(3));
    assert.ok(stagesPassed.includes(4));
    assert.ok(stagesPassed.includes(5));
    assert.ok(stagesPassed.includes(6));
    assert.ok(stagesPassed.includes(7));
  });

  it('fails closed when global kill switch is active', async () => {
    const stateMgr = new StateManager(3);
    const files: VirtualFile[] = [{ path: 'README.md', content: 'test' }];

    const res = await executeMaintenancePipeline({
      config: { ...DEFAULT_CONFIG, enabled: false },
      repo: testRepo,
      stateMgr,
      files,
      onStageChange: () => {},
      onLog: () => {},
    });

    assert.strictEqual(res.success, false);
    assert.strictEqual(res.report.status, 'failed');
    assert.ok(res.report.message.includes('kill switch is ACTIVE'));
  });

  it('deduplicates execution on high-availability backup run', async () => {
    const stateMgr = new StateManager(3);
    const today = new Date().toISOString().split('T')[0];

    // Record that primary run succeeded today
    stateMgr.recordTaskCompletion(testRepo.name, 'previous-task', {}, today);

    const files: VirtualFile[] = [{ path: 'README.md', content: 'test with teh typo' }];

    const res = await executeMaintenancePipeline({
      config: DEFAULT_CONFIG,
      repo: testRepo,
      stateMgr,
      files,
      isBackupRun: true,
      onStageChange: () => {},
      onLog: () => {},
    });

    assert.strictEqual(res.success, true);
    assert.strictEqual(res.report.status, 'skipped');
    assert.ok(res.report.message.includes('Primary run has already completed a maintenance task today'));
  });

  it('supports cancellation cleanly during execution', async () => {
    const stateMgr = new StateManager(3);
    const abortCtrl = new AbortController();
    abortCtrl.abort(); // Cancel upfront

    const files: VirtualFile[] = [{ path: 'README.md', content: 'test with teh typo' }];

    const res = await executeMaintenancePipeline({
      config: DEFAULT_CONFIG,
      repo: testRepo,
      stateMgr,
      files,
      abortSignal: abortCtrl.signal,
      onStageChange: () => {},
      onLog: () => {},
    });

    assert.strictEqual(res.success, false);
    assert.strictEqual(res.report.status, 'failed');
    assert.ok(res.report.message.includes('cancelled'));
  });
});
