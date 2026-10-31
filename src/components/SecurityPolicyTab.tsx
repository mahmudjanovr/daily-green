import React from 'react';
import {
  Lock,
  ShieldCheck,
  ShieldAlert,
  FileX,
  Key,
  Flame,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import { DailyGreenConfig, SecurityPolicyConfig } from '../types';

interface SecurityPolicyTabProps {
  config: DailyGreenConfig;
  onUpdatePolicy: (policy: SecurityPolicyConfig) => void;
  onToggleKillSwitch: () => void;
  onToggleDryRun: () => void;
}

export const SecurityPolicyTab: React.FC<SecurityPolicyTabProps> = ({
  config,
  onUpdatePolicy,
  onToggleKillSwitch,
  onToggleDryRun,
}) => {
  const policy = config.policy;

  const handleMaxLinesChange = (val: number) => {
    onUpdatePolicy({ ...policy, max_diff_lines: Math.min(500, Math.max(1, val)) });
  };

  return (
    <div className="space-y-6">
      {/* Policy Header & Emergency Controls */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Lock className="h-5 w-5 text-emerald-400" />
              <span>Global Security Policy & Safeguards (<code className="text-emerald-400">policy.yml</code>)</span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Enforced independently before, during, and after workspace execution. Fails closed.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={onToggleKillSwitch}
              className={`px-3 py-2 rounded-lg text-xs font-bold border transition-all ${
                config.enabled
                  ? 'bg-emerald-950/60 border-emerald-500/30 text-emerald-300'
                  : 'bg-rose-950/60 border-rose-500/40 text-rose-300'
              }`}
            >
              Kill Switch: {config.enabled ? 'ENABLED' : 'DISABLED (FAIL-CLOSED)'}
            </button>

            <button
              onClick={onToggleDryRun}
              className={`px-3 py-2 rounded-lg text-xs font-bold border transition-all ${
                config.dry_run
                  ? 'bg-blue-950/60 border-blue-500/30 text-blue-300'
                  : 'bg-amber-950/60 border-amber-500/30 text-amber-300'
              }`}
            >
              Mode: {config.dry_run ? 'DRY RUN (SAFE SIMULATION)' : 'LIVE REMOTE'}
            </button>
          </div>
        </div>

        {/* Security Invariants Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
            <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold mb-1">
              <ShieldCheck className="h-4 w-4" />
              <span>Zero Fabricated Commits</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-snug">
              If no legitimate maintenance task is found, DailyGreen reports <code className="text-slate-300">NO_TASK</code> and exits. Empty commits are forbidden.
            </p>
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
            <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold mb-1">
              <Key className="h-4 w-4" />
              <span>Sanitized Sandbox</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-snug">
              GitHub write tokens and cloud secrets are never exposed to test execution subprocesses.
            </p>
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
            <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold mb-1">
              <Lock className="h-4 w-4" />
              <span>Cryptographic Seal</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-snug">
              Every verified diff is sealed with a SHA-256 hash. Any alteration aborts delivery immediately.
            </p>
          </div>
        </div>
      </div>

      {/* Policy Settings Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Core Limits */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-bold text-white mb-2">Diff & Execution Boundaries</h3>

          <div className="space-y-3 text-xs">
            <div>
              <label className="block text-slate-300 font-semibold mb-1">
                Max Changed Lines Limit per Task:
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  value={policy.max_diff_lines}
                  onChange={(e) => handleMaxLinesChange(parseInt(e.target.value) || 150)}
                  min={10}
                  max={500}
                  className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-mono w-32"
                />
                <span className="text-slate-400 text-[11px]">
                  Default 150 lines. Prevents large or risky automated diffs.
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-800 space-y-2.5">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={policy.block_workflows}
                  onChange={(e) =>
                    onUpdatePolicy({ ...policy, block_workflows: e.target.checked })
                  }
                  className="mt-0.5 rounded border-slate-700 text-emerald-500 focus:ring-emerald-500/20"
                />
                <div>
                  <span className="font-semibold text-slate-200 block">
                    Strictly Block CI/CD Workflows (.github/workflows/**)
                  </span>
                  <span className="text-[11px] text-slate-400">
                    Prevents automated pipeline tampering or privilege escalation.
                  </span>
                </div>
              </label>

              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={policy.block_lockfiles}
                  onChange={(e) =>
                    onUpdatePolicy({ ...policy, block_lockfiles: e.target.checked })
                  }
                  className="mt-0.5 rounded border-slate-700 text-emerald-500 focus:ring-emerald-500/20"
                />
                <div>
                  <span className="font-semibold text-slate-200 block">
                    Strictly Block Dependency Lockfiles
                  </span>
                  <span className="text-[11px] text-slate-400">
                    Package lockfiles (package-lock.json, poetry.lock, Cargo.lock, yarn.lock, etc.) cannot be modified.
                  </span>
                </div>
              </label>

              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={policy.require_secret_scan}
                  onChange={(e) =>
                    onUpdatePolicy({ ...policy, require_secret_scan: e.target.checked })
                  }
                  className="mt-0.5 rounded border-slate-700 text-emerald-500 focus:ring-emerald-500/20"
                />
                <div>
                  <span className="font-semibold text-slate-200 block">
                    Mandatory Secret Scanning
                  </span>
                  <span className="text-[11px] text-slate-400">
                    Scans diff and modified files against AWS keys, GitHub tokens, Slack tokens, and private key blocks.
                  </span>
                </div>
              </label>
            </div>
          </div>
        </div>

        {/* Denied Paths & Extensions */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
          <h3 className="text-sm font-bold text-white mb-2">Denied Paths & Disallowed Extensions</h3>

          <div className="space-y-3 text-xs">
            <div>
              <span className="text-slate-400 font-semibold block mb-1">
                Global Denied Path Patterns ({policy.denied_paths.length}):
              </span>
              <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800 font-mono text-[11px] text-slate-300 max-h-36 overflow-y-auto space-y-0.5">
                {policy.denied_paths.map((p, idx) => (
                  <div key={idx} className="text-rose-400/90">
                    {p}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <span className="text-slate-400 font-semibold block mb-1">
                Disallowed Executable & Key Extensions:
              </span>
              <div className="flex flex-wrap gap-1.5 font-mono text-xs">
                {policy.disallowed_extensions.map((ext) => (
                  <span
                    key={ext}
                    className="px-2 py-0.5 rounded bg-slate-950 text-slate-300 border border-slate-800"
                  >
                    {ext}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
