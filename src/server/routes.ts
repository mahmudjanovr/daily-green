/**
 * DailyGreen Express API Routes
 *
 * Implements the 7 core endpoints:
 * - GET  /api/health
 * - GET  /api/capabilities
 * - GET  /api/repositories
 * - GET  /api/runs
 * - GET  /api/runs/:id
 * - POST /api/runs
 * - POST /api/runs/:id/cancel
 */

import { Router, Request, Response } from 'express';
import {
  BackendCapabilitiesResponse,
  BackendHealthResponse,
  CancelRunResponse,
  CreateRunRequest,
} from '../types';
import { serverPipelineOrchestrator } from './orchestrator';
import { serverPersistence } from './persistence';
import { probeSystemCapabilities } from './worker';
import * as crypto from 'crypto';
import { schedulerService } from './scheduler';
import { inspectGitDiff, inspectGitStatus } from './gitService';
import { geminiService } from './geminiService';
import { redactSecrets } from '../services/security';
import { logger } from './logger';
import { metricsService } from './metricsService';
import { backupService } from './backupService';

export function sanitizeErrorMessage(err: unknown): { statusCode: number; message: string; code: string } {
  let message = 'Internal server error';
  let code = 'INTERNAL_ERROR';
  let statusCode = 500;

  if (err instanceof Error) {
    message = redactSecrets(err.message);
    if ('code' in err && typeof (err as any).code === 'string') {
      code = (err as any).code;
    }
    if ('statusCode' in err && typeof (err as any).statusCode === 'number') {
      statusCode = (err as any).statusCode;
    }
  } else if (typeof err === 'string') {
    message = redactSecrets(err);
  }

  return { statusCode, message, code };
}

export const apiRouter = Router();

// Request Correlation ID and Metrics Middleware
apiRouter.use((req: Request, res: Response, next) => {
  const startTime = Date.now();
  const correlationId = (req.headers['x-request-id'] as string) || (req.headers['x-correlation-id'] as string) || crypto.randomUUID();
  res.setHeader('X-Correlation-ID', correlationId);
  (req as any).correlationId = correlationId;

  res.on('finish', () => {
    const duration = Date.now() - startTime;
    metricsService.recordRequest(req.method, req.path, res.statusCode, duration);
  });

  next();
});

const serverBootTime = Date.now();

/**
 * GET /api/health
 * System health, runtime diagnostics, and security invariant check.
 */
