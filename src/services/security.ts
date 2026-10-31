import { RepoConfig, SecurityCheckResult, SecurityPolicyConfig } from '../types';

export const SECRET_PATTERNS: Record<string, RegExp> = {
  'AWS Access Key': /AKIA[0-9A-Z]{16}/,
  'GitHub Classic Token': /gh[posru]_[a-zA-Z0-9]{36}/,
  'GitHub Fine-Grained Token': /github_pat_[a-zA-Z0-9_]{82}/,
  'Private Key Block': /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/,
  'Generic High-Entropy Secret': /(?:api[_-]?key|secret[_-]?key|auth[_-]?token|password)\s*[:=]\s*['"][0-9a-zA-Z\-_]{16,}['"]/i,
  'Slack Token': /xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}/,
  'Bearer or Basic Auth': /\b(?:Bearer|Basic|token)\s+[a-zA-Z0-9_.\-+/=]{16,}/i,
  'URL Embedded Credentials': /https?:\/\/([^:\s/]+):([^@\s/]+)@/,
};

export const SENSITIVE_KEY_SUBSTRINGS = [
  'TOKEN',
  'SECRET',
  'PRIVATE_KEY',
  'API_KEY',
  'PASSW',
  'AUTH',
  'CRED',
  'BEARER',
  'SIGNING',
  'CERT',
];

export function scanContentForSecrets(text: string): string[] {
  const detected: string[] = [];
  for (const [name, pattern] of Object.entries(SECRET_PATTERNS)) {
    if (pattern.test(text)) {
      detected.push(name);
    }
  }
  return detected;
}

export function redactSecrets(text: string, extraSecrets: string[] = []): string {
  if (!text) return text;
  let redacted = text;

  for (const s of extraSecrets) {
    if (s && s.length >= 4) {
      redacted = redacted.replaceAll(s, '***REDACTED_SECRET***');
    }
  }

  redacted = redacted.replace(/https?:\/\/([^:\s/]+):([^@\s/]+)@/g, 'https://***:***@');
  redacted = redacted.replace(/gh[posru]_[a-zA-Z0-9]{36}/g, '***REDACTED_GITHUB_TOKEN***');
  redacted = redacted.replace(/github_pat_[a-zA-Z0-9_]{82}/g, '***REDACTED_GITHUB_PAT***');
  redacted = redacted.replace(/AKIA[0-9A-Z]{16}/g, '***REDACTED_AWS_KEY***');
  redacted = redacted.replace(/xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}/g, '***REDACTED_SLACK_TOKEN***');
  redacted = redacted.replace(/\b(Bearer|Basic|token)\s+[a-zA-Z0-9_.\-+/=]{8,}/gi, '$1 ***REDACTED_AUTH***');
  redacted = redacted.replace(
    /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/g,
    '***REDACTED_PRIVATE_KEY_BLOCK***'
  );
  return redacted;
}

export function countDiffLines(diffText: string): number {
  let changed = 0;
  for (const line of diffText.split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) {
      continue;
    }
    if (line.startsWith('+') || line.startsWith('-')) {
      changed++;
    }
  }
  return changed;
}

export function validatePathSafety(relPath: string): boolean {
  if (!relPath) return false;
  const normalized = relPath.replace(/\\/g, '/');
  if (normalized.startsWith('/') || normalized.startsWith('../') || normalized.includes('/../') || normalized === '..') {
    return false;
  }
  return true;
}

function matchGlob(path: string, pattern: string): boolean {
  // Simple glob matcher for paths and filenames
  const regexStr = pattern
    .replace(/\./g, '\\.')
    .replace(/\*\*/g, '.*')
    .replace(/(?<!\.)\*/g, '[^/]*')
    .replace(/\?/g, '.');
  const regex = new RegExp(`^${regexStr}$`);
  const filename = path.split('/').pop() || '';
  return regex.test(path) || regex.test(filename);
}

