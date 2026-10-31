/**
 * Configuration Validator & Fail-Closed Policy Enforcement for DailyGreen
 */

import { DailyGreenConfig, RepoConfig, SecurityPolicyConfig } from '../types';

export class ConfigurationValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigurationValidationError';
  }
}

export const VALID_TASK_TYPES = new Set([
  'doc_links',
  'doc_formatting',
  'doc_typos',
  'curated_backlog',
  'issue_task',
]);

const REPO_NAME_REGEX = /^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/;

/**
 * Validate an individual repository configuration according to strict security rules.
 */
export function validateRepoConfig(
  repo: RepoConfig,
  globalPolicy?: SecurityPolicyConfig
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  // 1. Repository name in 'owner/repo' format
  if (!repo.name || !REPO_NAME_REGEX.test(repo.name)) {
    errors.push(
      `Repository name '${repo.name}' must be in strict 'owner/repo' format.`
    );
  }

  // 2. Default branch must not be empty
  if (!repo.default_branch || repo.default_branch.trim() === '') {
    errors.push(`Repository '${repo.name}' must specify a valid default branch.`);
  }

  // 3. Allowed paths must not be empty and cannot contain path traversal
  if (!repo.allowed_paths || repo.allowed_paths.length === 0) {
    errors.push(
      `Repository '${repo.name}' must explicitly configure at least one allowed path.`
    );
  } else {
    for (const p of repo.allowed_paths) {
      if (!p || typeof p !== 'string') {
        errors.push(`Repository '${repo.name}' has empty or invalid path pattern.`);
        continue;
      }
      if (p.includes('..') || p.startsWith('/') || p.startsWith('\\')) {
        errors.push(
          `Unsafe path pattern '${p}' in repository '${repo.name}' allowed_paths: traversal is forbidden.`
        );
      }
    }
  }

  // 4. Supported task types
  if (repo.supported_task_types) {
    for (const t of repo.supported_task_types) {
      if (!VALID_TASK_TYPES.has(t)) {
        errors.push(
          `Repository '${repo.name}' specifies unsupported task type '${t}'. Valid types: ${Array.from(VALID_TASK_TYPES).join(', ')}`
        );
      }
    }
  }

  // 5. Diff line limits
  if (repo.max_diff_lines < 1 || repo.max_diff_lines > 500) {
    errors.push(
      `Repository '${repo.name}' max_diff_lines (${repo.max_diff_lines}) must be between 1 and 500 lines.`
    );
  }

  if (globalPolicy && repo.max_diff_lines > globalPolicy.max_diff_lines) {
    errors.push(
      `Repository '${repo.name}' max_diff_lines (${repo.max_diff_lines}) exceeds global security policy limit (${globalPolicy.max_diff_lines}).`
    );
  }

  // 6. Timeout
  if (repo.timeout_seconds < 10 || repo.timeout_seconds > 1800) {
    errors.push(
      `Repository '${repo.name}' timeout_seconds (${repo.timeout_seconds}) must be between 10 and 1800 seconds.`
    );
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

/**
 * Validate the global security policy configuration.
 */
export function validateSecurityPolicy(
  policy: SecurityPolicyConfig
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (policy.max_diff_lines < 1 || policy.max_diff_lines > 500) {
    errors.push(
      `Global policy max_diff_lines (${policy.max_diff_lines}) must be between 1 and 500.`
    );
  }

  if (policy.max_tasks_per_run < 1 || policy.max_tasks_per_run > 5) {
    errors.push(
      `Global policy max_tasks_per_run (${policy.max_tasks_per_run}) must be between 1 and 5.`
    );
  }

  if (!policy.denied_paths || policy.denied_paths.length === 0) {
    errors.push(`Global policy must define strict denied paths.`);
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

/**
 * Validate the entire DailyGreen root configuration.
 */
export function validateDailyGreenConfig(
  config: DailyGreenConfig
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  // Policy validation
  const policyRes = validateSecurityPolicy(config.policy);
  errors.push(...policyRes.errors);

  // Repositories validation and uniqueness check
  const seenNames = new Set<string>();
  for (const repo of config.repos) {
    const lower = repo.name.toLowerCase();
    if (seenNames.has(lower)) {
      errors.push(`Duplicate repository definition in configuration: '${repo.name}'`);
    }
    seenNames.add(lower);

    const repoRes = validateRepoConfig(repo, config.policy);
    errors.push(...repoRes.errors);
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

/**
 * Fail-Closed Pre-Execution Gate.
 * Evaluates whether execution is authorized to proceed or must fail closed.
 */
export function evaluateExecutionAuthorization(
  config: DailyGreenConfig,
  repoName: string,
  circuitTripped: boolean,
  isBackupRun: boolean = false
): { authorized: boolean; reason?: string } {
  // 1. Global kill-switch check
  if (!config.enabled) {
    return {
      authorized: false,
      reason: 'Execution rejected: DailyGreen global kill switch is ACTIVE (DAILYGREEN_ENABLED=false).',
    };
  }

  // 2. Repository authorization
  const repo = config.repos.find(
    (r) => r.name.toLowerCase() === repoName.toLowerCase()
  );
  if (!repo) {
    return {
      authorized: false,
      reason: `Execution rejected: Repository '${repoName}' is not in the explicit allowlist.`,
    };
  }

  if (!repo.enabled) {
    return {
      authorized: false,
      reason: `Execution rejected: Repository '${repoName}' is currently disabled in configuration.`,
    };
  }

  // 3. Circuit breaker check
  if (circuitTripped) {
    return {
      authorized: false,
      reason: `Execution rejected: Circuit breaker is TRIPPED for '${repoName}' due to repeated failures. Maintainer reset required.`,
    };
  }

  return { authorized: true };
}
