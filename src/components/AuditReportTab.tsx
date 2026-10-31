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
  const [viewFormat, setViewFormat] = useState<'summary' | 'json' | 'state'>('summary');
  const [copied, setCopied] = useState(false);

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
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-300">View Format:</span>
                <div className="inline-flex rounded-lg border border-slate-700 bg-slate-950 p-0.5 text-xs font-medium">
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
                </div>
              </div>

              <button
                onClick={() => {
                  if (viewFormat === 'summary' && selectedRun) {
                    handleCopyText(formatMarkdownSummary(selectedRun));
                  } else if (viewFormat === 'json' && selectedRun) {
                    handleCopyText(JSON.stringify(selectedRun, null, 2));
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
          </div>
        </div>
      </div>
    </div>
  );
};
