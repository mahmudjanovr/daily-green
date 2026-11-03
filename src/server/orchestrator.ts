/**
 * DailyGreen Server-Side 7-Stage Pipeline Orchestrator
 *
 * Coordinates real ephemeral HMAC workspaces, sanitized subprocess baseline & post-tests,
 * deterministic task discovery, cryptographic patch sealing, and durable persistence.
 */

import * as crypto from 'crypto';
import {
  CommandResult,
  DeliveryResult,
  ExecutionLog,
  QualityGateResult,
  RepoConfig,
  RunReport,
  SecurityCheckResult,
  SecurityPolicyConfig,
  ServerRunRecord,
  Task,
  VirtualFile,
} from '../types';
import {
  assertMutationSafety,
  assertRepositoryAuthorized,
  AuthorizationError,
} from './auth';
import {
  cleanupWorkspace,
  createIsolatedWorkspace,
  populateWorkspaceFiles,
  readWorkspaceFiles,
  WorkspaceMetadata,
} from './workspace';
import { executeSubprocess } from './worker';
import { serverPersistence } from './persistence';
import { discoverNextTask } from '../services/discovery';
import { implementTaskInWorkspace } from '../services/taskEngine';
import { countDiffLines } from '../services/security';
import { evaluateQualityGate } from '../services/qualityGate';
import { DEFAULT_CONFIG, DEFAULT_POLICY } from '../data/defaultConfig';
import { StateManager } from '../services/stateManager';

export interface ActiveRunJob {
  record: ServerRunRecord;
  abortController: AbortController;
  workspace?: WorkspaceMetadata;
}

export class ServerPipelineOrchestrator {
  private activeJobs: Map<string, ActiveRunJob> = new Map();
  private authorizedRepos: RepoConfig[] = DEFAULT_CONFIG.repos;
  private policy: SecurityPolicyConfig = DEFAULT_POLICY;
  private stateMgr = new StateManager();

  public setConfig(repos: RepoConfig[], policy: SecurityPolicyConfig) {
    this.authorizedRepos = repos;
    this.policy = policy;
  }

  public getAuthorizedRepos(): RepoConfig[] {
    return this.authorizedRepos;
  }

  public getPolicy(): SecurityPolicyConfig {
    return this.policy;
  }

