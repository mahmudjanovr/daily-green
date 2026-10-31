/**
 * DailyGreen Server-Side GitHub Client
 *
 * Interacts with GitHub API strictly from the server side.
 * Keeps tokens in server environment, enforces read-only access,
 * and completely prevents remote mutations in Phase 2.
 */

import { redactSecrets } from '../services/security';

export interface GitHubConnectivityResult {
  hasToken: boolean;
  userLogin?: string;
  userType?: string;
  rateLimitRemaining?: number;
  rateLimitTotal?: number;
  rateLimitReset?: string;
  error?: string;
}

export class ServerGitHubClient {
  private get token(): string | undefined {
    return process.env.GITHUB_TOKEN?.trim() || undefined;
  }

  /**
   * Safe read-only connectivity check.
   */
  public async checkConnectivity(): Promise<GitHubConnectivityResult> {
    const token = this.token;
    if (!token) {
      return {
        hasToken: false,
        error: 'No GITHUB_TOKEN configured in server environment. Read-only unauthenticated mode.',
      };
    }

    try {
      const res = await fetch('https://api.github.com/user', {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/vnd.github.v3+json',
          'User-Agent': 'DailyGreen-Server-v2',
        },
      });

      const remaining = res.headers.get('x-ratelimit-remaining');
      const limit = res.headers.get('x-ratelimit-limit');
      const reset = res.headers.get('x-ratelimit-reset');

      const rateLimitRemaining = remaining ? parseInt(remaining, 10) : undefined;
      const rateLimitTotal = limit ? parseInt(limit, 10) : undefined;
      const rateLimitReset = reset ? new Date(parseInt(reset, 10) * 1000).toISOString() : undefined;

      if (!res.ok) {
        if (res.status === 401) {
          return {
            hasToken: true,
            error: 'HTTP 401 Unauthorized: Server GITHUB_TOKEN is invalid or expired.',
            rateLimitRemaining,
            rateLimitTotal,
          };
        }
        return {
          hasToken: true,
          error: `GitHub API error: HTTP ${res.status}`,
          rateLimitRemaining,
          rateLimitTotal,
        };
      }

      const user = await res.json();
      return {
        hasToken: true,
        userLogin: user.login,
        userType: user.type,
        rateLimitRemaining,
        rateLimitTotal,
        rateLimitReset,
      };
    } catch (err: any) {
      return {
        hasToken: true,
        error: redactSecrets(err.message || 'Network error reaching GitHub API'),
      };
    }
  }

  /**
   * Read-only repository access check.
   */
  public async checkRepositoryAccess(repoName: string): Promise<{
    accessible: boolean;
    visibility?: string;
    defaultBranch?: string;
    permissions?: { read: boolean; write: boolean; admin: boolean };
    openIssuesCount?: number;
    error?: string;
  }> {
    const token = this.token;
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github.v3+json',
      'User-Agent': 'DailyGreen-Server-v2',
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      const res = await fetch(`https://api.github.com/repos/${repoName}`, { headers });
      if (!res.ok) {
        return {
          accessible: false,
          error: `HTTP ${res.status}: Repository not found or inaccessible.`,
        };
      }

      const data = await res.json();
      return {
        accessible: true,
        visibility: data.private ? 'Private' : 'Public',
        defaultBranch: data.default_branch || 'main',
        permissions: {
          read: !!data.permissions?.pull,
          write: !!data.permissions?.push,
          admin: !!data.permissions?.admin,
        },
      };
    } catch (err: any) {
      return {
        accessible: false,
        error: redactSecrets(err.message || 'Error reaching repository'),
      };
    }
  }
}

export const serverGitHubClient = new ServerGitHubClient();