apiRouter.get('/health', async (req: Request, res: Response) => {
  try {
    const caps = await probeSystemCapabilities();
    const killSwitchActive =
      process.env.DAILYGREEN_ENABLED === undefined ||
      process.env.DAILYGREEN_ENABLED.trim().toLowerCase() !== 'true';

    const health: BackendHealthResponse = {
      status: 'ok',
      uptime_seconds: Math.floor((Date.now() - serverBootTime) / 1000),
      timestamp: new Date().toISOString(),
      version: '1.0.0-phase2',
      environment: {
        node_version: process.version,
        python_version: caps.pythonVersion,
        git_version: caps.gitVersion,
        platform: process.platform,
      },
      security_invariants: {
        dry_run_default: true,
        allow_live_mutations: false,
        max_workers: 1,
        kill_switch_active: killSwitchActive,
      },
    };

    res.json(health);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/capabilities
 * Explicit reporting of real vs missing dependencies and supported capabilities.
 */
apiRouter.get('/capabilities', async (req: Request, res: Response) => {
  try {
    const sys = await probeSystemCapabilities();

    const response: BackendCapabilitiesResponse = {
      capabilities: {
        git_cli: sys.gitVersion !== null,
        isolated_workspace: true,
        subprocess_sandbox: true,
        python_runtime: sys.pythonVersion !== null,
        python_dailygreen_engine: sys.hasDailygreenPython,
        durable_persistence: true,
        live_github_delivery: false,
      },
      limitations: [
        ...(sys.hasDailygreenPython
          ? []
          : [
              "Original Python engine package 'dailygreen' (mahmudjanovr/daily-green) is not installed in the host Python environment. Execution operates via typed TypeScript security orchestrator.",
            ]),
        'Live mutations (ALLOW_LIVE_MUTATIONS) and direct remote branch/PR pushes are disabled by policy in Phase 2.',
        'Subprocesses are executed in a credential-sanitized environment (all tokens and keys stripped).',
      ],
      matrix: [
        {
          name: 'Cryptographic HMAC Workspaces',
          supported: true,
          mode: 'native',
          notes: 'Ephemeral directories with HMAC-SHA256 .workspace-owner signatures.',
        },
        {
          name: 'Sanitized Subprocess Execution',
          supported: true,
          mode: 'native',
          notes: 'Baseline commands & test runners executed with stripped credentials.',
        },
        {
          name: 'Git CLI Integration',
          supported: sys.gitVersion !== null,
          mode: sys.gitVersion !== null ? 'native' : 'simulated',
          notes: sys.gitVersion ? `Host binary detected: ${sys.gitVersion}` : 'Git binary not available on host.',
        },
        {
          name: 'Python Runtime',
          supported: sys.pythonVersion !== null,
          mode: sys.pythonVersion !== null ? 'native' : 'missing_dependency',
          notes: sys.pythonVersion ? `Host interpreter: ${sys.pythonVersion}` : 'Python 3 not found.',
        },
        {
          name: "Python 'dailygreen' Package",
          supported: sys.hasDailygreenPython,
          mode: sys.hasDailygreenPython ? 'native' : 'missing_dependency',
          notes: sys.hasDailygreenPython
            ? 'Original Phase 3 engine module available.'
            : "Dependency missing from host site-packages; reported honestly as required by spec.",
        },
        {
          name: 'Durable Atomic State Persistence',
          supported: true,
          mode: 'native',
          notes: 'Versioned schema 2 with atomic tmpfile renaming and circuit breaker.',
        },
        {
          name: 'Live GitHub Delivery',
          supported: false,
          mode: 'simulated',
          notes: 'Strictly dry-run; no commits, pushes, or real PRs created.',
        },
      ],
    };

    res.json(response);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/repositories
 * Lists authorized repositories and their security configuration.
 */
apiRouter.get('/repositories', (req: Request, res: Response) => {
  try {
    const repos = serverPipelineOrchestrator.getAuthorizedRepos();
    res.json({ repositories: repos });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/runs
 * Retrieves list of recent server runs.
 */
apiRouter.get('/runs', async (req: Request, res: Response) => {
  try {
    const limit = req.query.limit ? parseInt(String(req.query.limit), 10) : 50;
    const runs = await serverPersistence.getRuns(isNaN(limit) ? 50 : limit);
    res.json({ runs });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/runs/:id
 * Retrieves a single run record by ID.
 */
apiRouter.get('/runs/:id', async (req: Request, res: Response) => {
  try {
    const runId = String(req.params.id);
    const run = await serverPersistence.getRunById(runId);
    if (!run) {
      res.status(404).json({ error: `Run with ID "${runId}" not found.`, code: 'NOT_FOUND' });
      return;
    }
    res.json({ run });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/runs
 * Triggers a new server-side pipeline run.
 */
apiRouter.post('/runs', async (req: Request, res: Response) => {
  try {
    const body = req.body as CreateRunRequest;
    if (!body || !body.repo) {
      res.status(400).json({ error: 'Missing required field "repo".', code: 'INVALID_REQUEST' });
      return;
    }

    const record = await serverPipelineOrchestrator.startRun(
      body.repo,
      !!body.is_backup_run,
      body.dry_run ?? true
    );

    res.status(201).json({ run: record });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/runs/:id/cancel
 * Cancels an in-progress or queued run.
 */
apiRouter.post('/runs/:id/cancel', async (req: Request, res: Response) => {
  try {
    const runId = String(req.params.id);
    const cancelled = await serverPipelineOrchestrator.cancelRun(runId);

    if (!cancelled) {
      res.status(404).json({
        error: `Run "${runId}" not found or not in a cancellable state.`,
        code: 'RUN_NOT_CANCELLABLE',
      });
      return;
    }

    const response: CancelRunResponse = {
      success: true,
      message: `Run ${runId} has been successfully cancelled.`,
      run_id: runId,
    };

    res.json(response);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/scheduler/status
 * Returns autonomous scheduling state, next run calculations, and audit log.
 */
apiRouter.get('/scheduler/status', async (req: Request, res: Response) => {
  try {
    const status = await schedulerService.getStatus();
    res.json(status);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/scheduler/toggle
 * Enables or disables the autonomous scheduler daemon.
 */
apiRouter.post('/scheduler/toggle', async (req: Request, res: Response) => {
  try {
    const currentlyRunning = schedulerService.isDaemonRunning();
    if (currentlyRunning) {
      schedulerService.stopDaemon();
    } else {
      schedulerService.startDaemon();
    }
    const status = await schedulerService.getStatus();
    res.json({
      success: true,
      message: `Autonomous scheduler daemon is now ${schedulerService.isDaemonRunning() ? 'running' : 'stopped'}.`,
      status,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/scheduler/trigger/:repo
 * Manually triggers a scheduled maintenance run for an authorized repository.
 */
apiRouter.post('/scheduler/trigger/:repo', async (req: Request, res: Response) => {
  try {
    const repoName = String(req.params.repo);
    const isBackup = req.body?.is_backup === true;
    const config = await serverPersistence.getConfig();

    const repo = config.repos.find((r) => r.name.toLowerCase() === repoName.toLowerCase());
    if (!repo) {
      res.status(404).json({ error: `Repository "${repoName}" not found or unauthorized.`, code: 'REPO_NOT_FOUND' });
      return;
    }

    const acquired = schedulerService.acquireLease(repo.name, `manual-sched-${Date.now()}`);
    if (!acquired) {
      res.status(409).json({
        error: `Could not acquire execution lease for "${repo.name}". Worker limit reached or active lease exists.`,
        code: 'LEASE_CONFLICT',
      });
      return;
    }

    schedulerService.recordAudit('TRIGGERED', repo.name, `Manual schedule trigger for '${repo.name}'`);
    const record = await serverPipelineOrchestrator.startRun(repo.name, isBackup, config.dry_run);

    res.status(201).json({
      success: true,
      message: `Scheduled run started for "${repo.name}"`,
      run: record,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * PUT /api/repositories/:repo/schedule
 * Updates repository-specific autonomous schedule settings.
 */
apiRouter.put('/repositories/:repo/schedule', async (req: Request, res: Response) => {
  try {
    const repoName = String(req.params.repo);
    const { time, timezone, enabled, backup_run_window_utc } = req.body;

    const config = await serverPersistence.getConfig();
    const repo = config.repos.find((r) => r.name.toLowerCase() === repoName.toLowerCase());

    if (!repo) {
      res.status(404).json({ error: `Repository "${repoName}" not found.`, code: 'REPO_NOT_FOUND' });
      return;
    }

    repo.schedule = {
      enabled: enabled ?? true,
      time: time || repo.schedule?.time || '09:00',
      timezone: timezone || repo.schedule?.timezone || 'Asia/Tashkent',
      backup_run_window_utc: backup_run_window_utc || '17:35',
    };

    await serverPersistence.saveConfig(config);
    serverPipelineOrchestrator.setConfig(config.repos, config.policy);

    res.json({
      success: true,
      message: `Updated schedule for ${repo.name}`,
      schedule: repo.schedule,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/repositories/:repo/reset-circuit
 * Resets circuit breaker for an authorized repository.
 */
apiRouter.post('/repositories/:repo/reset-circuit', async (req: Request, res: Response) => {
  try {
    const repoName = String(req.params.repo);
    await serverPersistence.resetCircuit(repoName);
    res.json({
      success: true,
      message: `Circuit breaker reset for "${repoName}". Failures counter cleared.`,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/git/diff-check
 * Inspects Git diff and status in a local repository directory safely.
 */
apiRouter.post('/git/diff-check', async (req: Request, res: Response) => {
  try {
    const targetDir = req.body?.dir;
    if (!targetDir || typeof targetDir !== 'string') {
      res.status(400).json({ error: 'Missing target directory "dir".', code: 'INVALID_REQUEST' });
      return;
    }

    const status = await inspectGitStatus(targetDir);
    const diff = await inspectGitDiff(targetDir);

    res.json({
      status,
      diff,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/ai/status
 * Returns server-side Gemini AI provider status and token metrics.
 */
apiRouter.get('/ai/status', async (req: Request, res: Response) => {
  try {
    const status = geminiService.getStatus();
    res.json(status);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/ai/classify
 * Classifies an incoming task and estimates its risk level using Gemini AI.
 */
apiRouter.post('/ai/classify', async (req: Request, res: Response) => {
  try {
    const { title, description } = req.body || {};
    if (!title || typeof title !== 'string') {
      res.status(400).json({ error: 'Missing required string field "title".', code: 'INVALID_REQUEST' });
      return;
    }

    const classification = await geminiService.classifyTask(title, description || '');
    res.json(classification);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/ai/improve-doc
 * Performs AI-assisted documentation improvements subject to strict AST and safety checks.
 */
apiRouter.post('/ai/improve-doc', async (req: Request, res: Response) => {
  try {
    const { filePath, content, instructions } = req.body || {};
    if (!filePath || !content || typeof content !== 'string') {
      res.status(400).json({ error: 'Missing "filePath" or "content".', code: 'INVALID_REQUEST' });
      return;
    }

    const result = await geminiService.improveDocumentation(filePath, content, instructions);
    res.json(result);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/ai/generate-pr
 * Generates an enterprise-grade Pull Request description with verification evidence.
 */
apiRouter.post('/ai/generate-pr', async (req: Request, res: Response) => {
  try {
    const { task, diff, qualityGate } = req.body || {};
    if (!task || !task.title) {
      res.status(400).json({ error: 'Missing task object.', code: 'INVALID_REQUEST' });
      return;
    }

    const prResult = await geminiService.generatePRDescription(task, diff || '', qualityGate);
    res.json(prResult);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/github/verify
 * Safe, read-only verification of GitHub authentication and accessible repositories.
 * Strictly never prints, logs, or returns the raw token.
 */
apiRouter.get('/github/verify', async (req: Request, res: Response) => {
  try {
    const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
    if (!token) {
      res.json({
        configured: false,
        authenticated: false,
        error: 'GITHUB_TOKEN environment variable is not configured in the server environment.',
      });
      return;
    }

    const headers = {
      'User-Agent': 'DailyGreen/1.3.0',
      'Accept': 'application/vnd.github.v3+json',
      'Authorization': `Bearer ${token.trim()}`,
    };

    // 1. Safe read-only authenticated user probe
    const userRes = await fetch('https://api.github.com/user', { headers });
    const rawRateLimit = {
      limit: parseInt(userRes.headers.get('x-ratelimit-limit') || '0', 10),
      remaining: parseInt(userRes.headers.get('x-ratelimit-remaining') || '0', 10),
      reset: parseInt(userRes.headers.get('x-ratelimit-reset') || '0', 10),
    };
    const scopesHeader = userRes.headers.get('x-oauth-scopes');
    const scopes = scopesHeader ? scopesHeader.split(',').map((s) => s.trim()).filter(Boolean) : [];

    if (!userRes.ok) {
      const errBody: any = await userRes.json().catch(() => ({}));
      logger.warn('GitHubAuth', `GitHub auth verification failed with status ${userRes.status}`);
      res.json({
        configured: true,
        authenticated: false,
        status_code: userRes.status,
        error: redactSecrets(errBody.message || 'GitHub authentication check failed'),
        rateLimit: rawRateLimit,
      });
      return;
    }

    const userData: any = await userRes.json();

    // 2. Safe read-only accessible repos probe
    let repoCount = 0;
    let repos: Array<{ name: string; full_name: string; private: boolean; permissions?: any }> = [];
    let repoError: string | undefined = undefined;

    try {
      const reposRes = await fetch('https://api.github.com/user/repos?per_page=100&sort=updated', { headers });
      if (reposRes.ok) {
        const repoList: any[] = await reposRes.json();
        repoCount = repoList.length;
        repos = repoList.map((r) => ({
          name: r.name,
          full_name: r.full_name,
          private: !!r.private,
          permissions: r.permissions,
        }));
      } else {
        const repoErrBody: any = await reposRes.json().catch(() => ({}));
        repoError = redactSecrets(repoErrBody.message || `HTTP ${reposRes.status} querying repositories`);
      }
    } catch (e: any) {
      repoError = redactSecrets(e.message);
    }

    logger.info('GitHubAuth', `GitHub verification successful for account ${userData.login}. Accessible repos: ${repoCount}`);

    res.json({
      configured: true,
      authenticated: true,
      account: {
        login: userData.login,
        name: userData.name || null,
        type: userData.type,
        id: userData.id,
        avatar_url: userData.avatar_url,
      },
      scopes,
      rateLimit: rawRateLimit,
      accessibleRepositoryCount: repoCount,
      repositories: repos,
      repoError,
    });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/metrics
 * SRE Observability & Prometheus-style metrics snapshot.
 */
apiRouter.get('/metrics', async (req: Request, res: Response) => {
  try {
    const metrics = await metricsService.getMetrics();
    res.json(metrics);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/logs
 * Structured JSON application and audit logs.
 */
apiRouter.get('/logs', async (req: Request, res: Response) => {
  try {
    const limit = parseInt(req.query.limit as string, 10) || 50;
    const level = req.query.level as any;
    const correlationId = req.query.correlationId as string;
    const logs = logger.getRecentLogs(limit, level, correlationId);
    res.json({ logs, count: logs.length });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/backups
 * Returns catalog of atomic state backups with SHA-256 integrity checksums.
 */
apiRouter.get('/backups', async (req: Request, res: Response) => {
  try {
    const backups = await backupService.listBackups();
    res.json({ backups, count: backups.length });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/backups
 * Creates an immediate atomic backup snapshot.
 */
apiRouter.post('/backups', async (req: Request, res: Response) => {
  try {
    const description = req.body?.description || 'Manual administrative backup';
    const backup = await backupService.createBackup(description);
    res.status(201).json({ success: true, backup });
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * GET /api/backups/:id/verify
 * Verifies cryptographic integrity of a specific backup snapshot.
 */
apiRouter.get('/backups/:id/verify', async (req: Request, res: Response) => {
  try {
    const backupId = Array.isArray(req.params.id) ? req.params.id[0] : req.params.id;
    const result = await backupService.verifyBackup(backupId);
    res.json(result);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});

/**
 * POST /api/backups/:id/restore
 * Safely restores system state from a verified backup.
 */
apiRouter.post('/backups/:id/restore', async (req: Request, res: Response) => {
  try {
    const backupId = Array.isArray(req.params.id) ? req.params.id[0] : req.params.id;
    const result = await backupService.restoreBackup(backupId);
    res.json(result);
  } catch (err) {
    const errorInfo = sanitizeErrorMessage(err);
    res.status(errorInfo.statusCode).json({ error: errorInfo.message, code: errorInfo.code });
  }
});