export function isPathAllowed(
  relPath: string,
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig
): { allowed: boolean; reason: string } {
  const normalized = relPath.replace(/\\/g, '/').replace(/^\//, '');

  // 1. Disallowed extensions
  const ext = normalized.includes('.') ? `.${normalized.split('.').pop()?.toLowerCase()}` : '';
  if (ext && policy.disallowed_extensions.map((e) => e.toLowerCase()).includes(ext)) {
    return { allowed: false, reason: `File extension '${ext}' is prohibited by security policy` };
  }

  // 2. Denied paths in policy and repo
  const allDenied = [...policy.denied_paths, ...repoConfig.denied_paths];
  for (const pattern of allDenied) {
    if (matchGlob(normalized, pattern)) {
      return { allowed: false, reason: `Path '${normalized}' matches denied pattern '${pattern}'` };
    }
  }

  // 3. Allowed paths in repo config
  let matchedAllow = false;
  for (const pattern of repoConfig.allowed_paths) {
    if (matchGlob(normalized, pattern)) {
      matchedAllow = true;
      break;
    }
  }

  if (!matchedAllow) {
    return { allowed: false, reason: `Path '${normalized}' is outside allowed paths for repo ${repoConfig.name}` };
  }

  return { allowed: true, reason: 'Path is allowed' };
}

export async function computePatchHash(diffText: string): Promise<string> {
  const normalized = diffText.replace(/\r\n/g, '\n').split('\n').join('\n') + '\n';
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.subtle) {
    const encoder = new TextEncoder();
    const data = encoder.encode(normalized);
    const hashBuffer = await globalThis.crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  try {
    const nodeCrypto = await import('node:crypto');
    return nodeCrypto.createHash('sha256').update(normalized, 'utf-8').digest('hex');
  } catch {
    throw new Error('No cryptographic SHA-256 implementation available in runtime.');
  }
}

export function runSecurityChecks(
  targetFiles: string[],
  diffText: string,
  fileContents: Record<string, string>,
  repoConfig: RepoConfig,
  policy: SecurityPolicyConfig
): SecurityCheckResult {
  const details: string[] = [];
  const secretsDetected: string[] = [];
  const deniedFiles: string[] = [];
  const pathTraversals: string[] = [];

  // 1. Path safety and allowlist validation
  for (const f of targetFiles) {
    if (!validatePathSafety(f)) {
      pathTraversals.push(f);
      details.push(`Path traversal or invalid path detected: ${f}`);
      continue;
    }

    const { allowed, reason } = isPathAllowed(f, repoConfig, policy);
    if (!allowed) {
      deniedFiles.push(f);
      details.push(`File rejected: ${reason}`);
    }
  }

  // 2. Secret scanning in diff text
  const diffSecrets = scanContentForSecrets(diffText);
  if (diffSecrets.length > 0) {
    secretsDetected.push(...diffSecrets);
    details.push(`Secrets detected in proposed diff: ${diffSecrets.join(', ')}`);
  }

  // 3. Secret scanning in target file contents
  for (const f of targetFiles) {
    const content = fileContents[f];
    if (content) {
      const fileSecrets = scanContentForSecrets(content);
      for (const s of fileSecrets) {
        if (!secretsDetected.includes(s)) {
          secretsDetected.push(s);
          details.push(`Secret detected in '${f}': ${s}`);
        }
      }
    }
  }

  // 4. Diff size evaluation
  const linesChanged = countDiffLines(diffText);
  const maxLines = Math.min(repoConfig.max_diff_lines, policy.max_diff_lines);
  if (linesChanged > maxLines) {
    details.push(`Diff size (${linesChanged} lines) exceeds maximum limit (${maxLines} lines)`);
  }

  const passed =
    secretsDetected.length === 0 &&
    deniedFiles.length === 0 &&
    pathTraversals.length === 0 &&
    linesChanged <= maxLines;

  return {
    passed,
    secrets_detected: secretsDetected,
    denied_files: deniedFiles,
    path_traversals: pathTraversals,
    lines_changed: linesChanged,
    max_lines_allowed: maxLines,
    details,
  };
}
