import { RepoConfig, RiskLevel, SecurityPolicyConfig, Task, VirtualFile } from '../types';
import { isPathAllowed } from './security';
import { StateManager } from './stateManager';

export const COMMON_DOC_TYPOS: Record<string, string> = {
  teh: 'the',
  recieve: 'receive',
  recieved: 'received',
  seperate: 'separate',
  occured: 'occurred',
  refering: 'referring',
  succesful: 'successful',
  accomodate: 'accommodate',
};

const MD_LINK_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g;

export function discoverIssueTasks(
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager,
  remoteIssues: Array<{ number: number; title: string; body: string; html_url?: string }> = []
): Task[] {
  if (!repoConfig.supported_task_types.includes('issue_task')) {
    return [];
  }

  const tasks: Task[] = [];
  for (const issue of remoteIssues) {
    const taskId = `issue-${issue.number}`;
    if (stateMgr.isTaskAlreadyDone(repoConfig.name, taskId)) {
      continue;
    }

    const targetFiles: string[] = [];
    const lines = (issue.body || '').split('\n');
    for (const line of lines) {
      const lineStr = line.trim().replace(/^[-*`\s]+|[`\s]+$/g, '');
      if (['.md', '.txt', '.rst'].some((ext) => lineStr.endsWith(ext))) {
        const { allowed } = isPathAllowed(lineStr, repoConfig, policy);
        if (allowed) {
          targetFiles.push(lineStr);
        }
      }
    }

    if (targetFiles.length === 0) {
      if (repoConfig.allowed_paths.some((p) => p.includes('README.md') || p === '*.md')) {
        targetFiles.push('README.md');
      } else {
        continue;
      }
    }

    tasks.push({
      id: taskId,
      repo: repoConfig.name,
      title: `Fix issue #${issue.number}: ${issue.title}`,
      description: issue.body ? issue.body.slice(0, 1000) : issue.title,
      rationale: `Addresses open GitHub issue #${issue.number} labeled 'dailygreen'`,
      acceptance_criteria: [
        `Resolve issue #${issue.number} requirements safely within allowed paths`,
      ],
      risk_level: 'low',
      validation_strategy: 'issue_verification',
      source: 'issue',
      target_files: targetFiles,
      created_at: new Date().toISOString(),
      metadata: { issue_number: issue.number, issue_url: issue.html_url },
    });
  }

  return tasks;
}

export function discoverBacklogTasks(
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager
): Task[] {
  if (!repoConfig.supported_task_types.includes('curated_backlog')) {
    return [];
  }

  const tasks: Task[] = [];
  for (const item of repoConfig.curated_tasks) {
    if (!item.id || stateMgr.isTaskAlreadyDone(repoConfig.name, item.id)) {
      continue;
    }

    const safeTargets: string[] = [];
    for (const f of item.target_files) {
      const { allowed } = isPathAllowed(f, repoConfig, policy);
      if (allowed) {
        safeTargets.push(f);
      }
    }

    if (safeTargets.length === 0) {
      continue;
    }

    tasks.push({
      id: item.id,
      repo: repoConfig.name,
      title: item.title,
      description: item.description,
      rationale: item.rationale,
      acceptance_criteria: item.acceptance_criteria,
      risk_level: item.risk_level,
      validation_strategy: item.validation_strategy,
      source: 'backlog',
      target_files: safeTargets,
      patch: item.patch,
      created_at: new Date().toISOString(),
      metadata: item,
    });
  }

  return tasks;
}

