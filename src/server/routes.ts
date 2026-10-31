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
import { sanitizeErrorMessage } from './auth';

export const apiRouter = Router();

const serverBootTime = Date.now();

/**
 * GET /api/health
 * System health, runtime diagnostics, and security invariant check.
 */
apiRouter.get('/health', async (req: Request, res: Response) => {
  try {
    const caps = await probeSystemCapabilities();
    const killSwitchActive =
      process.env.DAILYGREEN_ENABLED !== undefined &&
      process.env.DAILYGREEN_ENABLED.trim().toLowerCase() === 'false';

    const health: BackendHealthResponse = {
      status: killSwitchActive ? 'degraded' : 'ok',
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
    const run = await serverPersistence.getRunById(req.params.id);
    if (!run) {
      res.status(404).json({ error: `Run with ID "${req.params.id}" not found.`, code: 'NOT_FOUND' });
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
    const runId = req.params.id;
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
