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
}

export const backendApiClient = new BackendApiClient();