export function discoverDeterministicLinkTasks(
  files: VirtualFile[],
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager
): Task[] {
  if (!repoConfig.supported_task_types.includes('doc_links')) {
    return [];
  }

  const existingPaths = new Set(files.map((f) => f.path.replace(/\\/g, '/')));

  for (const file of files) {
    const relPath = file.path.replace(/\\/g, '/');
    const { allowed } = isPathAllowed(relPath, repoConfig, policy);
    if (!allowed || !relPath.endsWith('.md')) continue;

    const matches = Array.from(file.content.matchAll(MD_LINK_PATTERN));
    for (const match of matches) {
      const linkTarget = match[2]?.trim() || '';
      if (
        linkTarget.startsWith('http://') ||
        linkTarget.startsWith('https://') ||
        linkTarget.startsWith('mailto:') ||
        linkTarget.startsWith('#')
      ) {
        continue;
      }

      const targetClean = linkTarget.split('#')[0].split('?')[0];
      if (!targetClean) continue;

      // Check if target resolves in workspace
      let resolvedPath = targetClean;
      if (relPath.includes('/')) {
        const parent = relPath.substring(0, relPath.lastIndexOf('/'));
        resolvedPath = `${parent}/${targetClean}`.replace(/\/\.\//g, '/');
      }

      if (!existingPaths.has(targetClean) && !existingPaths.has(resolvedPath)) {
        const taskId = `fix-broken-link-${relPath.replace(/\//g, '-')}`;
        if (stateMgr.isTaskAlreadyDone(repoConfig.name, taskId)) {
          continue;
        }

        return [
          {
            id: taskId,
            repo: repoConfig.name,
            title: `Fix broken relative link in ${relPath}`,
            description: `Documentation file '${relPath}' contains broken relative link target '${linkTarget}'.`,
            rationale:
              'Ensures repository documentation navigation is functional and links resolve properly.',
            acceptance_criteria: [
              `Verify link target in '${relPath}' is corrected or replaced with code reference`,
            ],
            risk_level: 'low',
            validation_strategy: 'markdown_link_verification',
            source: 'deterministic',
            target_files: [relPath],
            created_at: new Date().toISOString(),
            metadata: { broken_target: linkTarget, source_file: relPath },
          },
        ];
      }
    }
  }

  return [];
}

export function discoverDeterministicFormattingTasks(
  files: VirtualFile[],
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager
): Task[] {
  if (!repoConfig.supported_task_types.includes('doc_formatting')) {
    return [];
  }

  for (const file of files) {
    const relPath = file.path.replace(/\\/g, '/');
    const { allowed } = isPathAllowed(relPath, repoConfig, policy);
    if (!allowed || !relPath.endsWith('.md')) continue;

    const taskId = `format-${relPath.replace(/\//g, '-')}`;
    if (stateMgr.isTaskAlreadyDone(repoConfig.name, taskId)) {
      continue;
    }

    let needsFix = false;
    const lines = file.content.split('\n');
    for (const line of lines) {
      if (line !== line.trimEnd()) {
        needsFix = true;
        break;
      }
    }

    if (file.content.length > 0 && !file.content.endsWith('\n')) {
      needsFix = true;
    }

    if (needsFix) {
      return [
        {
          id: taskId,
          repo: repoConfig.name,
          title: `Standardize documentation formatting in ${relPath}`,
          description: `Remove trailing whitespace and ensure trailing newline in '${relPath}'.`,
          rationale: 'Enforces clean, standard Markdown formatting across repository documentation.',
          acceptance_criteria: [
            `Lines in '${relPath}' have no trailing whitespace`,
            `'${relPath}' ends with a single newline character`,
          ],
          risk_level: 'low',
          validation_strategy: 'formatting_verification',
          source: 'deterministic',
          target_files: [relPath],
          created_at: new Date().toISOString(),
          metadata: { format_type: 'whitespace_and_eof' },
        },
      ];
    }
  }

  return [];
}

export function discoverDeterministicTypoTasks(
  files: VirtualFile[],
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager
): Task[] {
  if (!repoConfig.supported_task_types.includes('doc_typos')) {
    return [];
  }

  for (const file of files) {
    const relPath = file.path.replace(/\\/g, '/');
    const { allowed } = isPathAllowed(relPath, repoConfig, policy);
    if (!allowed || !relPath.endsWith('.md')) continue;

    for (const [typo, fix] of Object.entries(COMMON_DOC_TYPOS)) {
      const regex = new RegExp(`\\b${typo}\\b`, 'i');
      if (regex.test(file.content)) {
        const taskId = `typo-${typo}-${relPath.replace(/\//g, '-')}`;
        if (stateMgr.isTaskAlreadyDone(repoConfig.name, taskId)) {
          continue;
        }

        return [
          {
            id: taskId,
            repo: repoConfig.name,
            title: `Correct common typo '${typo}' -> '${fix}' in ${relPath}`,
            description: `Documentation file '${relPath}' contains reproducible typo '${typo}'.`,
            rationale: 'Maintains high-quality, professional documentation in the repository.',
            acceptance_criteria: [
              `Typo '${typo}' is corrected to '${fix}' in '${relPath}'`,
            ],
            risk_level: 'low',
            validation_strategy: 'typo_verification',
            source: 'deterministic',
            target_files: [relPath],
            created_at: new Date().toISOString(),
            metadata: { typo, replacement: fix },
          },
        ];
      }
    }
  }

  return [];
}

export function discoverNextTask(
  files: VirtualFile[],
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig,
  stateMgr: StateManager,
  remoteIssues: Array<{ number: number; title: string; body: string; html_url?: string }> = []
): Task | null {
  // 1. Issues labeled 'dailygreen'
  const issueTasks = discoverIssueTasks(repoConfig, policy, stateMgr, remoteIssues);
  if (issueTasks.length > 0) return issueTasks[0];

  // 2. Curated Backlog
  const backlogTasks = discoverBacklogTasks(repoConfig, policy, stateMgr);
  if (backlogTasks.length > 0) return backlogTasks[0];

  // 3. Deterministic checks
  // 3a. Links
  const linkTasks = discoverDeterministicLinkTasks(files, repoConfig, policy, stateMgr);
  if (linkTasks.length > 0) return linkTasks[0];

  // 3b. Formatting
  const formattingTasks = discoverDeterministicFormattingTasks(files, repoConfig, policy, stateMgr);
  if (formattingTasks.length > 0) return formattingTasks[0];

  // 3c. Typos
  const typoTasks = discoverDeterministicTypoTasks(files, repoConfig, policy, stateMgr);
  if (typoTasks.length > 0) return typoTasks[0];

  // 4. AI-assisted (when enabled)
  if (repoConfig.allow_ai_tasks) {
    const taskId = `ai-clarify-docs-${repoConfig.name.split('/')[1]}`;
    if (!stateMgr.isTaskAlreadyDone(repoConfig.name, taskId)) {
      return {
        id: taskId,
        repo: repoConfig.name,
        title: `Improve readability and clarify setup steps in docs`,
        description: `Refine headings and terminology in documentation for improved developer onboarding.`,
        rationale: 'Enhances documentation clarity and developer experience.',
        acceptance_criteria: ['Documentation reads clearly and accurately.'],
        risk_level: 'low',
        validation_strategy: 'ai_doc_review',
        source: 'ai',
        target_files: ['README.md'],
        created_at: new Date().toISOString(),
        metadata: { ai_generated: true },
      };
    }
  }

  return null;
}
