import React from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Flame,
  CheckCircle2,
  Clock,
  GitPullRequest,
  Power,
  Shield,
  Sparkles,
} from 'lucide-react';
import { DailyGreenConfig } from '../types';

interface HeaderProps {
  config: DailyGreenConfig;
  onToggleEnabled: () => void;
  onToggleDryRun: () => void;
  onToggleLiveMutations: () => void;
  activeLeasesCount: number;
  backendConnected?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  config,
  onToggleEnabled,
  onToggleDryRun,
  onToggleLiveMutations,
  activeLeasesCount,
  backendConnected = false,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-sm shadow-emerald-500/10">
            <Shield className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                DailyGreen
                <span className="text-xs font-mono font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  v1.2.0
                </span>
              </h1>
              <div
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-mono border ${
                  backendConnected
                    ? 'bg-emerald-950/70 border-emerald-500/30 text-emerald-300'
                    : 'bg-amber-950/70 border-amber-500/30 text-amber-300'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${backendConnected ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                <span>{backendConnected ? 'Backend Connected' : 'Simulation Mode'}</span>
              </div>
            </div>
            <p className="text-xs text-slate-400">
              Reliable, secure, and production-minded automated code maintenance
            </p>
          </div>
        </div>

        {/* Global Controls & Status Badges */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Primary / Backup Schedule Info */}
          <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/80 border border-slate-700/60 text-xs text-slate-300 font-mono">
            <Clock className="h-3.5 w-3.5 text-slate-400" />
            <span>22:15 / 22:35 Tashkent (17:15 UTC)</span>
          </div>

          {/* Active Leases */}
          {activeLeasesCount > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 font-mono">
              <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
              <span>{activeLeasesCount} Active Lease</span>
            </div>
          )}

          {/* Kill Switch Toggle */}
          <button
            onClick={onToggleEnabled}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
              config.enabled
                ? 'bg-emerald-950/60 border-emerald-500/30 text-emerald-300 hover:bg-emerald-900/60'
                : 'bg-rose-950/60 border-rose-500/30 text-rose-300 hover:bg-rose-900/60'
            }`}
            title="Global kill switch (DAILYGREEN_ENABLED)"
          >
            <Power className="h-3.5 w-3.5" />
            <span>{config.enabled ? 'SYSTEM ENABLED' : 'KILL SWITCH ACTIVE'}</span>
          </button>

          {/* Dry Run Toggle */}
          <button
            onClick={onToggleDryRun}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
              config.dry_run
                ? 'bg-blue-950/60 border-blue-500/30 text-blue-300 hover:bg-blue-900/60'
                : 'bg-amber-950/60 border-amber-500/30 text-amber-300 hover:bg-amber-900/60'
            }`}
            title="DRY_RUN mode: Safe simulation with zero mutations"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>{config.dry_run ? 'DRY RUN (SAFE)' : 'LIVE MODE'}</span>
          </button>

          {/* Live Mutations Gate */}
          <button
            onClick={onToggleLiveMutations}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
              config.allow_live_mutations
                ? 'bg-rose-950/60 border-rose-500/40 text-rose-300 hover:bg-rose-900/60'
                : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-850'
            }`}
            title="ALLOW_LIVE_MUTATIONS: Authorizes real branch creation and PR opening"
          >
            {config.allow_live_mutations ? (
              <Flame className="h-3.5 w-3.5 text-rose-400" />
            ) : (
              <ShieldAlert className="h-3.5 w-3.5" />
            )}
            <span>
              {config.allow_live_mutations ? 'MUTATIONS ALLOWED' : 'MUTATIONS BLOCKED'}
            </span>
          </button>
        </div>
      </div>
    </header>
  );
};
