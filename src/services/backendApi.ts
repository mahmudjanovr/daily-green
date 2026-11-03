/**
 * DailyGreen Client-Side Backend API Bridge
 *
 * Communicates with the Express backend endpoints (/api/*).
 * Provides graceful fallback detection if backend is unreachable,
 * ensuring the UI honestly indicates simulation vs live backend execution.
 */

import {
  BackendCapabilitiesResponse,
  BackendHealthResponse,
  CancelRunResponse,
  CreateRunRequest,
  RepoConfig,
  ServerRunRecord,
} from '../types';

export class BackendApiClient {
  private baseUrl = '';

  /**
   * Health check to probe backend connectivity.
   */
  public async getHealth(): Promise<{ connected: boolean; data?: BackendHealthResponse; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/health`, {
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) {
        return { connected: false, error: `HTTP ${res.status}: ${res.statusText}` };
      }
      const data = await res.json();
      return { connected: true, data };
    } catch (err: any) {
      return { connected: false, error: err.message || 'Cannot reach backend server' };
    }
  }

  /**
   * Fetch explicit backend capabilities and dependencies.
   */
  public async getCapabilities(): Promise<{ success: boolean; data?: BackendCapabilitiesResponse; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/capabilities`, {
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) {
        return { success: false, error: `HTTP ${res.status}` };
      }
      const data = await res.json();
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch authorized repositories from server.
   */
  public async getRepositories(): Promise<{ success: boolean; repositories?: RepoConfig[]; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/repositories`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { success: true, repositories: data.repositories };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch recent server runs.
   */
  public async getRuns(limit = 50): Promise<{ success: boolean; runs?: ServerRunRecord[]; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/runs?limit=${limit}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { success: true, runs: data.runs };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch single run by ID.
   */
  public async getRunById(id: string): Promise<{ success: boolean; run?: ServerRunRecord; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/runs/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { success: true, run: data.run };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Trigger a new server pipeline execution.
   */
  public async triggerRun(
    request: CreateRunRequest
  ): Promise<{ success: boolean; run?: ServerRunRecord; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(request),
      });

      const data = await res.json();
      if (!res.ok) {
        return { success: false, error: data.error || `HTTP ${res.status}` };
      }
      return { success: true, run: data.run };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Cancel an in-progress server run.
   */
  public async cancelRun(
    runId: string
  ): Promise<{ success: boolean; data?: CancelRunResponse; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) {
        return { success: false, error: data.error || `HTTP ${res.status}` };
      }
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch autonomous scheduler status and schedules.
   */
  public async getSchedulerStatus(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/scheduler/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Toggle the autonomous scheduler daemon.
   */
  public async toggleScheduler(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/scheduler/toggle`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Manually trigger a scheduled run for a repository.
   */
  public async triggerScheduledRun(
    repo: string,
    isBackup = false
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/scheduler/trigger/${encodeURIComponent(repo)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ is_backup: isBackup }),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error || `HTTP ${res.status}` };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Update repository schedule configuration.
   */
  public async updateRepoSchedule(
    repo: string,
    schedule: { time: string; timezone: string; enabled: boolean; backup_run_window_utc?: string }
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/repositories/${encodeURIComponent(repo)}/schedule`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(schedule),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Reset circuit breaker for a repository.
   */
  public async resetRepoCircuit(repo: string): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/repositories/${encodeURIComponent(repo)}/reset-circuit`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch server-side Gemini AI status and token metrics.
   */
  public async getAIStatus(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/ai/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Classify a task and evaluate its risk profile via Gemini AI.
   */
  public async classifyTaskAI(
    title: string,
    description: string
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/ai/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ title, description }),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Request AI-assisted documentation improvements.
   */
  public async improveDocAI(
    filePath: string,
    content: string,
    instructions?: string
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/ai/improve-doc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ filePath, content, instructions }),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Request an enterprise-grade Pull Request description generated from diff and proof.
   */
  public async generatePRDescriptionAI(
    task: any,
    diff: string,
    qualityGate?: any
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/ai/generate-pr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ task, diff, qualityGate }),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch SRE Observability metrics.
   */
  public async getMetrics(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/metrics`, {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch structured logs.
   */
  public async getLogs(limit = 50, level?: string): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const query = new URLSearchParams();
      if (limit) query.set('limit', String(limit));
      if (level) query.set('level', level);
      const res = await fetch(`${this.baseUrl}/api/logs?${query.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Fetch backup snapshots catalog.
   */
  public async getBackups(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/backups`, {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Create an immediate atomic backup.
   */
  public async createBackup(description?: string): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/backups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ description }),
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Verify backup checksum.
   */
  public async verifyBackup(id: string): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/backups/${id}/verify`, {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Restore state from backup.
   */
  public async restoreBackup(id: string): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/backups/${id}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Safe, read-only GitHub verification of configured server token.
   */
  public async verifyGitHub(): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      const res = await fetch(`${this.baseUrl}/api/github/verify`, {
        headers: { Accept: 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) return { success: false, error: data.error };
      return { success: true, data };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }
}

export const backendApiClient = new BackendApiClient();

