import React from 'react';
import {
  PlayCircle,
  Search,
  FolderGit2,
  Lock,
  Wifi,
  FileText,
  FileCode2,
} from 'lucide-react';

export type TabId =
  | 'pipeline'
  | 'discovery'
  | 'connectivity'
  | 'repositories'
  | 'policy'
  | 'audit'
  | 'files';

interface TabsNavProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  trippedCount: number;
}

export const TabsNav: React.FC<TabsNavProps> = ({
  activeTab,
  onTabChange,
  trippedCount,
}) => {
  const tabs = [
    { id: 'pipeline' as TabId, label: 'Pipeline Runner', icon: PlayCircle },
    { id: 'discovery' as TabId, label: 'Task Discovery', icon: Search },
    { id: 'connectivity' as TabId, label: 'GitHub Connectivity', icon: Wifi },
    { id: 'repositories' as TabId, label: 'Authorized Repos', icon: FolderGit2 },
    { id: 'policy' as TabId, label: 'Security Policy', icon: Lock },
    {
      id: 'audit' as TabId,
      label: 'Runs & State',
      icon: FileText,
      badge: trippedCount > 0 ? `${trippedCount} tripped` : undefined,
    },
    { id: 'files' as TabId, label: 'Workspace Files', icon: FileCode2 },
  ];

  return (
    <nav className="border-b border-slate-800 bg-slate-900/50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex space-x-1 sm:space-x-2 overflow-x-auto py-2 no-scrollbar">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs sm:text-sm font-medium transition-all whitespace-nowrap ${
                  isActive
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                }`}
              >
                <Icon className={`h-4 w-4 ${isActive ? 'text-emerald-400' : 'text-slate-400'}`} />
                <span>{tab.label}</span>
                {tab.badge && (
                  <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
};
