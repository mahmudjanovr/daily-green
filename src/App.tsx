import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { TabId, TabsNav } from './components/TabsNav';
import { PipelineTab } from './components/PipelineTab';
import { DiscoveryTab } from './components/DiscoveryTab';
import { ConnectivityTab } from './components/ConnectivityTab';
import { RepositoriesTab } from './components/RepositoriesTab';
import { SecurityPolicyTab } from './components/SecurityPolicyTab';
import { AuditReportTab } from './components/AuditReportTab';
import { VirtualFilesTab } from './components/VirtualFilesTab';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DEFAULT_CONFIG, INITIAL_VIRTUAL_FILES } from './data/defaultConfig';
import { DailyGreenConfig, RepoConfig, RunReport, SecurityPolicyConfig, VirtualFile } from './types';
import { StateManager } from './services/stateManager';

export const App: React.FC = () => {
  const [config, setConfig] = useState<DailyGreenConfig>(() => {
    try {
      const saved = localStorage.getItem('dailygreen_config_v1');
      if (saved) return JSON.parse(saved);
    } catch {}
    return DEFAULT_CONFIG;
  });

  const [stateMgr] = useState<StateManager>(() => new StateManager());
  const [activeTab, setActiveTab] = useState<TabId>('pipeline');
  const [selectedRepoName, setSelectedRepoName] = useState<string>(
    config.repos[0]?.name || 'example-org/astro-portfolio'
  );

  const [virtualFiles, setVirtualFiles] = useState<Record<string, VirtualFile[]>>(() => {
    try {
      const saved = localStorage.getItem('dailygreen_virtual_files_v1');
      if (saved) return JSON.parse(saved);
    } catch {}
    return INITIAL_VIRTUAL_FILES;
  });

  // GitHub credential is strictly in-memory per session. Never saved to localStorage.
  const [githubToken, setGithubToken] = useState<string>('');

  useEffect(() => {
    // Purge any legacy token from localStorage to guarantee credential isolation
    try {
      localStorage.removeItem('dailygreen_gh_token');
    } catch {}
  }, []);

  const [stateVersion, setStateVersion] = useState<number>(0);

  // Save config changes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('dailygreen_config_v1', JSON.stringify(config));
    } catch {}
  }, [config]);

  // Save virtual files changes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('dailygreen_virtual_files_v1', JSON.stringify(virtualFiles));
    } catch {}
  }, [virtualFiles]);

  const handleToggleEnabled = () => {
    setConfig((prev) => ({ ...prev, enabled: !prev.enabled }));
  };

  const handleToggleDryRun = () => {
    setConfig((prev) => ({ ...prev, dry_run: !prev.dry_run }));
  };

  const handleToggleLiveMutations = () => {
    setConfig((prev) => ({ ...prev, allow_live_mutations: !prev.allow_live_mutations }));
  };

  const handleUpdatePolicy = (newPolicy: SecurityPolicyConfig) => {
    setConfig((prev) => ({ ...prev, policy: newPolicy }));
  };

  const handleUpdateRepo = (updated: RepoConfig) => {
    setConfig((prev) => ({
      ...prev,
      repos: prev.repos.map((r) => (r.name === updated.name ? updated : r)),
    }));
  };

  const handleAddRepo = (newRepo: RepoConfig) => {
    setConfig((prev) => ({
      ...prev,
      repos: [...prev.repos, newRepo],
    }));
    // initialize virtual files for new repo
    if (!virtualFiles[newRepo.name]) {
      setVirtualFiles((prev) => ({
        ...prev,
        [newRepo.name]: [
          {
            path: 'README.md',
            content: `# ${newRepo.name}\n\nAutomated maintenance managed by DailyGreen.\n`,
          },
        ],
      }));
    }
  };

  const handleDeleteRepo = (name: string) => {
    setConfig((prev) => ({
      ...prev,
      repos: prev.repos.filter((r) => r.name !== name),
    }));
    if (selectedRepoName === name) {
      setSelectedRepoName(config.repos.find((r) => r.name !== name)?.name || '');
    }
  };

  const handleUpdateFiles = (repo: string, files: VirtualFile[]) => {
    setVirtualFiles((prev) => ({
      ...prev,
      [repo]: files,
    }));
  };

  const handleRunCompleted = (report: RunReport) => {
    setStateVersion((v) => v + 1);
  };

  const handleUpdateGithubToken = (tok: string) => {
    // Keep in-memory for the current session only
    setGithubToken(tok);
  };

  const activeLeasesCount = Object.keys(stateMgr.getState().active_leases || {}).length;
  const trippedCount = Object.values(stateMgr.getState().circuit_tripped || {}).filter(Boolean).length;

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
        <Header
          config={config}
          onToggleEnabled={handleToggleEnabled}
          onToggleDryRun={handleToggleDryRun}
          onToggleLiveMutations={handleToggleLiveMutations}
          activeLeasesCount={activeLeasesCount}
        />

        <TabsNav
          activeTab={activeTab}
          onTabChange={setActiveTab}
          trippedCount={trippedCount}
        />

        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {activeTab === 'pipeline' && (
            <PipelineTab
              config={config}
              stateMgr={stateMgr}
              virtualFiles={virtualFiles}
              onUpdateFiles={handleUpdateFiles}
              onRunCompleted={handleRunCompleted}
              selectedRepoName={selectedRepoName}
              onSelectRepo={setSelectedRepoName}
            />
          )}

          {activeTab === 'discovery' && (
            <DiscoveryTab
              config={config}
              stateMgr={stateMgr}
              virtualFiles={virtualFiles}
              selectedRepoName={selectedRepoName}
              onSelectRepo={setSelectedRepoName}
              onSelectTaskForPipeline={(repo) => {
                setSelectedRepoName(repo);
                setActiveTab('pipeline');
              }}
            />
          )}

          {activeTab === 'connectivity' && (
            <ConnectivityTab
              config={config}
              githubToken={githubToken}
              onUpdateGithubToken={handleUpdateGithubToken}
            />
          )}

          {activeTab === 'repositories' && (
            <RepositoriesTab
              config={config}
              onUpdateRepo={handleUpdateRepo}
              onAddRepo={handleAddRepo}
              onDeleteRepo={handleDeleteRepo}
            />
          )}

          {activeTab === 'policy' && (
            <SecurityPolicyTab
              config={config}
              onUpdatePolicy={handleUpdatePolicy}
              onToggleKillSwitch={handleToggleEnabled}
              onToggleDryRun={handleToggleDryRun}
            />
          )}

          {activeTab === 'audit' && (
            <AuditReportTab
              config={config}
              stateMgr={stateMgr}
              onRefresh={() => setStateVersion((v) => v + 1)}
            />
          )}

          {activeTab === 'files' && (
            <VirtualFilesTab
              config={config}
              virtualFiles={virtualFiles}
              onUpdateFiles={handleUpdateFiles}
              selectedRepoName={selectedRepoName}
              onSelectRepo={setSelectedRepoName}
            />
          )}
        </main>

        <footer className="border-t border-slate-800/80 bg-slate-900/60 py-4 text-center text-xs text-slate-500">
          <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
            <span>DailyGreen Automated Maintenance & Quality Gate Harness</span>
            <span>Rules-first • Mandatory Quality Gate • Cryptographic SHA-256 Patch Seal</span>
          </div>
        </footer>
      </div>
    </ErrorBoundary>
  );
};
