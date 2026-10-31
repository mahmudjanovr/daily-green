/**
 * Backend Readiness Service Contracts for DailyGreen
 *
 * Defines typed service interfaces for a production backend daemon / worker.
 * Clearly separates browser-side simulated execution from native OS execution requirements
 * (filesystem isolation, subprocess sandboxing, native Git operations, Gitleaks, etc.).
 */

import {
  CommandResult,
  DeliveryResult,
  QualityGateResult,
  RepoConfig,
  RiskLevel,
  RunReport,
  SecurityCheckResult,
  SecurityPolicyConfig,
  Task,
  TaskSource,
  VirtualFile,
} from '../types';

/**
 * Capability execution environment indicator.
 */
export type CapabilityMode = 'browser_simulated' | 'native_backend_required';

export interface ServiceCapability {
  name: string;
  mode: CapabilityMode;
  description: string;
  backendRequirements?: string[];
}

/**
 * Capability matrix detailing which DailyGreen operations run client-side
 * vs which require a secure, isolated server-side backend runner.
 */
export const DAILYGREEN_CAPABILITY_MATRIX: ServiceCapability[] = [
  {
    name: 'Rules-First Task Discovery',
    mode: 'browser_simulated',
    description: 'Deterministic typo, link, formatting, backlog, and issue analysis.',
  },
  {
    name: 'Mandatory Quality Gate Evaluation',
    mode: 'browser_simulated',
    description: 'Path allowlist verification, diff bounds, regex secret scanning, SHA-256 seal.',
  },
  {
    name: 'Read-Only GitHub Connectivity Check',
    mode: 'browser_simulated',
    description: 'In-memory token testing, API rate limit inspection, repository accessibility.',
  },
  {
    name: 'Isolated Filesystem Workspace',
    mode: 'native_backend_required',
    description: 'Ephemeral containerized workspace directory with tmpfs and isolated worktree.',
    backendRequirements: ['Docker/container sandbox', 'Local git clone over HTTPS', 'tmpfs filesystem'],
  },
  {
    name: 'Sanitized Subprocess Execution',
    mode: 'native_backend_required',
    description: 'Execution of baseline/test/lint commands with stripped environment variables.',
    backendRequirements: ['Python/Node test runners', 'Restricted system environment', 'Process timeout enforcement'],
  },
  {
    name: 'Native Git Hook Suppression',
    mode: 'native_backend_required',
    description: 'Execution of git commands with -c core.hooksPath="" to prevent untrusted hook execution.',
    backendRequirements: ['Git 2.30+ binary on host'],
  },
  {
    name: 'Native Gitleaks Scanner',
    mode: 'native_backend_required',
    description: 'Deep entropy and commit scanning using the compiled Gitleaks binary.',
    backendRequirements: ['gitleaks binary on PATH'],
  },
  {
    name: 'Durable Multi-Runner State Store',
    mode: 'native_backend_required',
    description: 'Centralized database or encrypted bucket for distributed execution leases and idempotency.',
    backendRequirements: ['Persistent state service or database'],
  },
];

/**
 * Repository management contract.
 */
export interface IRepositoryManager {
  listAuthorizedRepositories(): Promise<RepoConfig[]>;
  getRepository(name: string): Promise<RepoConfig | null>;
  validateRepositoryConfig(config: RepoConfig): Promise<{ valid: boolean; errors: string[] }>;
}

/**
 * Workspace lifecycle contract for isolated task preparation.
 */
export interface IWorkspaceLifecycle {
  createIsolatedWorkspace(repo: RepoConfig): Promise<string>;
  cleanupWorkspace(workspaceId: string): Promise<void>;
  readWorkspaceFiles(workspaceId: string): Promise<VirtualFile[]>;
  writeWorkspaceFiles(workspaceId: string, files: VirtualFile[]): Promise<void>;
}

/**
 * Rules-first task discovery contract.
 */
export interface ITaskDiscovery {
  discoverCandidate(
    repo: RepoConfig,
    policy: SecurityPolicyConfig,
    files: VirtualFile[]
  ): Promise<Task | null>;
}

/**
 * Task implementation engine contract.
 */
export interface ITaskExecutor {
  implementTask(
    task: Task,
    files: VirtualFile[]
  ): Promise<{ updatedFiles: VirtualFile[]; diff: string }>;
}

/**
 * Subprocess command runner contract.
 */
export interface ITestRunner {
  runCommand(
    command: string[],
    workspaceId: string,
    timeoutSeconds: number
  ): Promise<CommandResult>;
}

/**
 * Independent mandatory quality gate contract.
 */
export interface IQualityGate {
  evaluateGate(
    task: Task,
    diff: string,
    files: VirtualFile[],
    repo: RepoConfig,
    policy: SecurityPolicyConfig,
    baselineResult?: CommandResult | null,
    testResults?: CommandResult[],
    lintResults?: CommandResult[]
  ): Promise<QualityGateResult>;
}

/**
 * Durable state and circuit breaker persistence contract.
 */
export interface IStatePersistence {
  isTaskAlreadyDone(repo: string, taskId: string, dateStr?: string): Promise<boolean>;
  recordTaskCompletion(repo: string, taskId: string, details?: Record<string, any>): Promise<void>;
  acquireLease(repo: string, runId: string, timeoutSeconds: number): Promise<boolean>;
  releaseLease(repo: string, runId: string): Promise<void>;
  isCircuitTripped(repo: string): Promise<boolean>;
  recordFailure(repo: string, error: string): Promise<void>;
  resetCircuit(repo: string): Promise<void>;
  recordRunReport(report: RunReport): Promise<void>;
  getRunHistory(limit?: number): Promise<RunReport[]>;
}

/**
 * GitHub delivery and PR publication contract.
 */
export interface IGitHubDelivery {
  deliver(
    task: Task,
    qualityGate: QualityGateResult,
    diff: string,
    repo: RepoConfig,
    policy: SecurityPolicyConfig,
    dryRun: boolean,
    allowLiveMutations: boolean
  ): Promise<DeliveryResult>;
}
