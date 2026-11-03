import React, { useState } from 'react';
import {
  FileText,
  RotateCcw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Terminal,
  Trash2,
  RefreshCw,
  Copy,
  Flame,
} from 'lucide-react';
import { DailyGreenConfig, RunReport } from '../types';
import { StateManager } from '../services/stateManager';
import { formatMarkdownSummary } from '../services/reporting';
import { backendApiClient } from '../services/backendApi';

interface AuditReportTabProps {
  config: DailyGreenConfig;
  stateMgr: StateManager;
  onRefresh: () => void;
}

export const AuditReportTab: React.FC<AuditReportTabProps> = ({
  config,
  stateMgr,
  onRefresh,
}) => {
  const [selectedRun, setSelectedRun] = useState<RunReport | null>(null);
  const [viewFormat, setViewFormat] = useState<'summary' | 'json' | 'metrics' | 'backups' | 'state' | 'scheduler'>('summary');
  const [schedulerAudit, setSchedulerAudit] = useState<any[]>([]);
  const [metricsData, setMetricsData] = useState<any | null>(null);
  const [backupsList, setBackupsList] = useState<any[]>([]);
  const [newBackupDesc, setNewBackupDesc] = useState('');
  const [backupActionLoading, setBackupActionLoading] = useState(false);
  const [backupStatusMessage, setBackupStatusMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const loadMetricsAndBackups = async () => {
    const mRes = await backendApiClient.getMetrics();
    if (mRes.success && mRes.data) {
      setMetricsData(mRes.data);
    }
    const bRes = await backendApiClient.getBackups();
    if (bRes.success && bRes.data?.backups) {
      setBackupsList(bRes.data.backups);
    }
  };

  React.useEffect(() => {
    backendApiClient.getSchedulerStatus().then((res) => {
      if (res.success && res.data?.audit_trail) {
        setSchedulerAudit(res.data.audit_trail);
      }
    });
    loadMetricsAndBackups();
  }, [onRefresh, viewFormat]);

  const handleCreateImmediateBackup = async () => {
    setBackupActionLoading(true);
    setBackupStatusMessage(null);
    const res = await backendApiClient.createBackup(newBackupDesc || 'Manual administrative snapshot');
    if (res.success) {
      setBackupStatusMessage(`Backup created successfully: ${res.data?.backup?.id} (SHA-256 sealed)`);
      setNewBackupDesc('');
      loadMetricsAndBackups();
    } else {
      setBackupStatusMessage(`Failed to create backup: ${res.error}`);
    }
    setBackupActionLoading(false);
  };

  const handleVerifyBackupSnapshot = async (id: string) => {
    setBackupActionLoading(true);
    const res = await backendApiClient.verifyBackup(id);
    if (res.success && res.data?.valid) {
      alert(`[Integrity Confirmed]\nBackup ID: ${id}\nSHA-256 Checksum: ${res.data.sha256}\nIntegrity Seal: INTACT & UNCORRUPTED`);
    } else {
      alert(`[Integrity Verification Failed]\nBackup ID: ${id}\nError: ${res.data?.error || res.error}`);
    }
    setBackupActionLoading(false);
  };

  const handleRestoreBackupSnapshot = async (id: string) => {
    if (!confirm(`Restore system state from backup ${id}?\nAn automatic pre-restore safety snapshot will be taken first.`)) {
      return;
    }
    setBackupActionLoading(true);
    setBackupStatusMessage(null);
    const res = await backendApiClient.restoreBackup(id);
    if (res.success) {
      setBackupStatusMessage(`Restore successful from ${id}. Safety rollback snapshot captured: ${res.data?.pre_restore_backup_id}`);
      loadMetricsAndBackups();
      onRefresh();
    } else {
      setBackupStatusMessage(`Restore failed: ${res.error}`);
    }
    setBackupActionLoading(false);
  };

  const state = stateMgr.getState();
  const runs = state.runs || [];

  const handleResetCircuit = (repo: string) => {
    stateMgr.resetFailureCount(repo);
    onRefresh();
  };

  const handleClearHistory = () => {
    if (confirm('Clear all run reports and state history?')) {
      stateMgr.clearAllHistory();
      setSelectedRun(null);
      onRefresh();
    }
  };

  const handleCopyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Circuit Breakers & State Status */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <FileText className="h-5 w-5 text-emerald-400" />
                <span>Durable State, Circuit Breakers & Run History (<code className="text-emerald-400">report</code>)</span>
              </h2>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                schema v{state.schema_version || 1}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Tracks task idempotency, active runner leases, and trips circuit breakers on repeated failures.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleClearHistory}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-rose-300 bg-rose-950/40 hover:bg-rose-900/60 border border-rose-500/30"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>Clear History</span>
            </button>
          </div>
        </div>

        {/* Repositories Circuit Breaker Status */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {config.repos.map((r) => {
            const isTripped = stateMgr.isCircuitTripped(r.name);
            const failures = stateMgr.getConsecutiveFailures(r.name);
            const activeLease = state.active_leases[r.name.toLowerCase()];

            return (
              <div
                key={r.name}
                className={`p-3.5 rounded-lg border text-xs flex flex-col justify-between ${
                  isTripped
                    ? 'bg-rose-950/40 border-rose-500/40'
                    : 'bg-slate-950 border-slate-800'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-mono font-bold text-slate-200">{r.name}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        isTripped
                          ? 'bg-rose-500/20 text-rose-300'
                          : 'bg-emerald-500/20 text-emerald-300'
                      }`}
                    >
                      {isTripped ? 'CIRCUIT TRIPPED' : 'HEALTHY'}
                    </span>
                  </div>

                  <div className="text-[11px] text-slate-400 space-y-0.5">
                    <div>
                      Consecutive Failures: <strong className="text-slate-200">{failures} / 3</strong>
                    </div>
                    {activeLease && (
                      <div className="text-amber-400 flex items-center gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
                        <span>Active lease: {activeLease.run_id}</span>
                      </div>
                    )}
                  </div>
                </div>

                {isTripped && (
                  <button
                    onClick={() => handleResetCircuit(r.name)}
                    className="mt-2.5 flex items-center justify-center gap-1 w-full py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-semibold"
                  >
                    <RefreshCw className="h-3 w-3" />
                    <span>Reset Circuit Breaker</span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Runs List & Details */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Runs List */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Recent Runs ({runs.length})
            </h3>
            <span className="text-[10px] font-mono text-slate-500">Max 50 kept</span>
          </div>

          <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
            {runs.length === 0 ? (
              <p className="text-xs text-slate-500 italic p-3 text-center">
                No runs recorded yet. Run a pipeline to record reports.
              </p>
            ) : (
              runs.map((r) => {
                const isSelected = selectedRun?.run_id === r.run_id;
                let statusColor = 'text-emerald-400 border-emerald-500/20 bg-emerald-500/10';
                if (r.status === 'failed')
                  statusColor = 'text-rose-400 border-rose-500/20 bg-rose-500/10';
                else if (r.status === 'no_task' || r.status === 'skipped')
                  statusColor = 'text-slate-400 border-slate-700 bg-slate-800/60';

                return (
                  <div
                    key={r.run_id}
                    onClick={() => setSelectedRun(r)}
                    className={`p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-slate-800 border-emerald-500/40 text-white'
                        : 'bg-slate-950 border-slate-800/80 text-slate-300 hover:bg-slate-850'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono text-[11px] font-bold truncate">
                        {r.repo}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${statusColor}`}>
                        {r.status}
                      </span>
                    </div>

                    <div className="text-[10px] text-slate-500 flex items-center justify-between">
                      <span>{new Date(r.timestamp).toLocaleTimeString()}</span>
                      <span className="font-mono">{r.run_id.slice(-8)}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Selected Run Viewer or State Inspector */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-slate-300">View Format:</span>
                <div className="inline-flex rounded-lg border border-slate-700 bg-slate-950 p-0.5 text-xs font-medium flex-wrap gap-0.5">
                  <button
                    onClick={() => setViewFormat('summary')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'summary'
                        ? 'bg-slate-800 text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    GitHub Step Summary
                  </button>
                  <button
                    onClick={() => setViewFormat('metrics')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'metrics'
                        ? 'bg-emerald-800 text-white font-bold'
                        : 'text-emerald-400 hover:text-emerald-200'
                    }`}
                  >
                    SRE Metrics & Telemetry
                  </button>
                  <button
                    onClick={() => setViewFormat('backups')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'backups'
                        ? 'bg-indigo-800 text-white font-bold'
                        : 'text-indigo-400 hover:text-indigo-200'
                    }`}
                  >
                    Disaster Recovery Backups ({backupsList.length})
                  </button>
                  <button
                    onClick={() => setViewFormat('json')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'json'
                        ? 'bg-slate-800 text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Run JSON
                  </button>
                  <button
                    onClick={() => setViewFormat('state')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'state'
                        ? 'bg-slate-800 text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Full state.json
                  </button>
                  <button
                    onClick={() => setViewFormat('scheduler')}
                    className={`px-3 py-1 rounded transition-all ${
                      viewFormat === 'scheduler'
                        ? 'bg-slate-800 text-white'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Scheduler Audit ({schedulerAudit.length})
                  </button>
                </div>
              </div>

              <button
                onClick={() => {
                  if (viewFormat === 'summary' && selectedRun) {
                    handleCopyText(formatMarkdownSummary(selectedRun));
                  } else if (viewFormat === 'metrics' && metricsData) {
                    handleCopyText(JSON.stringify(metricsData, null, 2));
                  } else if (viewFormat === 'backups') {
                    handleCopyText(JSON.stringify(backupsList, null, 2));
                  } else if (viewFormat === 'json' && selectedRun) {
                    handleCopyText(JSON.stringify(selectedRun, null, 2));
                  } else if (viewFormat === 'scheduler') {
                    handleCopyText(JSON.stringify(schedulerAudit, null, 2));
                  } else {
                    handleCopyText(JSON.stringify(state, null, 2));
                  }
                }}
                className="flex items-center gap-1.5 px-3 py-1 rounded text-xs bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700 self-start sm:self-auto"
              >
                <Copy className="h-3.5 w-3.5" />
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            </div>

            {/* Display according to format */}
            {viewFormat === 'summary' && (
              <div>
                {selectedRun ? (
                  <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 text-xs text-slate-300 space-y-3 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed">
                    {formatMarkdownSummary(selectedRun)}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic text-center py-10">
                    Select a run from the list to preview its rendered GitHub Actions Step Summary.
                  </p>
                )}
              </div>
            )}

            {/* SRE Observability Metrics View */}
            {viewFormat === 'metrics' && (
              <div className="space-y-4">
                {metricsData ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                        <span className="text-slate-500 block text-[11px]">System Uptime</span>
                        <span className="font-mono font-bold text-slate-200">
                          {Math.floor(metricsData.system.uptime_seconds / 60)}m {metricsData.system.uptime_seconds % 60}s
                        </span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                        <span className="text-slate-500 block text-[11px]">Node Heap Memory</span>
                        <span className="font-mono font-bold text-slate-200">
                          {metricsData.system.memory_usage.heap_used_mb} MB / {metricsData.system.memory_usage.heap_total_mb} MB
                        </span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                        <span className="text-slate-500 block text-[11px]">HTTP Requests (p95 Latency)</span>
                        <span className="font-mono font-bold text-emerald-400">
                          {metricsData.http.total_requests} req ({metricsData.http.p95_latency_ms}ms)
                        </span>
                      </div>
                      <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                        <span className="text-slate-500 block text-[11px]">Durable Storage Footprint</span>
                        <span className="font-mono font-bold text-slate-200">
                          {Math.round(metricsData.storage.data_dir_bytes / 1024)} KB ({metricsData.storage.backups_count} backups)
                        </span>
                      </div>
                    </div>

                    <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 text-xs font-mono space-y-2">
                      <div className="text-slate-400 font-sans font-semibold">Security Invariant Status:</div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                        <div>dry_run default: <strong className="text-emerald-400">{String(metricsData.security_invariants.dry_run_default)}</strong></div>
                        <div>allow_live_mutations: <strong className="text-emerald-400">{String(metricsData.security_invariants.allow_live_mutations)}</strong></div>
                        <div>max_workers limit: <strong className="text-emerald-400">{metricsData.security_invariants.max_workers}</strong></div>
                        <div>kill_switch: <strong className={metricsData.security_invariants.kill_switch_active ? "text-rose-400" : "text-emerald-400"}>{metricsData.security_invariants.kill_switch_active ? "TRIGGERED" : "CLEAR"}</strong></div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic text-center py-6">Loading SRE observability metrics...</p>
                )}
              </div>
            )}

            {/* Disaster Recovery Backups View */}
            {viewFormat === 'backups' && (
              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    type="text"
                    value={newBackupDesc}
                    onChange={(e) => setNewBackupDesc(e.target.value)}
                    placeholder="Backup snapshot description (e.g. Pre-upgrade state)"
                    className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-500"
                  />
                  <button
                    onClick={handleCreateImmediateBackup}
                    disabled={backupActionLoading}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold whitespace-nowrap"
                  >
                    {backupActionLoading ? 'Processing...' : 'Create Atomic Snapshot'}
                  </button>
                </div>

                {backupStatusMessage && (
                  <div className="p-3 bg-indigo-950/40 border border-indigo-500/30 rounded-lg text-xs text-indigo-200">
                    {backupStatusMessage}
                  </div>
                )}

                <div className="border border-slate-800 rounded-lg overflow-hidden text-xs">
                  <table className="w-full text-left">
                    <thead className="bg-slate-950 text-slate-400 font-mono text-[11px] border-b border-slate-800">
                      <tr>
                        <th className="p-2.5">Snapshot ID & Timestamp</th>
                        <th className="p-2.5">Description</th>
                        <th className="p-2.5">SHA-256 Checksum Seal</th>
                        <th className="p-2.5">Size</th>
                        <th className="p-2.5 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-sans">
                      {backupsList.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="p-6 text-center text-slate-500 italic">
                            No backup snapshots created yet. Click 'Create Atomic Snapshot' above.
                          </td>
                        </tr>
                      ) : (
                        backupsList.map((b) => (
                          <tr key={b.id} className="hover:bg-slate-800/30 font-mono">
                            <td className="p-2.5">
                              <span className="font-bold text-slate-200 block">{b.id}</span>
                              <span className="text-[10px] text-slate-500">{new Date(b.created_at).toLocaleString()}</span>
                            </td>
                            <td className="p-2.5 text-slate-300 font-sans text-xs">{b.description}</td>
                            <td className="p-2.5 text-emerald-400 text-[10px] truncate max-w-[140px]" title={b.sha256_hash}>
                              {b.sha256_hash.slice(0, 16)}...
                            </td>
                            <td className="p-2.5 text-slate-400 text-xs font-mono">{b.size_bytes} B</td>
                            <td className="p-2.5 text-right font-sans">
                              <div className="inline-flex gap-1.5">
                                <button
                                  onClick={() => handleVerifyBackupSnapshot(b.id)}
                                  disabled={backupActionLoading}
                                  className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-[11px]"
                                >
                                  Verify
                                </button>
                                <button
                                  onClick={() => handleRestoreBackupSnapshot(b.id)}
                                  disabled={backupActionLoading}
                                  className="px-2 py-1 bg-amber-950/60 hover:bg-amber-900/60 border border-amber-500/30 text-amber-300 rounded text-[11px]"
                                >
                                  Restore
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {viewFormat === 'json' && (
              <div>
                {selectedRun ? (
                  <pre className="bg-slate-950 p-4 rounded-lg border border-slate-800 text-xs font-mono text-emerald-400/90 overflow-x-auto max-h-[460px]">
                    {JSON.stringify(selectedRun, null, 2)}
                  </pre>
                ) : (
                  <p className="text-xs text-slate-500 italic text-center py-10">
                    Select a run to view its structured JSON report.
                  </p>
                )}
              </div>
            )}

            {viewFormat === 'state' && (
              <div>
                <pre className="bg-slate-950 p-4 rounded-lg border border-slate-800 text-xs font-mono text-slate-300 overflow-x-auto max-h-[460px]">
                  {JSON.stringify(state, null, 2)}
                </pre>
              </div>
            )}

            {viewFormat === 'scheduler' && (
              <div className="space-y-2">
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-xs max-h-[460px] overflow-y-auto space-y-2">
                  {schedulerAudit.length === 0 ? (
                    <p className="text-slate-500 italic">No scheduler events recorded yet.</p>
                  ) : (
                    schedulerAudit.map((item) => (
                      <div key={item.id} className="p-2 rounded bg-slate-900/60 border border-slate-800/80">
                        <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                          <span className="font-bold text-emerald-400">[{item.event}]</span>
                          <span>{item.timestamp}</span>
                        </div>
                        <div className="text-slate-200">
                          <span className="text-slate-400 font-sans text-[11px]">Repo:</span>{' '}
                          <span className="font-bold">{item.repo}</span>
                        </div>
                        <div className="text-slate-300 text-[11px] mt-0.5">{item.details}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
