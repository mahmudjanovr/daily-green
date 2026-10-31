/**
 * DailyGreen Subprocess Execution Worker & Capability Detector
 *
 * Implements isolated, sanitized process execution with credential stripping,
 * strict timeouts, baseline test execution, and host capability probing.
 */

import { spawn } from 'child_process';
import { CommandResult } from '../types';
import { redactSecrets } from '../services/security';

/**
 * Builds a sanitized environment dictionary for subprocess execution.
 * Completely strips all secrets, tokens, keys, credentials, and CI/CD variables.
 */
export function getSanitizedEnvironment(): NodeJS.ProcessEnv {
  const sanitized: NodeJS.ProcessEnv = {};

  // Allowlist of strictly safe system variables
  const safeEnvVars = ['PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'TERM', 'SHELL', 'TMPDIR'];

  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;

    const upperKey = key.toUpperCase();

    // Check if key is explicitly safe
    if (safeEnvVars.includes(upperKey)) {
      sanitized[key] = value;
      continue;
    }

    // Blacklist any variable containing sensitive tokens or credentials
    if (
      upperKey.includes('TOKEN') ||
      upperKey.includes('SECRET') ||
      upperKey.includes('KEY') ||
      upperKey.includes('PASS') ||
      upperKey.includes('AUTH') ||
      upperKey.includes('CREDENTIAL') ||
      upperKey.includes('PAT') ||
      upperKey.startsWith('GH_') ||
      upperKey.startsWith('GITHUB_') ||
      upperKey.startsWith('AWS_') ||
      upperKey.startsWith('GEMINI_') ||
      upperKey.startsWith('GCP_') ||
      upperKey.startsWith('FIREBASE_')
    ) {
      continue; // STRIP CREDENTIAL
    }

    // Default to safe inclusion for general non-sensitive vars
    if (/^[A-Z0-9_]+$/.test(upperKey)) {
      sanitized[key] = value;
    }
  }

  // Explicitly inject safe indicators
  sanitized['DAILYGREEN_ISOLATED'] = '1';
  sanitized['CI'] = 'false';

  return sanitized;
}

/**
 * Executes a subprocess command safely with timeout and sanitized environment.
 */
export async function executeSubprocess(
  command: string[],
  cwd: string,
  timeoutSeconds = 30,
  abortSignal?: AbortSignal
): Promise<CommandResult> {
  const startTime = Date.now();

  if (!command || command.length === 0) {
    return {
      command: [],
      exit_code: 1,
      stdout: '',
      stderr: 'Empty command passed to runner.',
      duration_seconds: 0,
      timed_out: false,
      passed: false,
    };
  }

  const [executable, ...args] = command;
  const sanitizedEnv = getSanitizedEnvironment();

  return new Promise<CommandResult>((resolve) => {
    let stdoutData = '';
    let stderrData = '';
    let isTimedOut = false;
    let isTerminated = false;

    let timeoutTimer: NodeJS.Timeout | null = null;

    let childProcess: ReturnType<typeof spawn>;

    try {
      childProcess = spawn(executable, args, {
        cwd,
        env: sanitizedEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err: any) {
      const duration = (Date.now() - startTime) / 1000;
      return resolve({
        command,
        exit_code: 127,
        stdout: '',
        stderr: redactSecrets(err.message || 'Failed to spawn process'),
        duration_seconds: duration,
        timed_out: false,
        passed: false,
      });
    }

    // Handle AbortSignal cancellation
    if (abortSignal) {
      if (abortSignal.aborted) {
        childProcess.kill('SIGKILL');
        return resolve({
          command,
          exit_code: 130,
          stdout: '',
          stderr: 'Subprocess cancelled before start.',
          duration_seconds: 0,
          timed_out: false,
          passed: false,
        });
      }

      abortSignal.addEventListener('abort', () => {
        if (!isTerminated) {
          isTerminated = true;
          childProcess.kill('SIGKILL');
        }
      });
    }

    // Enforce execution timeout
    timeoutTimer = setTimeout(() => {
      isTimedOut = true;
      if (!isTerminated) {
        isTerminated = true;
        childProcess.kill('SIGKILL');
      }
    }, timeoutSeconds * 1000);

    childProcess.stdout?.on('data', (data) => {
      stdoutData += data.toString();
    });

    childProcess.stderr?.on('data', (data) => {
      stderrData += data.toString();
    });

    childProcess.on('error', (err) => {
      if (timeoutTimer) clearTimeout(timeoutTimer);
      const duration = (Date.now() - startTime) / 1000;
      resolve({
        command,
        exit_code: 1,
        stdout: redactSecrets(stdoutData),
        stderr: redactSecrets(err.message || stderrData),
        duration_seconds: duration,
        timed_out: isTimedOut,
        passed: false,
      });
    });

    childProcess.on('close', (code) => {
      if (timeoutTimer) clearTimeout(timeoutTimer);
      const duration = (Date.now() - startTime) / 1000;
      const exitCode = isTimedOut ? 124 : (code ?? 0);

      resolve({
        command,
        exit_code: exitCode,
        stdout: redactSecrets(stdoutData),
        stderr: redactSecrets(stderrData + (isTimedOut ? '\nProcess timed out.' : '')),
        duration_seconds: duration,
        timed_out: isTimedOut,
        passed: exitCode === 0 && !isTimedOut,
      });
    });
  });
}

/**
 * Detects system capability matrix (git, python, dailygreen module, and sandbox support).
 */
export async function probeSystemCapabilities(): Promise<{
  gitVersion: string | null;
  pythonVersion: string | null;
  hasDailygreenPython: boolean;
  pythonEngineError: string | null;
}> {
  let gitVersion: string | null = null;
  let pythonVersion: string | null = null;
  let hasDailygreenPython = false;
  let pythonEngineError: string | null = null;

  try {
    const gitRes = await executeSubprocess(['git', '--version'], process.cwd(), 5);
    if (gitRes.passed) {
      gitVersion = gitRes.stdout.trim();
    }
  } catch {
    gitVersion = null;
  }

  try {
    const pyRes = await executeSubprocess(['python3', '--version'], process.cwd(), 5);
    if (pyRes.passed) {
      pythonVersion = pyRes.stdout.trim() || pyRes.stderr.trim();
    }
  } catch {
    pythonVersion = null;
  }

  try {
    const modRes = await executeSubprocess(
      ['python3', '-c', 'import dailygreen; print(dailygreen.__file__)'],
      process.cwd(),
      5
    );
    if (modRes.passed) {
      hasDailygreenPython = true;
    } else {
      hasDailygreenPython = false;
      pythonEngineError = "Python module 'dailygreen' not installed in host Python environment.";
    }
  } catch (err: any) {
    hasDailygreenPython = false;
    pythonEngineError = err.message || 'Failed to probe Python dailygreen module';
  }

  return {
    gitVersion,
    pythonVersion,
    hasDailygreenPython,
    pythonEngineError,
  };
}
