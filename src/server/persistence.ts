/**
 * DailyGreen Durable Server-Side Persistence Engine
 *
 * Implements atomic state updates via tmpfile renaming, versioned schema validation,
 * idempotency recording, execution mutex leases, circuit breaker counters, and run journals.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { RunReport, ServerRunRecord } from '../types';

export const SERVER_SCHEMA_VERSION = 2;

export interface ServerStateSchema {
  schema_version: number;
  completed_tasks: Record<string, { completed_at: string; details?: any }>;
  active_leases: Record<string, { run_id: string; acquired_at: number; expires_at: number }>;
  consecutive_failures: Record<string, number>;
  circuit_tripped: Record<string, boolean>;
  runs: ServerRunRecord[];
  updated_at: string;
}

export class ServerPersistence {
  private stateFilePath: string;
  private stateDir: string;
  private inMemoryCache: ServerStateSchema | null = null;
  private lockPromise: Promise<void> = Promise.resolve();

  constructor(customStateDir?: string) {
    this.stateDir = customStateDir || path.join(process.cwd(), '.dailygreen');
    this.stateFilePath = path.join(this.stateDir, 'server_state.json');
  }

  private getDefaultState(): ServerStateSchema {
    return {
      schema_version: SERVER_SCHEMA_VERSION,
      completed_tasks: {},
      active_leases: {},
      consecutive_failures: {},
      circuit_tripped: {},
      runs: [],
      updated_at: new Date().toISOString(),
    };
  }

  /**
   * Loads state from disk with schema validation and automatic migration/recovery.
   */
  public async loadState(): Promise<ServerStateSchema> {
    if (this.inMemoryCache) {
      return this.inMemoryCache;
    }

    try {
      if (!fs.existsSync(this.stateDir)) {
        await fs.promises.mkdir(this.stateDir, { recursive: true, mode: 0o700 });
      }

      if (!fs.existsSync(this.stateFilePath)) {
        const initial = this.getDefaultState();
        await this.atomicSave(initial);
        this.inMemoryCache = initial;
        return initial;
      }

      const raw = await fs.promises.readFile(this.stateFilePath, 'utf8');
      const parsed = JSON.parse(raw);

      // Validate or migrate schema
      if (!parsed || typeof parsed !== 'object' || parsed.schema_version !== SERVER_SCHEMA_VERSION) {
        // Migrate or reset safely
        const migrated: ServerStateSchema = {
          ...this.getDefaultState(),
          completed_tasks: parsed.completed_tasks || {},
          consecutive_failures: parsed.consecutive_failures || {},
          circuit_tripped: parsed.circuit_tripped || {},
          runs: Array.isArray(parsed.runs) ? parsed.runs : [],
          schema_version: SERVER_SCHEMA_VERSION,
          updated_at: new Date().toISOString(),
        };
        await this.atomicSave(migrated);
        this.inMemoryCache = migrated;
        return migrated;
      }

      this.inMemoryCache = parsed as ServerStateSchema;
      return this.inMemoryCache;
    } catch (err) {
      // In case of unrecoverable corruption, fallback gracefully without crashing
      const fallback = this.getDefaultState();
      this.inMemoryCache = fallback;
      return fallback;
    }
  }

  /**
   * Atomically writes state to a tempfile then renames to target path.
   */
  private async atomicSave(state: ServerStateSchema): Promise<void> {
    state.updated_at = new Date().toISOString();
    const tempFile = path.join(
      this.stateDir,
      `server_state.json.tmp.${Date.now()}.${crypto.randomBytes(4).toString('hex')}`
    );

    const payload = JSON.stringify(state, null, 2);
    await fs.promises.writeFile(tempFile, payload, { encoding: 'utf8', mode: 0o600 });
    await fs.promises.rename(tempFile, this.stateFilePath);
    this.inMemoryCache = state;
  }

  /**
   * Synchronizes state updates under an asynchronous write lock.
   */
  private async withLock<T>(action: (state: ServerStateSchema) => Promise<T>): Promise<T> {
    let releaseLock: () => void = () => {};
    const nextLock = new Promise<void>((resolve) => {
      releaseLock = resolve;
    });

    const previousLock = this.lockPromise;
    this.lockPromise = nextLock;

    try {
      await previousLock;
      const state = await this.loadState();
      const result = await action(state);
      await this.atomicSave(state);
      return result;
    } finally {
      releaseLock();
    }
  }

  /**
   * Idempotency check: determines if a task was already completed today.
   */
  public async isTaskAlreadyDone(repo: string, taskId: string, dateStr?: string): Promise<boolean> {
    const today = dateStr || new Date().toISOString().split('T')[0];
    const key = `${today}:${repo.toLowerCase()}:${taskId}`;
    const state = await this.loadState();
    return !!state.completed_tasks[key];
  }

  /**
   * Records task completion into state.
   */
  public async recordTaskCompletion(repo: string, taskId: string, details?: any): Promise<void> {
    const today = new Date().toISOString().split('T')[0];
    const key = `${today}:${repo.toLowerCase()}:${taskId}`;
    await this.withLock(async (state) => {
      state.completed_tasks[key] = {
        completed_at: new Date().toISOString(),
        details,
      };
      // Reset failure counter on success
      state.consecutive_failures[repo] = 0;
      state.circuit_tripped[repo] = false;
    });
  }

  /**
   * Acquires an execution lease for a repository.
   * Prevents concurrent runs on the same repository.
   */
  public async acquireLease(repo: string, runId: string, timeoutSeconds = 1800): Promise<boolean> {
    return this.withLock(async (state) => {
      const now = Date.now();
      const existing = state.active_leases[repo];

      // If active lease exists and has not expired, reject
      if (existing && existing.expires_at > now && existing.run_id !== runId) {
        return false;
      }

      state.active_leases[repo] = {
        run_id: runId,
        acquired_at: now,
        expires_at: now + timeoutSeconds * 1000,
      };
      return true;
    });
  }

  /**
   * Releases an execution lease for a repository.
   */
  public async releaseLease(repo: string, runId: string): Promise<void> {
    await this.withLock(async (state) => {
      const existing = state.active_leases[repo];
      if (existing && existing.run_id === runId) {
        delete state.active_leases[repo];
      }
    });
  }

  /**
   * Checks if circuit breaker is tripped for a repository.
   */
  public async isCircuitTripped(repo: string): Promise<boolean> {
    const state = await this.loadState();
    return !!state.circuit_tripped[repo];
  }

  /**
   * Records failure and trips circuit breaker after 3 consecutive failures.
   */
  public async recordFailure(repo: string, error: string): Promise<{ circuitTripped: boolean; count: number }> {
    return this.withLock(async (state) => {
      const current = (state.consecutive_failures[repo] || 0) + 1;
      state.consecutive_failures[repo] = current;

      if (current >= 3) {
        state.circuit_tripped[repo] = true;
      }

      return {
        circuitTripped: !!state.circuit_tripped[repo],
        count: current,
      };
    });
  }

  /**
   * Resets circuit breaker for a repository.
   */
  public async resetCircuit(repo: string): Promise<void> {
    await this.withLock(async (state) => {
      state.consecutive_failures[repo] = 0;
      state.circuit_tripped[repo] = false;
    });
  }

  /**
   * Records a server run record.
   */
  public async saveRun(record: ServerRunRecord): Promise<void> {
    await this.withLock(async (state) => {
      const idx = state.runs.findIndex((r) => r.id === record.id);
      if (idx >= 0) {
        state.runs[idx] = record;
      } else {
        state.runs.unshift(record);
      }
      // Keep last 100 runs
      if (state.runs.length > 100) {
        state.runs = state.runs.slice(0, 100);
      }
    });
  }

  /**
   * Retrieves all recorded runs.
   */
  public async getRuns(limit = 50): Promise<ServerRunRecord[]> {
    const state = await this.loadState();
    return state.runs.slice(0, limit);
  }

  /**
   * Retrieves a specific run by ID.
   */
  public async getRunById(id: string): Promise<ServerRunRecord | null> {
    const state = await this.loadState();
    return state.runs.find((r) => r.id === id) || null;
  }
}

export const serverPersistence = new ServerPersistence();