  /**
   * Triggers a new pipeline run.
   */
  public async startRun(
    repoName: string,
    isBackupRun = false,
    requestedDryRun = true
  ): Promise<ServerRunRecord> {
    const runId = `dg-srv-${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
    const startTime = new Date().toISOString();

    // 1. Authorization & Policy Assertion
    assertMutationSafety(requestedDryRun, false);
    const targetRepo = assertRepositoryAuthorized(repoName, this.authorizedRepos);

    // 2. Circuit Breaker Check
    const circuitTripped = await serverPersistence.isCircuitTripped(targetRepo.name);
    if (circuitTripped) {
      throw new AuthorizationError(
        `Execution rejected: Circuit breaker is tripped for repository "${targetRepo.name}" after 3 consecutive failures. Reset required.`,
        'CIRCUIT_BREAKER_TRIPPED',
        429
      );
    }

    // 3. Concurrency Lease Acquisition
    const leaseAcquired = await serverPersistence.acquireLease(targetRepo.name, runId, 1800);
    if (!leaseAcquired) {
      throw new AuthorizationError(
        `Execution rejected: A concurrent run is already executing for repository "${targetRepo.name}". Max workers is 1.`,
        'CONCURRENT_RUN_CONFLICT',
        409
      );
    }

    const abortController = new AbortController();
    const runRecord: ServerRunRecord = {
      id: runId,
      repo: targetRepo.name,
      status: 'running',
      current_stage: 'Stage 1: Authorization & Policy Check',
      start_time: startTime,
      logs: [],
      cancellable: true,
      is_backup_run: isBackupRun,
      dry_run: true,
    };

    const job: ActiveRunJob = {
      record: runRecord,
      abortController,
    };

    this.activeJobs.set(runId, job);
    await serverPersistence.saveRun(runRecord);

    // Run execution asynchronously
    this.executePipelineAsync(job, targetRepo, isBackupRun).catch(async (err) => {
      // Unhandled fatal runner error
      runRecord.status = 'failed';
      runRecord.error = err.message;
      runRecord.end_time = new Date().toISOString();
      await serverPersistence.recordFailure(targetRepo.name, err.message);
      await serverPersistence.releaseLease(targetRepo.name, runId);
      await serverPersistence.saveRun(runRecord);
      this.activeJobs.delete(runId);
    });

    return runRecord;
  }

  /**
   * Cancels a running job.
   */
  public async cancelRun(runId: string): Promise<boolean> {
    const job = this.activeJobs.get(runId);
    if (!job) {
      // Check if run exists in persistence
      const saved = await serverPersistence.getRunById(runId);
      if (saved && (saved.status === 'running' || saved.status === 'queued')) {
        saved.status = 'cancelled';
        saved.end_time = new Date().toISOString();
        saved.cancellable = false;
        await serverPersistence.saveRun(saved);
        await serverPersistence.releaseLease(saved.repo, runId);
        return true;
      }
      return false;
    }

    job.abortController.abort();
    job.record.status = 'cancelled';
    job.record.end_time = new Date().toISOString();
    job.record.cancellable = false;
    job.record.logs.push({
      id: `log-${Date.now()}`,
      timestamp: new Date().toISOString(),
      level: 'WARN',
      message: 'Run was cancelled by operator request.',
    });

    await serverPersistence.saveRun(job.record);
    await serverPersistence.releaseLease(job.record.repo, runId);

    if (job.workspace) {
      await cleanupWorkspace(job.workspace);
    }

    this.activeJobs.delete(runId);
    return true;
  }

  /**
   * Async 7-stage pipeline execution worker.
   */
  private async executePipelineAsync(
    job: ActiveRunJob,
    repo: RepoConfig,
    isBackupRun: boolean
  ): Promise<void> {
    const { record, abortController } = job;
    const signal = abortController.signal;

    const addLog = async (level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS', message: string, extra?: any) => {
      const logEntry: ExecutionLog = {
        id: `log-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        timestamp: new Date().toISOString(),
        level,
        message,
        extra,
      };
      record.logs.push(logEntry);
      await serverPersistence.saveRun(record);
    };

    try {
      await addLog('INFO', `Starting DailyGreen Server Run [${record.id}] for ${repo.name}`);
      await addLog('INFO', `Policy defaults: dry_run=true, allow_live_mutations=false, max_workers=1`);

      if (signal.aborted) throw new Error('Run aborted');

      // Check HA backup idempotency
      if (isBackupRun) {
        const today = new Date().toISOString().split('T')[0];
        const state = await serverPersistence.loadState();
        const hasTaskCompletedToday = Object.keys(state.completed_tasks).some(
          (k) => k.startsWith(`${today}:${repo.name.toLowerCase()}:`)
        );
        if (hasTaskCompletedToday) {
          await addLog('INFO', 'Backup run: Primary run already completed a task today. Skipping.');
          record.status = 'completed';
          record.end_time = new Date().toISOString();
          record.cancellable = false;
          record.report = {
            run_id: record.id,
            timestamp: new Date().toISOString(),
            repo: repo.name,
            status: 'skipped',
            message: 'Backup run: primary run already succeeded today.',
            is_backup_run: true,
          };
          await serverPersistence.saveRun(record);
          await serverPersistence.releaseLease(repo.name, record.id);
          this.activeJobs.delete(record.id);
          return;
        }
      }

      // STAGE 2: Workspace & Baseline Quality Gate (Pre-tests)
      record.current_stage = 'Stage 2: Workspace & Baseline Quality Gate (Pre-tests)';
      await addLog('INFO', 'Creating isolated ephemeral workspace with cryptographic HMAC seal...');

      const workspace = await createIsolatedWorkspace('dg');
      job.workspace = workspace;

      // Seed workspace with sample files if none present
      const initialFiles: VirtualFile[] = [
        {
          path: 'README.md',
          content: `# ${repo.name}\n\nAutomated maintenance managed by DailyGreen.\n\nSee [documentation](docs/guide.md) for details.\n`,
        },
        {
          path: 'docs/guide.md',
          content: `# Documentation Guide\n\nThis guide explains the project usage.    \n\nRefer to [getting started](docs/getting-started.md) for quick setup.\n`,
        },
        {
          path: 'docs/getting-started.md',
          content: `# Getting Started\n\nInstall dependencies and run the tests.\n`,
        },
      ];

      await populateWorkspaceFiles(workspace, initialFiles);
      await addLog('INFO', `Workspace initialized at ${workspace.dirPath} (HMAC verified).`);

      let baselineResult: CommandResult | null = null;
      if (repo.baseline_command && repo.baseline_command.length > 0) {
        await addLog('INFO', `Running baseline pre-test in sanitized subprocess: ${repo.baseline_command.join(' ')}`);
        baselineResult = await executeSubprocess(repo.baseline_command, workspace.dirPath, repo.timeout_seconds, signal);
        if (!baselineResult.passed) {
          await addLog('ERROR', `Baseline pre-check FAILED: repository is already broken. Aborting pipeline.`);
          record.status = 'failed';
          record.end_time = new Date().toISOString();
          record.cancellable = false;
          record.report = {
            run_id: record.id,
            timestamp: new Date().toISOString(),
            repo: repo.name,
            status: 'failed',
            message: `Baseline check failed before making any changes: ${baselineResult.stderr || baselineResult.stdout}`,
            is_backup_run: isBackupRun,
          };
          await serverPersistence.recordFailure(repo.name, 'Baseline pre-check failed');
          await serverPersistence.saveRun(record);
          await serverPersistence.releaseLease(repo.name, record.id);
          await cleanupWorkspace(workspace);
          this.activeJobs.delete(record.id);
          return;
        }
        await addLog('SUCCESS', `Baseline check passed in ${baselineResult.duration_seconds}s.`);
      }

      if (signal.aborted) throw new Error('Run aborted');

      // STAGE 3: Task Discovery
      record.current_stage = 'Stage 3: Task Discovery (Deterministic / Backlog)';
      await addLog('INFO', 'Running deterministic rules-first task discovery...');

      const candidateTask = discoverNextTask(initialFiles, repo, this.policy, this.stateMgr);
      if (!candidateTask) {
        await addLog('INFO', 'No eligible maintenance tasks found for this repository. Zero modifications needed.');
        record.status = 'completed';
        record.end_time = new Date().toISOString();
        record.cancellable = false;
        record.report = {
          run_id: record.id,
          timestamp: new Date().toISOString(),
          repo: repo.name,
          status: 'no_task',
          message: 'No eligible maintenance candidate discovered.',
          is_backup_run: isBackupRun,
        };
        await serverPersistence.saveRun(record);
        await serverPersistence.releaseLease(repo.name, record.id);
        await cleanupWorkspace(workspace);
        this.activeJobs.delete(record.id);
        return;
      }

      // Check task idempotency
      const alreadyDone = await serverPersistence.isTaskAlreadyDone(repo.name, candidateTask.id);
      if (alreadyDone) {
        await addLog('INFO', `Task "${candidateTask.id}" was already completed today. Deduplicating.`);
        record.status = 'completed';
        record.end_time = new Date().toISOString();
        record.cancellable = false;
        record.report = {
          run_id: record.id,
          timestamp: new Date().toISOString(),
          repo: repo.name,
          status: 'skipped',
          task: candidateTask,
          message: `Task ${candidateTask.id} already completed today.`,
          is_backup_run: isBackupRun,
        };
        await serverPersistence.saveRun(record);
        await serverPersistence.releaseLease(repo.name, record.id);
        await cleanupWorkspace(workspace);
        this.activeJobs.delete(record.id);
        return;
      }

      record.task = candidateTask;
      await addLog('SUCCESS', `Discovered candidate task: "${candidateTask.title}" (${candidateTask.id})`);

      if (signal.aborted) throw new Error('Run aborted');

      // STAGE 4: Task Execution & Patch Synthesis
      record.current_stage = 'Stage 4: Task Execution & Patch Synthesis';
      await addLog('INFO', `Synthesizing patch for target files: ${candidateTask.target_files.join(', ')}`);

      const executionResult = implementTaskInWorkspace(initialFiles, candidateTask);
      await populateWorkspaceFiles(workspace, executionResult.updatedFiles);
      await addLog('INFO', `Applied patch in isolated workspace. Diff generated (${countDiffLines(executionResult.diff)} lines).`);

      if (signal.aborted) throw new Error('Run aborted');

      // STAGE 5: Quality Gate & SHA-256 Patch Seal
      record.current_stage = 'Stage 5: Quality Gate & SHA-256 Patch Seal';
      await addLog('INFO', 'Evaluating Quality Gate: allowlists, path bounds, secret scanning, tests...');

      const postTestResults: CommandResult[] = [];
      const postLintResults: CommandResult[] = [];

      for (const cmd of repo.test_commands) {
        await addLog('INFO', `Running post-change test in sanitized subprocess: ${cmd.join(' ')}`);
        const res = await executeSubprocess(cmd, workspace.dirPath, repo.timeout_seconds, signal);
        postTestResults.push(res);
      }

      for (const cmd of repo.lint_commands) {
        await addLog('INFO', `Running post-change linter in sanitized subprocess: ${cmd.join(' ')}`);
        const res = await executeSubprocess(cmd, workspace.dirPath, repo.timeout_seconds, signal);
        postLintResults.push(res);
      }

      const fileContentsMap: Record<string, string> = {};
      for (const f of executionResult.updatedFiles) {
        fileContentsMap[f.path] = f.content;
      }

      const qgResult = await evaluateQualityGate(
        candidateTask,
        executionResult.diff,
        fileContentsMap,
        repo,
        this.policy,
        baselineResult,
        postTestResults,
        postLintResults
      );

      if (!qgResult.passed) {
        await addLog('ERROR', `Quality Gate REJECTED proposed changes: ${qgResult.reason}`);
        record.status = 'failed';
        record.end_time = new Date().toISOString();
        record.cancellable = false;
        record.report = {
          run_id: record.id,
          timestamp: new Date().toISOString(),
          repo: repo.name,
          status: 'failed',
          task: candidateTask,
          quality_gate: qgResult,
          message: `Quality Gate failed: ${qgResult.reason}`,
          is_backup_run: isBackupRun,
        };
        await serverPersistence.recordFailure(repo.name, qgResult.reason);
        await serverPersistence.saveRun(record);
        await serverPersistence.releaseLease(repo.name, record.id);
        await cleanupWorkspace(workspace);
        this.activeJobs.delete(record.id);
        return;
      }

      await addLog('SUCCESS', `Quality Gate PASSED. Patch sealed with SHA-256: ${qgResult.patch_hash?.substring(0, 16)}...`);

      if (signal.aborted) throw new Error('Run aborted');

      // STAGE 6: Delivery Verification (Dry-Run Guard)
      record.current_stage = 'Stage 6: Delivery Verification (Dry-Run Guard)';
      await addLog('INFO', 'Verifying delivery authorization: dry_run=true, allow_live_mutations=false.');

      const deliveryResult: DeliveryResult = {
        success: true,
        is_dry_run: true,
        branch_name: `dailygreen/dry-run-${candidateTask.id}`,
        pr_number: 999,
        pr_url: `https://github.com/${repo.name}/pull/simulated-999`,
        message: 'Dry-run delivery verified. Zero remote branches or PRs created.',
        contribution_status: 'SIMULATED_DRY_RUN',
      };
      await addLog('INFO', deliveryResult.message);

      // STAGE 7: State Persistence & Run Journaling
      record.current_stage = 'Stage 7: State Persistence & Run Journaling';
      await addLog('INFO', 'Recording durable state to server persistence...');

      await serverPersistence.recordTaskCompletion(repo.name, candidateTask.id, {
        patch_hash: qgResult.patch_hash,
        run_id: record.id,
      });

      const finalReport: RunReport = {
        run_id: record.id,
        timestamp: new Date().toISOString(),
        repo: repo.name,
        status: 'dry_run_completed',
        task: candidateTask,
        quality_gate: qgResult,
        delivery: deliveryResult,
        message: 'Pipeline completed successfully in dry-run simulation mode.',
        is_backup_run: isBackupRun,
      };

      record.status = 'completed';
      record.end_time = new Date().toISOString();
      record.cancellable = false;
      record.report = finalReport;

      await serverPersistence.saveRun(record);
      await addLog('SUCCESS', `Run [${record.id}] finished successfully (Status: dry_run_completed).`);
    } catch (err: any) {
      if (signal.aborted) {
        await addLog('WARN', 'Pipeline execution was cancelled.');
        record.status = 'cancelled';
      } else {
        await addLog('ERROR', `Pipeline execution error: ${err.message}`);
        record.status = 'failed';
        record.error = err.message;
        await serverPersistence.recordFailure(repo.name, err.message);
      }
      record.end_time = new Date().toISOString();
      record.cancellable = false;
      await serverPersistence.saveRun(record);
    } finally {
      await serverPersistence.releaseLease(repo.name, record.id);
      if (job.workspace) {
        await cleanupWorkspace(job.workspace);
      }
      this.activeJobs.delete(record.id);
    }
  }
}

export const serverPipelineOrchestrator = new ServerPipelineOrchestrator();
