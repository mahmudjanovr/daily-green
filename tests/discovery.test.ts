import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
  discoverNextTask,
  discoverDeterministicTypoTasks,
  discoverDeterministicFormattingTasks,
  discoverDeterministicLinkTasks,
} from '../src/services/discovery';
import { DEFAULT_POLICY } from '../src/data/defaultConfig';
import { RepoConfig, VirtualFile } from '../src/types/index';
import { StateManager } from '../src/services/stateManager';

const mockRepo: RepoConfig = {
  name: 'example-org/astro-portfolio',
  default_branch: 'main',
  enabled: true,
  max_diff_lines: 100,
  timeout_seconds: 300,
  allowed_paths: ['docs/**', 'README.md'],
  denied_paths: [],
  supported_task_types: ['doc_links', 'doc_formatting', 'doc_typos', 'curated_backlog', 'issue_task'],
  allow_ai_tasks: false,
  test_commands: [],
  lint_commands: [],
  curated_tasks: [],
};

describe('Rules-First Task Discovery Tests', () => {
  it('discovers deterministic typo tasks', () => {
    const stateMgr = new StateManager(3);
    const files: VirtualFile[] = [
      {
        path: 'docs/guide.md',
        content: '# Guide\n\nThis is teh documentation.\n',
      },
    ];

    const tasks = discoverDeterministicTypoTasks(files, mockRepo, DEFAULT_POLICY, stateMgr);
    assert.strictEqual(tasks.length, 1);
    assert.strictEqual(tasks[0].id, 'typo-teh-docs-guide.md');
    assert.strictEqual(tasks[0].source, 'deterministic');
  });

  it('discovers deterministic formatting tasks (trailing whitespace)', () => {
    const stateMgr = new StateManager(3);
    const files: VirtualFile[] = [
      {
        path: 'docs/guide.md',
        content: '# Guide    \nClean line\n',
      },
    ];

    const tasks = discoverDeterministicFormattingTasks(files, mockRepo, DEFAULT_POLICY, stateMgr);
    assert.strictEqual(tasks.length, 1);
    assert.strictEqual(tasks[0].id, 'format-docs-guide.md');
  });

  it('discovers deterministic broken internal relative links', () => {
    const stateMgr = new StateManager(3);
    const files: VirtualFile[] = [
      {
        path: 'docs/guide.md',
        content: '# Guide\n\nSee [Missing Doc](docs/missing-file.md) for details.\n',
      },
    ];

    const tasks = discoverDeterministicLinkTasks(files, mockRepo, DEFAULT_POLICY, stateMgr);
    assert.strictEqual(tasks.length, 1);
    assert.ok(tasks[0].id.includes('fix-broken-link'));
  });

  it('respects strict priority order: Issues > Backlog > Deterministic', () => {
    const stateMgr = new StateManager(3);
    const repoWithBacklog: RepoConfig = {
      ...mockRepo,
      curated_tasks: [
        {
          id: 'curated-readme-fix',
          title: 'Curated Readme Update',
          description: 'Improve documentation',
          rationale: 'Backlog priority',
          acceptance_criteria: ['Check docs'],
          risk_level: 'low',
          validation_strategy: 'verify',
          source: 'backlog',
          target_files: ['README.md'],
        },
      ],
    };

    const files: VirtualFile[] = [
      {
        path: 'README.md',
        content: '# Readme\n\nContains teh typo and trailing spaces.   \n',
      },
    ];

    // Case 1: Labeled issue present -> should win over backlog & deterministic
    const issueCandidate = discoverNextTask(files, repoWithBacklog, DEFAULT_POLICY, stateMgr, [
      {
        number: 99,
        title: 'High priority issue task',
        body: 'Please fix README.md',
      },
    ]);
    assert.strictEqual(issueCandidate?.source, 'issue');
    assert.strictEqual(issueCandidate?.id, 'issue-99');

    // Case 2: No issues -> curated backlog should win over deterministic typos
    const backlogCandidate = discoverNextTask(files, repoWithBacklog, DEFAULT_POLICY, stateMgr, []);
    assert.strictEqual(backlogCandidate?.source, 'backlog');
    assert.strictEqual(backlogCandidate?.id, 'curated-readme-fix');

    // Case 3: No issues and no backlog -> deterministic checks take effect
    const repoWithoutBacklog: RepoConfig = { ...mockRepo, curated_tasks: [] };
    const deterministicCandidate = discoverNextTask(files, repoWithoutBacklog, DEFAULT_POLICY, stateMgr, []);
    assert.strictEqual(deterministicCandidate?.source, 'deterministic');
  });

  it('returns null (NO_TASK) cleanly when no eligible maintenance task exists', () => {
    const stateMgr = new StateManager(3);
    const cleanFiles: VirtualFile[] = [
      {
        path: 'README.md',
        content: '# Readme\n\nClean markdown with no typos, no trailing spaces, and single newline.\n',
      },
    ];

    const task = discoverNextTask(cleanFiles, mockRepo, DEFAULT_POLICY, stateMgr, []);
    assert.strictEqual(task, null);
  });
});
