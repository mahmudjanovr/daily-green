import React, { useState } from 'react';
import {
  FolderGit2,
  Plus,
  Trash2,
  Check,
  ShieldAlert,
  Clock,
  Terminal,
  FileCheck,
  Sparkles,
} from 'lucide-react';
import { DailyGreenConfig, RepoConfig } from '../types';
import { validateRepoConfig } from '../validation/configValidator';

interface RepositoriesTabProps {
  config: DailyGreenConfig;
  onUpdateRepo: (repo: RepoConfig) => void;
  onAddRepo: (repo: RepoConfig) => void;
  onDeleteRepo: (name: string) => void;
}

export const RepositoriesTab: React.FC<RepositoriesTabProps> = ({
  config,
  onUpdateRepo,
  onAddRepo,
  onDeleteRepo,
}) => {
  const [selectedRepoName, setSelectedRepoName] = useState<string>(
    config.repos[0]?.name || ''
  );
  const [showAddModal, setShowAddModal] = useState(false);
  const [newRepoName, setNewRepoName] = useState('');
  const [newBranch, setNewBranch] = useState('main');
  const [addErrors, setAddErrors] = useState<string[]>([]);

  const selectedRepo =
    config.repos.find((r) => r.name === selectedRepoName) || config.repos[0];

  const handleToggleTaskType = (type: string) => {
    if (!selectedRepo) return;
    const exists = selectedRepo.supported_task_types.includes(type);
    const updatedTypes = exists
      ? selectedRepo.supported_task_types.filter((t) => t !== type)
      : [...selectedRepo.supported_task_types, type];
    onUpdateRepo({ ...selectedRepo, supported_task_types: updatedTypes });
  };

  const handleAddNewRepo = () => {
    setAddErrors([]);
    const repoTrimmed = newRepoName.trim();
    if (config.repos.some((r) => r.name.toLowerCase() === repoTrimmed.toLowerCase())) {
      setAddErrors([`Repository '${repoTrimmed}' is already present in allowlist.`]);
      return;
    }

    const newRepo: RepoConfig = {
      name: repoTrimmed,
      default_branch: newBranch.trim() || 'main',
      enabled: true,
      max_diff_lines: 120,
      timeout_seconds: 300,
      allowed_paths: ['docs/**', 'README.md'],
      denied_paths: [],
      supported_task_types: [
        'doc_links',
        'doc_formatting',
        'doc_typos',
        'curated_backlog',
        'issue_task',
      ],
      allow_ai_tasks: false,
      baseline_command: ['npm', 'run', 'build'],
      test_commands: [['npm', 'run', 'build']],
      lint_commands: [['npm', 'run', 'lint']],
      curated_tasks: [],
    };

    const valResult = validateRepoConfig(newRepo, config.policy);
    if (!valResult.valid) {
      setAddErrors(valResult.errors);
      return;
    }

    onAddRepo(newRepo);
    setSelectedRepoName(newRepo.name);
    setShowAddModal(false);
    setNewRepoName('');
    setAddErrors([]);
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <FolderGit2 className="h-5 w-5 text-emerald-400" />
            <span>Authorized Repositories Allowlist (<code className="text-emerald-400">repos.yml</code>)</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            DailyGreen strictly fails closed. Only repositories explicitly listed in this allowlist can be accessed or inspected.
          </p>
        </div>

        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow transition-all"
        >
          <Plus className="h-4 w-4" />
          <span>Add Authorized Repository</span>
        </button>
      </div>

      {/* Main Content Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Repo List Sidebar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Authorized Repositories ({config.repos.length})
          </h3>
          <div className="space-y-1.5">
            {config.repos.map((repo) => {
              const isSelected = selectedRepo?.name === repo.name;
              return (
                <div
                  key={repo.name}
                  onClick={() => setSelectedRepoName(repo.name)}
                  className={`p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-slate-800 border-emerald-500/40 text-white shadow-sm'
                      : 'bg-slate-950 border-slate-800/80 text-slate-300 hover:bg-slate-850'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold truncate">{repo.name}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        repo.enabled
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : 'bg-slate-800 text-slate-500'
                      }`}
                    >
                      {repo.enabled ? 'ACTIVE' : 'OFF'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-1">
                    <span>branch: {repo.default_branch}</span>
                    <span>•</span>
                    <span>{repo.supported_task_types.length} tasks</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Selected Repo Details & Editor */}
        {selectedRepo && (
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-5">
              {/* Repo Title & Enable Switch */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
                <div>
                  <h3 className="text-lg font-bold font-mono text-white">
                    {selectedRepo.name}
                  </h3>
                  <p className="text-xs text-slate-400">
                    Default branch: <code className="text-emerald-400">{selectedRepo.default_branch}</code>
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() =>
                      onUpdateRepo({ ...selectedRepo, enabled: !selectedRepo.enabled })
                    }
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                      selectedRepo.enabled
                        ? 'bg-emerald-950/60 border-emerald-500/30 text-emerald-300'
                        : 'bg-rose-950/60 border-rose-500/30 text-rose-300'
                    }`}
                  >
                    {selectedRepo.enabled ? 'Repository Enabled' : 'Repository Disabled'}
                  </button>

                  {config.repos.length > 1 && (
                    <button
                      onClick={() => onDeleteRepo(selectedRepo.name)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-950/30 border border-slate-800"
                      title="Remove repository from allowlist"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* General Limits */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Max Diff Lines Limit:
                  </label>
                  <input
                    type="number"
                    value={selectedRepo.max_diff_lines}
                    onChange={(e) =>
                      onUpdateRepo({
                        ...selectedRepo,
                        max_diff_lines: parseInt(e.target.value) || 100,
                      })
                    }
                    min={1}
                    max={config.policy.max_diff_lines}
                    className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-mono"
                  />
                  <span className="text-[10px] text-slate-500">
                    Cannot exceed global policy limit ({config.policy.max_diff_lines})
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Timeout (Seconds):
                  </label>
                  <input
                    type="number"
                    value={selectedRepo.timeout_seconds}
                    onChange={(e) =>
                      onUpdateRepo({
                        ...selectedRepo,
                        timeout_seconds: parseInt(e.target.value) || 300,
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-mono"
                  />
                </div>
              </div>

              {/* Supported Task Types */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-2">
                  Supported Task Types:
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                  {[
                    { id: 'doc_links', label: 'Broken Doc Links' },
                    { id: 'doc_formatting', label: 'Whitespace & EOF' },
                    { id: 'doc_typos', label: 'Common Typos' },
                    { id: 'curated_backlog', label: 'Curated Backlog' },
                    { id: 'issue_task', label: 'Labeled Issues' },
                  ].map((item) => {
                    const checked = selectedRepo.supported_task_types.includes(item.id);
                    return (
                      <button
                        key={item.id}
                        onClick={() => handleToggleTaskType(item.id)}
                        className={`flex items-center gap-2 p-2 rounded-lg border text-left transition-all ${
                          checked
                            ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300'
                            : 'bg-slate-950 border-slate-800 text-slate-500'
                        }`}
                      >
                        <div
                          className={`h-4 w-4 rounded flex items-center justify-center border ${
                            checked
                              ? 'bg-emerald-500 border-emerald-500 text-black'
                              : 'border-slate-700'
                          }`}
                        >
                          {checked && <Check className="h-3 w-3 stroke-[3]" />}
                        </div>
                        <span className="font-medium text-[11px]">{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Allowed Paths & Denied Paths */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Allowed Path Glob Patterns:
                  </label>
                  <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 space-y-1">
                    {selectedRepo.allowed_paths.map((pattern, idx) => (
                      <div key={idx} className="flex items-center justify-between">
                        <span>{pattern}</span>
                      </div>
                    ))}
                  </div>
                  <span className="text-[10px] text-slate-500 block mt-1">
                    Changes outside these paths will be immediately rejected by the Quality Gate.
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Repository Denied Patterns:
                  </label>
                  <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 space-y-1">
                    {selectedRepo.denied_paths.length === 0 ? (
                      <span className="text-slate-600 italic">None (merged with global policy)</span>
                    ) : (
                      selectedRepo.denied_paths.map((pattern, idx) => (
                        <div key={idx}>{pattern}</div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Commands Configuration */}
              <div className="space-y-3 border-t border-slate-800 pt-4">
                <h4 className="text-xs font-semibold text-slate-300">
                  Verification Commands
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-mono">
                  <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase font-sans font-bold mb-1">
                      Baseline Command
                    </span>
                    <span className="text-emerald-400">
                      {selectedRepo.baseline_command?.join(' ') || 'None'}
                    </span>
                  </div>

                  <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase font-sans font-bold mb-1">
                      Post-Change Tests
                    </span>
                    <span className="text-slate-300">
                      {selectedRepo.test_commands.map((c) => c.join(' ')).join('; ') || 'None'}
                    </span>
                  </div>

                  <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase font-sans font-bold mb-1">
                      Post-Change Linter
                    </span>
                    <span className="text-slate-300">
                      {selectedRepo.lint_commands.map((c) => c.join(' ')).join('; ') || 'None'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Curated Backlog Items */}
              {selectedRepo.curated_tasks.length > 0 && (
                <div className="border-t border-slate-800 pt-4 space-y-2">
                  <h4 className="text-xs font-semibold text-slate-300">
                    Configured Curated Backlog Tasks ({selectedRepo.curated_tasks.length})
                  </h4>
                  <div className="space-y-2">
                    {selectedRepo.curated_tasks.map((task) => (
                      <div
                        key={task.id}
                        className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs"
                      >
                        <div className="flex items-center justify-between font-bold text-white mb-1">
                          <span>{task.title}</span>
                          <span className="font-mono text-[10px] text-emerald-400 bg-slate-900 px-1.5 py-0.5 rounded">
                            {task.id}
                          </span>
                        </div>
                        <p className="text-slate-400 text-[11px] mb-1.5">{task.description}</p>
                        <div className="text-[10px] text-slate-500 font-mono">
                          targets: {task.target_files.join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Modal: Add Repository */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 max-w-md w-full space-y-4 shadow-xl">
            <h3 className="text-base font-bold text-white">Add Authorized Repository</h3>
            <p className="text-xs text-slate-400">
              DailyGreen requires repository names in <code className="text-emerald-400">owner/repo</code> format.
            </p>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 font-semibold mb-1">
                  Repository Name (owner/repo):
                </label>
                <input
                  type="text"
                  placeholder="e.g. org/my-service"
                  value={newRepoName}
                  onChange={(e) => setNewRepoName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-semibold mb-1">
                  Default Branch:
                </label>
                <input
                  type="text"
                  placeholder="main"
                  value={newBranch}
                  onChange={(e) => setNewBranch(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 font-mono"
                />
              </div>
            </div>

            {addErrors.length > 0 && (
              <div className="p-2.5 rounded-lg bg-rose-950/60 border border-rose-500/40 text-rose-300 text-[11px] space-y-1">
                {addErrors.map((err, i) => (
                  <div key={i}>• {err}</div>
                ))}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                onClick={handleAddNewRepo}
                disabled={!newRepoName.includes('/')}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50"
              >
                Add Repository
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
