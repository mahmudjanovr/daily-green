/**
 * DailyGreen Server-Side Workspace Lifecycle & Ownership Verification
 *
 * Implements ephemeral filesystem workspaces with cryptographic HMAC-SHA256
 * ownership verification, strict path traversal defenses, and safe cleanup.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { VirtualFile } from '../types';

export class WorkspaceOwnershipError extends Error {
  public readonly code: string;
  constructor(message: string, code = 'WORKSPACE_OWNERSHIP_FAILED') {
    super(message);
    this.name = 'WorkspaceOwnershipError';
    this.code = code;
  }
}

// Server-wide ephemeral secret generated on boot for workspace ownership HMAC
const WORKSPACE_HMAC_SECRET = process.env.DAILYGREEN_HMAC_SECRET || crypto.randomBytes(32).toString('hex');
const WORKSPACES_BASE_DIR = path.join(os.tmpdir(), 'dailygreen_workspaces');

export interface WorkspaceMetadata {
  workspaceId: string;
  dirPath: string;
  createdAt: number;
  hmacSignature: string;
}

/**
 * Generates an HMAC-SHA256 signature for a workspace id and timestamp.
 */
export function generateOwnershipSignature(workspaceId: string, timestamp: number): string {
  const hmac = crypto.createHmac('sha256', WORKSPACE_HMAC_SECRET);
  hmac.update(`${workspaceId}:${timestamp}`);
  return hmac.digest('hex');
}

/**
 * Validates path safety, ensuring the target path is strictly inside the workspace.
 */
export function resolveSafeWorkspacePath(workspaceDir: string, relativePath: string): string {
  const normalizedRelative = path.normalize(relativePath).replace(/^(\.\.(\/|\\|$))+/, '');
  if (normalizedRelative.startsWith('..') || path.isAbsolute(normalizedRelative)) {
    throw new WorkspaceOwnershipError(
      `Path traversal attack detected: "${relativePath}" escapes workspace boundary.`,
      'PATH_TRAVERSAL_DETECTED'
    );
  }

  const resolved = path.resolve(workspaceDir, normalizedRelative);
  const normalizedRoot = path.resolve(workspaceDir);

  if (!resolved.startsWith(normalizedRoot + path.sep) && resolved !== normalizedRoot) {
    throw new WorkspaceOwnershipError(
      `Resolved path "${resolved}" escapes root directory "${normalizedRoot}".`,
      'PATH_TRAVERSAL_DETECTED'
    );
  }

  return resolved;
}

/**
 * Creates an isolated ephemeral workspace with HMAC ownership seal.
 */
export async function createIsolatedWorkspace(prefix = 'run'): Promise<WorkspaceMetadata> {
  if (!fs.existsSync(WORKSPACES_BASE_DIR)) {
    await fs.promises.mkdir(WORKSPACES_BASE_DIR, { recursive: true, mode: 0o700 });
  }

  const uniqueId = `${prefix}-${Date.now()}-${crypto.randomBytes(6).toString('hex')}`;
  const dirPath = path.join(WORKSPACES_BASE_DIR, uniqueId);
  const createdAt = Date.now();
  const hmacSignature = generateOwnershipSignature(uniqueId, createdAt);

  await fs.promises.mkdir(dirPath, { recursive: true, mode: 0o700 });

  const ownerPayload = JSON.stringify({
    workspaceId: uniqueId,
    createdAt,
    hmacSignature,
  });

  const ownerFilePath = path.join(dirPath, '.workspace-owner');
  await fs.promises.writeFile(ownerFilePath, ownerPayload, { encoding: 'utf8', mode: 0o600 });

  return {
    workspaceId: uniqueId,
    dirPath,
    createdAt,
    hmacSignature,
  };
}

/**
 * Verifies that the given directory is an authorized, untampered DailyGreen workspace.
 * Fails closed if the HMAC signature does not match or the ownership file is missing.
 */
export async function verifyWorkspaceOwnership(dirPath: string, expectedWorkspaceId: string): Promise<boolean> {
  const ownerFilePath = path.join(dirPath, '.workspace-owner');

  if (!fs.existsSync(ownerFilePath)) {
    throw new WorkspaceOwnershipError(
      `Workspace verification failed: Missing .workspace-owner marker in "${dirPath}".`,
      'OWNERSHIP_MARKER_MISSING'
    );
  }

  try {
    const raw = await fs.promises.readFile(ownerFilePath, 'utf8');
    const parsed = JSON.parse(raw);

    if (parsed.workspaceId !== expectedWorkspaceId) {
      throw new WorkspaceOwnershipError(
        `Workspace ID mismatch: expected "${expectedWorkspaceId}", found "${parsed.workspaceId}".`,
        'OWNERSHIP_ID_MISMATCH'
      );
    }

    const expectedSig = generateOwnershipSignature(parsed.workspaceId, parsed.createdAt);
    const valid = crypto.timingSafeEqual(
      Buffer.from(parsed.hmacSignature, 'hex'),
      Buffer.from(expectedSig, 'hex')
    );

    if (!valid) {
      throw new WorkspaceOwnershipError(
        'Workspace verification failed: HMAC signature is invalid or tampered.',
        'OWNERSHIP_HMAC_INVALID'
      );
    }

    return true;
  } catch (err: any) {
    if (err instanceof WorkspaceOwnershipError) throw err;
    throw new WorkspaceOwnershipError(
      `Corrupted workspace ownership data: ${err.message}`,
      'OWNERSHIP_DATA_CORRUPT'
    );
  }
}

/**
 * Populates files inside an isolated workspace safely.
 */
export async function populateWorkspaceFiles(
  workspace: WorkspaceMetadata,
  files: VirtualFile[]
): Promise<void> {
  await verifyWorkspaceOwnership(workspace.dirPath, workspace.workspaceId);

  for (const file of files) {
    const safePath = resolveSafeWorkspacePath(workspace.dirPath, file.path);
    const parentDir = path.dirname(safePath);
    if (!fs.existsSync(parentDir)) {
      await fs.promises.mkdir(parentDir, { recursive: true, mode: 0o700 });
    }
    await fs.promises.writeFile(safePath, file.content, 'utf8');
  }
}

/**
 * Reads all files from an isolated workspace safely.
 */
export async function readWorkspaceFiles(workspace: WorkspaceMetadata): Promise<VirtualFile[]> {
  await verifyWorkspaceOwnership(workspace.dirPath, workspace.workspaceId);
  const results: VirtualFile[] = [];

  async function walk(dir: string, baseDir: string) {
    const entries = await fs.promises.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name === '.workspace-owner' || entry.name === '.git') continue;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath, baseDir);
      } else if (entry.isFile()) {
        const relPath = path.relative(baseDir, fullPath).replace(/\\/g, '/');
        const content = await fs.promises.readFile(fullPath, 'utf8');
        results.push({ path: relPath, content });
      }
    }
  }

  await walk(workspace.dirPath, workspace.dirPath);
  return results;
}

/**
 * Safely removes a workspace after verifying its cryptographic ownership.
 */
export async function cleanupWorkspace(workspace: WorkspaceMetadata): Promise<void> {
  try {
    if (fs.existsSync(workspace.dirPath)) {
      await verifyWorkspaceOwnership(workspace.dirPath, workspace.workspaceId);
      await fs.promises.rm(workspace.dirPath, { recursive: true, force: true });
    }
  } catch (err) {
    // If directory already deleted or unmounted, log silently
  }
}
