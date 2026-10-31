import { redactSecrets } from './security';

export class GitHubAPIError extends Error {
  public statusCode?: number;
  constructor(message: string, statusCode?: number) {
    super(redactSecrets(message));
    this.name = 'GitHubAPIError';
    this.statusCode = statusCode;
  }
}

export interface GitHubUser {
  login: string;
  type: string;
  name?: string;
  avatar_url?: string;
}

export interface RateLimitInfo {
  limit: number;
  remaining: number;
  reset: number;
  used: number;
}

export interface RepoDetails {
  name: string;
  full_name: string;
  private: boolean;
  default_branch: string;
  permissions?: {
    admin: boolean;
    push: boolean;
    pull: boolean;
  };
}

export interface LabeledIssue {
  number: number;
  title: string;
  body: string;
  html_url: string;
  created_at: string;
  labels: Array<{ name: string }>;
}

export interface OpenPR {
  number: number;
  title: string;
  body: string;
  html_url: string;
  head: { ref: string; sha?: string };
  base: { ref: string };
  created_at: string;
}

/**
 * GitHub Client for DailyGreen.
 *
 * Implements read-only connectivity checks, rate-limit queries, and issue discovery.
 * Credentials are kept in-memory only during the active browser session.
 * Live remote mutations are strictly blocked in this phase.
 */
export class GitHubClient {
  private token: string;
  private isMock: boolean;

  constructor(token: string = '', isMock: boolean = false) {
    this.token = token.trim();
    this.isMock = isMock || !this.token;
  }

  public hasToken(): boolean {
    return Boolean(this.token);
  }

  public isMockMode(): boolean {
    return this.isMock;
  }

  public async getRateLimit(): Promise<{ rate: RateLimitInfo }> {
    if (this.isMock) {
      return {
        rate: {
          limit: 5000,
          remaining: 4999,
          reset: Math.floor(Date.now() / 1000) + 3600,
          used: 1,
        },
      };
    }

    try {
      const res = await fetch('https://api.github.com/rate_limit', {
        headers: {
          Accept: 'application/vnd.github.v3+json',
          Authorization: `Bearer ${this.token}`,
        },
      });
      if (!res.ok) {
        throw new GitHubAPIError(`GitHub API rate limit check failed with HTTP ${res.status}`, res.status);
      }
      return await res.json();
    } catch (err: any) {
      if (err instanceof GitHubAPIError) throw err;
      // Network or CORS failure fallback to unauthenticated mock
      return {
        rate: {
          limit: 60,
          remaining: 59,
          reset: Math.floor(Date.now() / 1000) + 3600,
          used: 1,
        },
      };
    }
  }

  public async getAuthenticatedUser(): Promise<GitHubUser> {
    if (this.isMock) {
      return {
        login: 'developer-dailygreen',
        type: 'User',
        name: 'DailyGreen Maintainer',
        avatar_url: 'https://github.com/ghost.png',
      };
    }

    try {
      const res = await fetch('https://api.github.com/user', {
        headers: {
          Accept: 'application/vnd.github.v3+json',
          Authorization: `Bearer ${this.token}`,
        },
      });
      if (!res.ok) {
        throw new GitHubAPIError(`GitHub user authentication failed with HTTP ${res.status}`, res.status);
      }
      return await res.json();
    } catch (err: any) {
      if (err instanceof GitHubAPIError) throw err;
      throw new GitHubAPIError(`Network error while authenticating user: ${err.message}`);
    }
  }

  public async getRepository(repo: string): Promise<RepoDetails> {
    if (this.isMock) {
      return {
        name: repo.split('/')[1] || repo,
        full_name: repo,
        private: false,
        default_branch: 'main',
        permissions: {
          admin: true,
          push: true,
          pull: true,
        },
      };
    }

    try {
      const res = await fetch(`https://api.github.com/repos/${repo}`, {
        headers: {
          Accept: 'application/vnd.github.v3+json',
          Authorization: `Bearer ${this.token}`,
        },
      });
      if (!res.ok) {
        throw new GitHubAPIError(`Failed to query repository '${repo}': HTTP ${res.status}`, res.status);
      }
      return await res.json();
    } catch (err: any) {
      if (err instanceof GitHubAPIError) throw err;
      throw new GitHubAPIError(`Failed to reach GitHub for repository '${repo}': ${err.message}`);
    }
  }

  public async getLabeledIssues(
    repo: string,
    label: string = 'dailygreen'
  ): Promise<LabeledIssue[]> {
    if (this.isMock) {
      if (repo.includes('astro')) {
        return [
          {
            number: 42,
            title: 'Fix typo in documentation: seperate -> separate',
            body: 'Please correct typo in `docs/guide.md` regarding separate build pipelines.',
            html_url: `https://github.com/${repo}/issues/42`,
            created_at: new Date().toISOString(),
            labels: [{ name: label }],
          },
        ];
      }
      return [];
    }

    try {
      const res = await fetch(
        `https://api.github.com/repos/${repo}/issues?labels=${encodeURIComponent(
          label
        )}&state=open`,
        {
          headers: {
            Accept: 'application/vnd.github.v3+json',
            Authorization: `Bearer ${this.token}`,
          },
        }
      );
      if (!res.ok) return [];
      const issues = await res.json();
      return Array.isArray(issues) ? issues.filter((i: any) => !i.pull_request) : [];
    } catch {
      return [];
    }
  }

  public async getOpenPullRequests(repo: string): Promise<OpenPR[]> {
    if (this.isMock) {
      return [];
    }

    try {
      const res = await fetch(
        `https://api.github.com/repos/${repo}/pulls?state=open`,
        {
          headers: {
            Accept: 'application/vnd.github.v3+json',
            Authorization: `Bearer ${this.token}`,
          },
        }
      );
      if (!res.ok) return [];
      const prs = await res.json();
      return Array.isArray(prs) ? prs : [];
    } catch {
      return [];
    }
  }
}
