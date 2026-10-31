import React, { useState } from 'react';
import {
  FileCode2,
  FilePlus,
  RotateCcw,
  Save,
  Sparkles,
  ShieldAlert,
  HelpCircle,
  FileText,
} from 'lucide-react';
import { DailyGreenConfig, VirtualFile } from '../types';
import { INITIAL_VIRTUAL_FILES } from '../data/defaultConfig';

interface VirtualFilesTabProps {
  config: DailyGreenConfig;
  virtualFiles: Record<string, VirtualFile[]>;
  onUpdateFiles: (repo: string, files: VirtualFile[]) => void;
  selectedRepoName: string;
  onSelectRepo: (name: string) => void;
}

export const VirtualFilesTab: React.FC<VirtualFilesTabProps> = ({
  config,
  virtualFiles,
  onUpdateFiles,
  selectedRepoName,
  onSelectRepo,
}) => {
  const repoFiles = virtualFiles[selectedRepoName] || [];
  const [selectedFilePath, setSelectedFilePath] = useState<string>(
    repoFiles[0]?.path || ''
  );
  const [currentContent, setCurrentContent] = useState<string>(
    repoFiles.find((f) => f.path === selectedFilePath)?.content || ''
  );
  const [saveNotice, setSaveNotice] = useState(false);

  const handleSelectFile = (path: string) => {
    setSelectedFilePath(path);
    const file = repoFiles.find((f) => f.path === path);
    setCurrentContent(file?.content || '');
  };

  const handleSaveContent = () => {
    const updated = repoFiles.map((f) =>
      f.path === selectedFilePath ? { ...f, content: currentContent } : f
    );
    onUpdateFiles(selectedRepoName, updated);
    setSaveNotice(true);
    setTimeout(() => setSaveNotice(false), 2000);
  };

  const handleInjectTypo = () => {
    const injected = currentContent + '\n\nWe need to recieve teh updated artifacts for seperate validation.\n';
    setCurrentContent(injected);
  };

  const handleInjectBrokenLink = () => {
    const injected = currentContent + '\n\nRefer to [Broken Guide](docs/non-existent-file.md) for details.\n';
    setCurrentContent(injected);
  };

  const handleInjectTrailingWhitespace = () => {
    const injected = currentContent + '\nTrailing whitespace line with spaces at end.    \nAnother unformatted line with tabs. \t\n';
    setCurrentContent(injected);
  };

  const handleInjectSecret = () => {
    const injected = currentContent + '\n# WARNING TEST: AKIAIOSFODNN7EXAMPLE\n';
    setCurrentContent(injected);
  };

  const handleResetRepoFiles = () => {
    if (INITIAL_VIRTUAL_FILES[selectedRepoName]) {
      const resetFiles = INITIAL_VIRTUAL_FILES[selectedRepoName].map((f) => ({ ...f }));
      onUpdateFiles(selectedRepoName, resetFiles);
      setSelectedFilePath(resetFiles[0]?.path || '');
      setCurrentContent(resetFiles[0]?.content || '');
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <FileCode2 className="h-5 w-5 text-emerald-400" />
            <span>Workspace File Sandbox</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Simulate repository documentation files. Inject common issues or secrets to observe how DailyGreen rules and Quality Gates respond.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedRepoName}
            onChange={(e) => {
              onSelectRepo(e.target.value);
              const files = virtualFiles[e.target.value] || [];
              setSelectedFilePath(files[0]?.path || '');
              setCurrentContent(files[0]?.content || '');
            }}
            className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-2 font-mono"
          >
            {config.repos.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>

          <button
            onClick={handleResetRepoFiles}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-750 text-slate-300 text-xs font-semibold border border-slate-700"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>Reset Files</span>
          </button>
        </div>
      </div>

      {/* Editor & Injectors */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* File Navigator & Test Triggers */}
        <div className="space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Files in {selectedRepoName.split('/')[1]}
            </h3>
            <div className="space-y-1">
              {repoFiles.map((f) => {
                const isSelected = f.path === selectedFilePath;
                return (
                  <button
                    key={f.path}
                    onClick={() => handleSelectFile(f.path)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs font-mono transition-all flex items-center gap-2 ${
                      isSelected
                        ? 'bg-slate-800 text-emerald-400 font-bold border border-emerald-500/30'
                        : 'text-slate-400 hover:bg-slate-850 hover:text-slate-200'
                    }`}
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{f.path}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Test Problem Inserters */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2.5">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
              <span>Simulate Issue Scenarios</span>
            </h3>

            <div className="space-y-2 text-xs">
              <button
                onClick={handleInjectTypo}
                className="w-full text-left p-2 rounded-lg bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 transition-all"
              >
                <div className="font-semibold text-emerald-400 text-[11px] mb-0.5">
                  + Add Common Typos
                </div>
                <div className="text-[10px] text-slate-500">
                  Inserts &apos;teh&apos;, &apos;recieve&apos;, and &apos;seperate&apos;
                </div>
              </button>

              <button
                onClick={handleInjectBrokenLink}
                className="w-full text-left p-2 rounded-lg bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 transition-all"
              >
                <div className="font-semibold text-emerald-400 text-[11px] mb-0.5">
                  + Add Broken Doc Link
                </div>
                <div className="text-[10px] text-slate-500">
                  Inserts Markdown link to non-existent file
                </div>
              </button>

              <button
                onClick={handleInjectTrailingWhitespace}
                className="w-full text-left p-2 rounded-lg bg-slate-950 hover:bg-slate-850 border border-slate-800 text-slate-300 transition-all"
              >
                <div className="font-semibold text-emerald-400 text-[11px] mb-0.5">
                  + Add Trailing Whitespace
                </div>
                <div className="text-[10px] text-slate-500">
                  Inserts unformatted lines and spaces at EOF
                </div>
              </button>

              <button
                onClick={handleInjectSecret}
                className="w-full text-left p-2 rounded-lg bg-rose-950/20 hover:bg-rose-950/40 border border-rose-500/20 text-slate-300 transition-all"
              >
                <div className="font-semibold text-rose-400 text-[11px] mb-0.5 flex items-center gap-1">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  <span>+ Test Secret Violation</span>
                </div>
                <div className="text-[10px] text-slate-400">
                  Inserts an AWS access key pattern to test the Quality Gate secret blocker!
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* Text Area File Editor */}
        <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs font-bold text-slate-200">
              {selectedFilePath || 'No file selected'}
            </span>

            <div className="flex items-center gap-2">
              {saveNotice && (
                <span className="text-xs text-emerald-400 font-semibold animate-fade-in">
                  Saved to workspace!
                </span>
              )}
              <button
                onClick={handleSaveContent}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-all shadow"
              >
                <Save className="h-3.5 w-3.5" />
                <span>Save Changes</span>
              </button>
            </div>
          </div>

          <textarea
            value={currentContent}
            onChange={(e) => setCurrentContent(e.target.value)}
            rows={18}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3.5 text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500 leading-relaxed resize-y"
            placeholder="File content..."
          />
        </div>
      </div>
    </div>
  );
};
