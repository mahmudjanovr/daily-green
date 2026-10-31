import React, { useState } from 'react';
import {
  Search,
  CheckCircle2,
  AlertCircle,
  FileText,
  ShieldAlert,
  ArrowRight,
  ListFilter,
  Sparkles,
  Info,
} from 'lucide-react';
import { DailyGreenConfig, Task, VirtualFile } from '../types';
import { StateManager } from '../services/stateManager';
import { discoverNextTask } from '../services/discovery';

interface DiscoveryTabProps {
  config: DailyGreenConfig;
  stateMgr: StateManager;
  virtualFiles: Record<string, VirtualFile[]>;
  selectedRepoName: string;
  onSelectRepo: (name: string) => void;
  onSelectTaskForPipeline: (repo: string) => void;
}

export const DiscoveryTab: React.FC<DiscoveryTabProps> = ({
  config,
  stateMgr,
  virtualFiles,
  selectedRepoName,
  onSelectRepo,
  onSelectTaskForPipeline,
}) => {
  const [candidate, setCandidate] = useState<Task | null>(null);
  const [hasDiscovered, setHasDiscovered] = useState(false);
  const [isScanning, setIsScanning] = useState(false);

  const selectedRepo =
    config.repos.find((r) => r.name === selectedRepoName) || config.repos[0];

  const handleRunDiscovery = () => {
    if (!selectedRepo) return;
    setIsScanning(true);
    setTimeout(() => {
      const repoFiles = virtualFiles[selectedRepo.name] || [];
      const task = discoverNextTask(repoFiles, selectedRepo, config.policy, stateMgr);
      setCandidate(task);
      setHasDiscovered(true);
      setIsScanning(false);
    }, 400);
  };

  return (
    <div className="space-y-6">
      {/* Intro & Discovery Rules Priority */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Search className="h-5 w-5 text-emerald-400" />
              <span>Read-Only Task Discovery Engine</span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Discovers legitimate maintenance candidates using strict{' '}
              <strong className="text-slate-200">rules-first, AI-second</strong> priority.
              Zero remote or local modifications are performed.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <select
              value={selectedRepoName}
              onChange={(e) => {
                onSelectRepo(e.target.value);
                setHasDiscovered(false);
              }}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-emerald-500"
            >
              {config.repos.map((r) => (
                <option key={r.name} value={r.name}>
                  {r.name}
                </option>
              ))}
            </select>

            <button
              onClick={handleRunDiscovery}
              disabled={isScanning}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow transition-all hover:scale-[1.02]"
            >
              <Search className="h-4 w-4" />
              <span>{isScanning ? 'Discovering...' : 'Discover Next Task'}</span>
            </button>
          </div>
        </div>

        {/* Priority Ladder */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-2">
          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <div className="text-[10px] font-mono text-emerald-400 font-bold uppercase mb-1">
              Priority 1
            </div>
            <h4 className="text-xs font-semibold text-slate-200">Labeled Issues</h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              GitHub issues explicitly tagged with label <code className="text-emerald-300">dailygreen</code>
            </p>
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <div className="text-[10px] font-mono text-emerald-400 font-bold uppercase mb-1">
              Priority 2
            </div>
            <h4 className="text-xs font-semibold text-slate-200">Curated Backlog</h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Repo-specific verified tasks defined in <code className="text-slate-300">repos.yml</code>
            </p>
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <div className="text-[10px] font-mono text-emerald-400 font-bold uppercase mb-1">
              Priority 3
            </div>
            <h4 className="text-xs font-semibold text-slate-200">Deterministic Checks</h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Broken links, trailing spaces, missing EOF newlines, and common doc typos
            </p>
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80">
            <div className="text-[10px] font-mono text-slate-500 font-bold uppercase mb-1">
              Priority 4 (Optional)
            </div>
            <h4 className="text-xs font-semibold text-slate-200">AI Proposals</h4>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Bounded doc improvements only when <code className="text-slate-300">allow_ai_tasks: true</code>
            </p>
          </div>
        </div>
      </div>

      {/* Discovery Output View */}
      {hasDiscovered && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
          {candidate ? (
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-4 border-b border-slate-800 pb-4">
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      CANDIDATE DISCOVERED
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-800 text-slate-300">
                      Source: {candidate.source}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-slate-800 text-slate-300">
                      Risk: {candidate.risk_level}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-white">{candidate.title}</h3>
                  <div className="text-xs font-mono text-slate-400 mt-1">
                    Task ID: <span className="text-emerald-400">{candidate.id}</span>
                  </div>
                </div>

                <button
                  onClick={() => onSelectTaskForPipeline(selectedRepo.name)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-all shadow"
                >
                  <span>Execute in Pipeline</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div className="space-y-2">
                  <div>
                    <span className="text-slate-500 font-semibold block mb-0.5">Description:</span>
                    <p className="text-slate-300 bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
                      {candidate.description}
                    </p>
                  </div>
                  <div>
                    <span className="text-slate-500 font-semibold block mb-0.5">Rationale:</span>
                    <p className="text-slate-300 bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
                      {candidate.rationale}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <div>
                    <span className="text-slate-500 font-semibold block mb-0.5">Target Files:</span>
                    <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80 font-mono text-slate-300 space-y-1">
                      {candidate.target_files.map((f) => (
                        <div key={f}>- {f}</div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span className="text-slate-500 font-semibold block mb-0.5">Acceptance Criteria:</span>
                    <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800/80 text-slate-300 space-y-1">
                      {candidate.acceptance_criteria.map((ac, idx) => (
                        <div key={idx} className="flex items-center gap-1.5">
                          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                          <span>{ac}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="p-3 bg-emerald-950/20 border border-emerald-500/20 rounded-lg text-xs text-emerald-300 flex items-center gap-2">
                <Info className="h-4 w-4 shrink-0 text-emerald-400" />
                <span>
                  Notice: Discovered candidate is proposed only. Zero remote or local modifications were made.
                </span>
              </div>
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="h-12 w-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto text-slate-400 mb-3">
                <CheckCircle2 className="h-6 w-6 text-emerald-400" />
              </div>
              <h3 className="text-sm font-bold text-white mb-1">STATUS: NO_TASK</h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto mb-2">
                No eligible maintenance tasks found for repository &apos;{selectedRepo.name}&apos;.
              </p>
              <p className="text-[11px] text-slate-500 max-w-lg mx-auto">
                DailyGreen exits cleanly without modifying anything. It never commits empty changes or fabricates activity.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
