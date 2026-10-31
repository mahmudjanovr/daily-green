import { RunReport } from '../types';

export const CURRENT_STATE_SCHEMA_VERSION = 1;

export interface StateData {
  schema_version: number;
  is_browser_simulated: boolean;
  completed_tasks: Record<
    string,
    { timestamp: string; repo: string; task_id: string; details?: Record<string, any> }
  >;
  consecutive_failures: Record<string, number>;
  circuit_tripped: Record<string, boolean>;
  active_leases: Record<string, { run_id: string; timestamp: number; iso: string }>;
  runs: RunReport[];
}

const STORAGE_KEY = 'dailygreen_state_v1';

export class StateManager {
  private failureThreshold: number;
  private state: StateData;
  private storageAvailable: boolean;

  constructor(failureThreshold: number = 3) {
    this.failureThreshold = failureThreshold;
    this.storageAvailable = this.checkStorageAvailability();
    this.state = this.loadState();
  }

  private checkStorageAvailability(): boolean {
    try {
      if (typeof window === 'undefined' || !window.localStorage) return false;
      const testKey = '__dg_storage_test__';
      window.localStorage.setItem(testKey, '1');
      window.localStorage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  }

  private getDefaultState(): StateData {
    return {
      schema_version: CURRENT_STATE_SCHEMA_VERSION,
      is_browser_simulated: true,
      completed_tasks: {
        '2026-10-30:example-org/astro-portfolio:astro-doc-polish': {
          timestamp: '2026-10-30T17:15:32.000Z',
          repo: 'example-org/astro-portfolio',
          task_id: 'astro-doc-polish',
          details: { branch: 'dailygreen/2026-10-30-astro-doc-polish', pr_number: 14 },
        },
      },
      consecutive_failures: {},
      circuit_tripped: {},
      active_leases: {},
      runs: [
        {
          run_id: 'run-dg-20261030-2215',
          timestamp: '2026-10-30T17:15:44.000Z',
          repo: 'example-org/astro-portfolio',
          status: 'dry_run_completed',
          task: {
            id: 'astro-doc-polish',
            repo: 'example-org/astro-portfolio',
            title: 'Verify and clean trailing spaces in README',
            description: 'Whitespace cleanup in repository README',
            rationale: 'Clean markdown documentation style',
            acceptance_criteria: ['No trailing spaces'],
            risk_level: 'low',
            validation_strategy: 'formatting_verification',
            source: 'deterministic',
            target_files: ['README.md'],
            created_at: '2026-10-30T17:15:00.000Z',
          },
          message: 'Dry-run mode: All quality gates passed. PR creation simulated successfully.',
          is_backup_run: false,
        },
      ],
    };
  }

  private loadState(): StateData {
    const defaultState = this.getDefaultState();
    if (!this.storageAvailable) {
      return defaultState;
    }

    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState;
      const parsed = JSON.parse(raw);

      if (!parsed || typeof parsed !== 'object') {
        console.warn('[DailyGreen] Corrupted state format in storage. Reverting to safe defaults.');
        return defaultState;
      }

      // Validate and sanitize components
      const completedTasks: Record<string, any> =
        parsed.completed_tasks && typeof parsed.completed_tasks === 'object'
          ? parsed.completed_tasks
          : defaultState.completed_tasks;

      const consecutiveFailures: Record<string, number> =
        parsed.consecutive_failures && typeof parsed.consecutive_failures === 'object'
          ? parsed.consecutive_failures
          : {};

      const circuitTripped: Record<string, boolean> =
        parsed.circuit_tripped && typeof parsed.circuit_tripped === 'object'
          ? parsed.circuit_tripped
          : {};

      const runs: RunReport[] = Array.isArray(parsed.runs)
        ? parsed.runs.filter((r: any) => r && typeof r.run_id === 'string')
        : defaultState.runs;

      // Clean expired leases (> 30 mins)
      const now = Date.now();
      const rawLeases = parsed.active_leases || {};
      const activeLeases: Record<string, { run_id: string; timestamp: number; iso: string }> = {};

      if (typeof rawLeases === 'object') {
        for (const [repo, lease] of Object.entries(rawLeases)) {
          if (
            lease &&
            typeof lease === 'object' &&
            typeof (lease as any).timestamp === 'number' &&
            now - (lease as any).timestamp < 1800 * 1000
          ) {
            activeLeases[repo] = lease as any;
          }
        }
      }

      return {
        schema_version: CURRENT_STATE_SCHEMA_VERSION,
        is_browser_simulated: true,
        completed_tasks: completedTasks,
        consecutive_failures: consecutiveFailures,
        circuit_tripped: circuitTripped,
        active_leases: activeLeases,
        runs,
      };
    } catch (e) {
      console.warn('[DailyGreen] Failed to parse stored state. Fallback to clean state.', e);
      return defaultState;
    }
  }

