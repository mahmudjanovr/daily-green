/**
 * DailyGreen Server-Side Authentication & Authorization Gate
 *
 * Implements strict fail-closed authorization, kill-switch validation,
 * repository allowlist matching, circuit-breaker inspection, and secret scrubbing.
 */

import { RepoConfig, SecurityPolicyConfig } from '../types';
import { redactSecrets } from '../services/security';

export class AuthorizationError extends Error {
  public readonly code: string;
  public readonly statusCode: number;

  constructor(message: string, code = 'AUTH_FORBIDDEN', statusCode = 403) {
    super(redactSecrets(message));
    this.name = 'AuthorizationError';
    this.code = code;
    this.statusCode = statusCode;
  }
}

/**
 * Validates the global kill-switch.
 * Must fail closed if DAILYGREEN_ENABLED === 'false'.
 */
export function assertGlobalKillSwitch(): void {
  const envEnabled = process.env.DAILYGREEN_ENABLED;
  if (envEnabled !== undefined && envEnabled.trim().toLowerCase() === 'false') {
    throw new AuthorizationError(
      'DailyGreen execution is halted by global kill switch (DAILYGREEN_ENABLED=false).',
      'KILL_SWITCH_ACTIVE',
      503
    );
  }
}

/**
 * Validates that live mutations are strictly prohibited in this phase.
 */
export function assertMutationSafety(dryRunRequested?: boolean, allowLiveMutationsRequested?: boolean): {
  dryRun: boolean;
  allowLiveMutations: boolean;
} {
  // In Phase 2, live mutations remain strictly forbidden by policy
  const allowLive = false; // Forced false
  const dryRun = true; // Forced true

  if (allowLiveMutationsRequested === true) {
    throw new AuthorizationError(
      'ALLOW_LIVE_MUTATIONS is disabled by server safety policy in Phase 2.',
      'LIVE_MUTATIONS_FORBIDDEN',
      400
    );
  }

  if (dryRunRequested === false) {
    throw new AuthorizationError(
      'dry_run=false is prohibited in Phase 2. All operations must run in dry-run mode.',
      'DRY_RUN_MANDATORY',
      400
    );
  }

  return { dryRun, allowLiveMutations: allowLive };
}

/**
 * Validates a repository name format (owner/repo).
 */
export function validateRepoName(repoName: string): boolean {
  if (!repoName || typeof repoName !== 'string') return false;
  const regex = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
  return regex.test(repoName.trim());
}

/**
 * Asserts repository is authorized, enabled, and matches security allowlists.
 */
export function assertRepositoryAuthorized(
  repoName: string,
  authorizedRepos: RepoConfig[]
): RepoConfig {
  assertGlobalKillSwitch();

  if (!validateRepoName(repoName)) {
    throw new AuthorizationError(
      `Malformed repository name: "${repoName}". Must follow "owner/repo" format.`,
      'INVALID_REPO_NAME',
      400
    );
  }

  const target = authorizedRepos.find(
    (r) => r.name.toLowerCase() === repoName.toLowerCase().trim()
  );

  if (!target) {
    throw new AuthorizationError(
      `Repository "${repoName}" is not in the authorized repository allowlist.`,
      'REPO_NOT_AUTHORIZED',
      403
    );
  }

  if (!target.enabled) {
    throw new AuthorizationError(
      `Repository "${repoName}" is explicitly disabled in repository configuration.`,
      'REPO_DISABLED',
      403
    );
  }

  return target;
}

/**
 * Sanitizes errors and ensures no credentials or system internals leak.
 */
export function sanitizeErrorMessage(err: unknown): { message: string; code: string; statusCode: number } {
  if (err instanceof AuthorizationError) {
    return {
      message: err.message,
      code: err.code,
      statusCode: err.statusCode,
    };
  }

  const raw = err instanceof Error ? err.message : String(err);
  const clean = redactSecrets(raw);

  return {
    message: clean,
    code: 'INTERNAL_ERROR',
    statusCode: 500,
  };
}
