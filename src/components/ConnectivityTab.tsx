import React, { useState } from 'react';
import {
  Wifi,
  ShieldCheck,
  KeyRound,
  RotateCcw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Github,
  Lock,
} from 'lucide-react';
import { DailyGreenConfig, BackendHealthResponse, BackendCapabilitiesResponse } from '../types';
import { GitHubClient, LabeledIssue, RateLimitInfo, RepoDetails } from '../services/githubClient';
import { backendApiClient } from '../services/backendApi';

interface ConnectivityTabProps {
  config: DailyGreenConfig;
  githubToken: string;
  onUpdateGithubToken: (token: string) => void;
}

export const ConnectivityTab: React.FC<ConnectivityTabProps> = ({
  config,
  githubToken,
  onUpdateGithubToken,
}) => {
  const [tokenInput, setTokenInput] = useState(githubToken);
  const [isTesting, setIsTesting] = useState(false);
  const [isMockMode, setIsMockMode] = useState(!githubToken);
  const [backendHealth, setBackendHealth] = useState<BackendHealthResponse | null>(null);
  const [backendCaps, setBackendCaps] = useState<BackendCapabilitiesResponse | null>(null);
  const [isBackendChecking, setIsBackendChecking] = useState(false);

  const loadBackendStatus = async () => {
    setIsBackendChecking(true);
    const health = await backendApiClient.getHealth();
    if (health.connected && health.data) {
      setBackendHealth(health.data);
    }
    const caps = await backendApiClient.getCapabilities();
    if (caps.success && caps.data) {
      setBackendCaps(caps.data);
    }
    setIsBackendChecking(false);
  };

  React.useEffect(() => {
    loadBackendStatus();
  }, []);

  const [testResults, setTestResults] = useState<{
    tokenStatus: string;
    rateLimit: RateLimitInfo | null;
    user: any | null;
    reposStatus: Array<{
      repo: string;
      accessible: boolean;
      details?: RepoDetails;
      issuesCount: number;
      issues: LabeledIssue[];
      prsCount: number;
      error?: string;
    }>;
  } | null>(null);

  const handleRunCheck = async () => {
    setIsTesting(true);
    const client = new GitHubClient(tokenInput, isMockMode);

    try {
      const rateData = await client.getRateLimit();
      const user = await client.getAuthenticatedUser();

      const reposStatus = [];
      for (const r of config.repos) {
        try {
          const details = await client.getRepository(r.name);
          const issues = await client.getLabeledIssues(r.name, 'dailygreen');
          const prs = await client.getOpenPullRequests(r.name);
          reposStatus.push({
            repo: r.name,
            accessible: true,
            details,
            issuesCount: issues.length,
            issues,
            prsCount: prs.length,
          });
        } catch (err: any) {
          reposStatus.push({
            repo: r.name,
            accessible: false,
            issuesCount: 0,
            issues: [],
            prsCount: 0,
            error: err.message,
          });
        }
      }

      setTestResults({
        tokenStatus: tokenInput ? 'DETECTED' : 'NOT PROVIDED (Mock/Public Mode)',
        rateLimit: rateData.rate,
        user,
        reposStatus,
      });
    } catch {
      // In case of error
    } finally {
      setIsTesting(false);
    }
  };

  const handleSaveToken = () => {
    onUpdateGithubToken(tokenInput);
    if (tokenInput.trim()) {
      setIsMockMode(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Backend Server & Infrastructure Capabilities */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <span className={`inline-block w-2.5 h-2.5 rounded-full ${backendHealth ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
            <h2 className="text-base font-bold text-white">Backend Infrastructure & Execution Capabilities</h2>
          </div>
          <button
            onClick={loadBackendStatus}
            disabled={isBackendChecking}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50"
          >
            <RotateCcw className={`h-3.5 w-3.5 ${isBackendChecking ? 'animate-spin' : ''}`} />
            <span>Probe Server</span>
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-xs font-mono">
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <span className="text-[10px] text-slate-500 uppercase block font-sans">Status</span>
            <span className="font-bold text-emerald-400">{backendHealth ? 'CONNECTED (Full-Stack)' : 'STANDALONE SIMULATION'}</span>
          </div>
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <span className="text-[10px] text-slate-500 uppercase block font-sans">Node Environment</span>
            <span className="text-slate-200 font-semibold">{backendHealth?.environment.node_version || process.version || 'v22.x'}</span>
          </div>
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <span className="text-[10px] text-slate-500 uppercase block font-sans">Python Host</span>
            <span className="text-slate-200 font-semibold">{backendHealth?.environment.python_version || 'Python 3.10.12'}</span>
          </div>
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <span className="text-[10px] text-slate-500 uppercase block font-sans">Git Binary</span>
            <span className="text-slate-200 font-semibold">{backendHealth?.environment.git_version || 'git 2.34.1'}</span>
          </div>
        </div>

        {/* Explicit Limitations / Missing Dependencies Notice */}
        {backendCaps?.limitations && backendCaps.limitations.length > 0 && (
          <div className="mb-4 p-3.5 bg-amber-950/20 border border-amber-500/30 rounded-lg text-xs space-y-1">
            <div className="flex items-center gap-2 font-semibold text-amber-300">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
              <span>Host Dependencies & Safety Limitations</span>
            </div>
            <ul className="list-disc list-inside text-amber-200/80 space-y-0.5 pl-1 text-[11px]">
              {backendCaps.limitations.map((lim, i) => (
                <li key={i}>{lim}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Matrix of Capabilities */}
        {backendCaps?.matrix && (
          <div className="border border-slate-800 rounded-lg overflow-hidden text-xs">
            <table className="w-full text-left">
              <thead className="bg-slate-950 text-slate-400 font-mono text-[11px] border-b border-slate-800">
                <tr>
                  <th className="p-2.5">Subsystem Capability</th>
                  <th className="p-2.5">Mode</th>
                  <th className="p-2.5">Status</th>
                  <th className="p-2.5">Execution Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans">
                {backendCaps.matrix.map((item, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/30">
                    <td className="p-2.5 font-medium text-slate-200">{item.name}</td>
                    <td className="p-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase ${
                        item.mode === 'native' ? 'bg-emerald-950 text-emerald-300 border border-emerald-500/30' :
                        item.mode === 'missing_dependency' ? 'bg-amber-950 text-amber-300 border border-amber-500/30' :
                        'bg-slate-800 text-slate-400'
                      }`}>
                        {item.mode}
                      </span>
                    </td>
                    <td className="p-2.5">
                      <span className={`font-mono text-[11px] font-semibold ${item.supported ? 'text-emerald-400' : 'text-slate-500'}`}>
                        {item.supported ? 'SUPPORTED' : 'DISABLED'}
                      </span>
                    </td>
                    <td className="p-2.5 text-slate-400 text-[11px]">{item.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Configuration & Token Input */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center gap-2 mb-2">
          <Wifi className="h-5 w-5 text-emerald-400" />
          <h2 className="text-base font-bold text-white">
            GitHub Read-Only Connectivity Check (<code className="text-emerald-400">check-github</code>)
          </h2>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Verifies GitHub API authentication, rate limits, and read-only repository permissions.
          All connectivity calls are strictly read-only with zero mutations.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2 space-y-2">
            <label className="block text-xs font-semibold text-slate-300">
              GitHub Personal Access Token (PAT) / GitHub App Token:
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="ghp_... or github_pat_... (in-memory session only)"
                className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-emerald-500"
              />
              <button
                onClick={handleSaveToken}
                className="px-3 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-semibold"
              >
                Set Session Token
              </button>
              {tokenInput && (
                <button
                  onClick={() => {
                    setTokenInput('');
                    onUpdateGithubToken('');
                    setIsMockMode(true);
                  }}
                  className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-300 text-xs font-semibold border border-slate-700"
                  title="Purge token from session memory"
                >
                  Clear
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-400">
              <strong className="text-emerald-400">Security Invariant:</strong> Token is held strictly in volatile session memory. It is never persisted to localStorage or browser storage. Read-only connectivity checks never mutate remote state.
            </p>
          </div>

          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-300">
              Client Mode:
            </label>
            <div className="flex flex-col gap-2">
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isMockMode}
                  onChange={(e) => setIsMockMode(e.target.checked)}
                  className="rounded border-slate-700 text-emerald-500 focus:ring-emerald-500/20"
                />
                <span>Simulate Offline Mock Client</span>
              </label>

              <button
                onClick={handleRunCheck}
                disabled={isTesting}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow transition-all hover:scale-[1.01]"
              >
                {isTesting ? (
                  <>
                    <RotateCcw className="h-4 w-4 animate-spin" />
                    <span>Verifying Connectivity...</span>
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4" />
                    <span>Execute check-github</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Connectivity Check Output */}
      {testResults && (
        <div className="space-y-4">
          {/* Rate Limit & User Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-xs text-slate-500 uppercase font-mono font-bold mb-1">
                Token Authentication
              </div>
              <div className="flex items-center gap-2 font-mono text-sm font-semibold text-emerald-400">
                <KeyRound className="h-4 w-4" />
                <span>{testResults.tokenStatus}</span>
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                {isMockMode ? 'Operating in offline simulation mode' : 'Using provided credentials'}
              </p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-xs text-slate-500 uppercase font-mono font-bold mb-1">
                API Rate Limits
              </div>
              <div className="text-sm font-mono font-semibold text-slate-200">
                {testResults.rateLimit?.remaining} / {testResults.rateLimit?.limit} remaining
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Reset: {new Date((testResults.rateLimit?.reset || 0) * 1000).toLocaleTimeString()}
              </p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <div className="text-xs text-slate-500 uppercase font-mono font-bold mb-1">
                Authenticated User
              </div>
              <div className="flex items-center gap-2 font-mono text-sm font-semibold text-slate-200">
                <Github className="h-4 w-4 text-slate-400" />
                <span>{testResults.user?.login}</span>
                <span className="text-[10px] font-sans px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                  {testResults.user?.type}
                </span>
              </div>
            </div>
          </div>

          {/* Repositories Status */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <h3 className="text-sm font-bold text-white mb-3">
              Authorized Repositories Status ({testResults.reposStatus.length})
            </h3>

            <div className="space-y-3">
              {testResults.reposStatus.map((r) => (
                <div
                  key={r.repo}
                  className="p-3.5 bg-slate-950 rounded-lg border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-slate-200 text-sm">{r.repo}</span>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          r.accessible
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : 'bg-rose-500/20 text-rose-300'
                        }`}
                      >
                        {r.accessible ? 'ACCESSIBLE' : 'INACCESSIBLE'}
                      </span>
                    </div>

                    {r.details && (
                      <div className="text-slate-400 space-x-3">
                        <span>
                          Default branch: <strong className="text-slate-300">{r.details.default_branch}</strong>
                        </span>
                        <span>•</span>
                        <span>
                          Visibility: <strong className="text-slate-300">{r.details.private ? 'Private' : 'Public'}</strong>
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-4 text-slate-300">
                    <div className="p-2 bg-slate-900 rounded border border-slate-800 text-center">
                      <div className="font-mono font-bold text-emerald-400">{r.issuesCount}</div>
                      <div className="text-[10px] text-slate-500">Labeled Issues</div>
                    </div>
                    <div className="p-2 bg-slate-900 rounded border border-slate-800 text-center">
                      <div className="font-mono font-bold text-slate-200">{r.prsCount}</div>
                      <div className="text-[10px] text-slate-500">Open PRs</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 p-3 bg-emerald-950/20 border border-emerald-500/20 rounded-lg text-xs text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>Read-Only Check Completed: Zero remote mutations performed.</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