  private saveState(): void {
    if (!this.storageAvailable) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.state));
    } catch (e) {
      console.warn('[DailyGreen] Failed to persist state to storage (quota or private mode).', e);
    }
  }

  public getState(): StateData {
    return this.state;
  }

  public isStorageHealthy(): boolean {
    return this.storageAvailable;
  }

  public getIdempotencyKey(repo: string, taskId: string, dateStr?: string): string {
    const d = dateStr || new Date().toISOString().split('T')[0];
    return `${d}:${repo.toLowerCase()}:${taskId}`;
  }

  public isTaskAlreadyDone(repo: string, taskId: string, dateStr?: string): boolean {
    const key = this.getIdempotencyKey(repo, taskId, dateStr);
    return Boolean(this.state.completed_tasks[key]);
  }

  public recordTaskCompletion(
    repo: string,
    taskId: string,
    details?: Record<string, any>,
    dateStr?: string
  ): void {
    const key = this.getIdempotencyKey(repo, taskId, dateStr);
    this.state.completed_tasks[key] = {
      timestamp: new Date().toISOString(),
      repo,
      task_id: taskId,
      details: details || {},
    };
    this.resetFailureCount(repo);
    this.saveState();
  }

  public isCircuitTripped(repo: string): boolean {
    const repoKey = repo.toLowerCase();
    const tripped = this.state.circuit_tripped[repoKey] || false;
    const failures = this.state.consecutive_failures[repoKey] || 0;
    return tripped || failures >= this.failureThreshold;
  }

  public getConsecutiveFailures(repo: string): number {
    return this.state.consecutive_failures[repo.toLowerCase()] || 0;
  }

  public recordFailure(repo: string, _errorMessage: string): void {
    const repoKey = repo.toLowerCase();
    const current = (this.state.consecutive_failures[repoKey] || 0) + 1;
    this.state.consecutive_failures[repoKey] = current;

    if (current >= this.failureThreshold) {
      this.state.circuit_tripped[repoKey] = true;
    }
    this.saveState();
  }

  public resetFailureCount(repo: string): void {
    const repoKey = repo.toLowerCase();
    this.state.consecutive_failures[repoKey] = 0;
    this.state.circuit_tripped[repoKey] = false;
    this.saveState();
  }

  public acquireRunLease(
    repo: string,
    runId: string,
    leaseTimeoutSeconds: number = 1800
  ): boolean {
    const repoKey = repo.toLowerCase();
    const now = Date.now();
    const currentLease = this.state.active_leases[repoKey];

    if (currentLease) {
      if (
        now - currentLease.timestamp < leaseTimeoutSeconds * 1000 &&
        currentLease.run_id !== runId
      ) {
        return false;
      }
    }

    this.state.active_leases[repoKey] = {
      run_id: runId,
      timestamp: now,
      iso: new Date().toISOString(),
    };
    this.saveState();
    return true;
  }

  public releaseRunLease(repo: string, runId: string): void {
    const repoKey = repo.toLowerCase();
    const currentLease = this.state.active_leases[repoKey];
    if (currentLease && currentLease.run_id === runId) {
      delete this.state.active_leases[repoKey];
      this.saveState();
    }
  }

  public recordRun(report: RunReport): void {
    this.state.runs.unshift(report);
    if (this.state.runs.length > 50) {
      this.state.runs = this.state.runs.slice(0, 50);
    }
    this.saveState();
  }

  public clearAllHistory(): void {
    this.state = this.getDefaultState();
    this.state.completed_tasks = {};
    this.state.runs = [];
    this.saveState();
  }
}
