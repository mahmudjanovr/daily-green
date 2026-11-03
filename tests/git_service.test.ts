import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import {
  validateGitRepositoryTarget,
  validateBranchName,
  cloneRepository,
  createAndCheckoutBranch,
  inspectGitStatus,
  inspectGitDiff,
  commitChangesSafely,
  GitExecutionError,
} from '../src/server/gitService';
import { executeSubprocess } from '../src/server/worker';

describe('Phase 2: Real Git Infrastructure & Credential Security', () => {
  const testBaseDir = path.join(os.tmpdir(), `dg_git_test_${Date.now()}`);
  const originRepoDir = path.join(testBaseDir, 'origin.git');
  const cloneTargetDir = path.join(testBaseDir, 'cloned_workspace');

  before(async () => {
    // Create bare origin repository for testing real git clone and commit flows
    await fs.promises.mkdir(originRepoDir, { recursive: true });
    await executeSubprocess(['git', 'init', '--bare'], originRepoDir, 10);

    // Seed bare repo with an initial commit via a temp working dir
    const seedDir = path.join(testBaseDir, 'seed');
    await fs.promises.mkdir(seedDir, { recursive: true });
    await executeSubprocess(['git', 'init'], seedDir, 10);
    await fs.promises.writeFile(path.join(seedDir, 'README.md'), '# Initial Test Project\n', 'utf8');
    await executeSubprocess(['git', 'add', 'README.md'], seedDir, 10);
    await executeSubprocess(
      ['git', '-c', 'user.name=Test', '-c', 'user.email=test@test.local', 'commit', '-m', 'Initial commit'],
      seedDir,
      10
    );
    await executeSubprocess(['git', 'branch', '-M', 'main'], seedDir, 10);
    await executeSubprocess(['git', 'remote', 'add', 'origin', originRepoDir], seedDir, 10);
    await executeSubprocess(['git', 'push', 'origin', 'main'], seedDir, 10);
  });

  after(async () => {
    try {
      await fs.promises.rm(testBaseDir, { recursive: true, force: true });
    } catch {
      // Ignore cleanup error
    }
  });

  test('validateGitRepositoryTarget accepts valid HTTPS repository URLs', () => {
    assert.strictEqual(validateGitRepositoryTarget('https://github.com/mahmudjanovr/daily-green.git'), true);
    assert.strictEqual(validateGitRepositoryTarget('https://github.com/owner/sample-repo'), true);
  });

  test('validateGitRepositoryTarget accepts safe local test directories', () => {
    assert.strictEqual(validateGitRepositoryTarget('/tmp/dailygreen_workspaces/repo.git'), true);
  });

  test('validateGitRepositoryTarget rejects dangerous injection flags and shell characters', () => {
    assert.strictEqual(validateGitRepositoryTarget('--upload-pack=touch /tmp/pwn'), false);
    assert.strictEqual(validateGitRepositoryTarget('https://github.com/repo.git; rm -rf /'), false);
    assert.strictEqual(validateGitRepositoryTarget('-u `whoami`'), false);
    assert.strictEqual(validateGitRepositoryTarget(''), false);
  });

  test('validateBranchName validates allowed branch formats and rejects injection', () => {
    assert.strictEqual(validateBranchName('dailygreen/fix-doc-links-20261103'), true);
    assert.strictEqual(validateBranchName('main'), true);
    assert.strictEqual(validateBranchName('feature/ast-security-v2'), true);

    // Rejections
    assert.strictEqual(validateBranchName('--help'), false);
    assert.strictEqual(validateBranchName('branch;cat /etc/passwd'), false);
    assert.strictEqual(validateBranchName('../escape'), false);
  });

  test('cloneRepository successfully clones a real Git repository into an isolated directory', async () => {
    const res = await cloneRepository({
      repoUrl: originRepoDir,
      targetDir: cloneTargetDir,
      branch: 'main',
    });

    assert.strictEqual(res.passed, true);
    assert.strictEqual(fs.existsSync(path.join(cloneTargetDir, 'README.md')), true);
    assert.strictEqual(fs.existsSync(path.join(cloneTargetDir, '.git')), true);
  });

  test('createAndCheckoutBranch creates an isolated maintenance branch', async () => {
    const branchName = 'dailygreen/test-maintenance-branch';
    const res = await createAndCheckoutBranch(cloneTargetDir, branchName);
    assert.strictEqual(res.passed, true);
    assert.strictEqual(res.branch, branchName);

    const status = await inspectGitStatus(cloneTargetDir);
    assert.strictEqual(status.isClean, true);
  });

  test('inspectGitStatus and inspectGitDiff detect real modified files and lines', async () => {
    // Modify README.md in cloned workspace
    const readmePath = path.join(cloneTargetDir, 'README.md');
    await fs.promises.appendFile(readmePath, '\nAutonomous maintenance entry verified.\n', 'utf8');

    const status = await inspectGitStatus(cloneTargetDir);
    assert.strictEqual(status.isClean, false);
    assert.strictEqual(status.entries.some((e) => e.includes('README.md')), true);

    const diff = await inspectGitDiff(cloneTargetDir);
    assert.strictEqual(diff.files_changed.includes('README.md'), true);
    assert.strictEqual(diff.total_lines_added >= 1, true);
    assert.strictEqual(diff.raw_diff.includes('Autonomous maintenance entry verified.'), true);
  });

  test('commitChangesSafely stages and commits changes with sanitized author identity', async () => {
    const commitRes = await commitChangesSafely(
      cloneTargetDir,
      'chore(dailygreen): automated maintenance test commit',
      { name: 'DailyGreen Test Worker', email: 'worker@dailygreen.local' }
    );

    assert.strictEqual(commitRes.passed, true);
    assert.ok(commitRes.commitSha && commitRes.commitSha.length === 40);

    const statusAfter = await inspectGitStatus(cloneTargetDir);
    assert.strictEqual(statusAfter.isClean, true);
  });

  test('GitExecutionError redacts sensitive credentials from errors and stdout/stderr', () => {
    const err = new GitExecutionError(
      'Failed with token ghp_1234567890abcdef1234567890abcdef1234 and pass',
      'AUTH_ERROR',
      'ghp_1234567890abcdef1234567890abcdef1234'
    );

    assert.strictEqual(err.message.includes('ghp_1234567890abcdef1234567890abcdef1234'), false);
    assert.strictEqual(err.stdout?.includes('ghp_1234567890abcdef1234567890abcdef1234'), false);
    assert.strictEqual(err.message.includes('REDACTED_GITHUB_TOKEN'), true);
  });
});
