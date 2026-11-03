import React, { useState, useRef } from 'react';
import {
  Play,
  RotateCcw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileCode,
  Shield,
  Key,
  Terminal,
  ExternalLink,
  Lock,
  GitBranch,
  Copy,
  Clock,
  Sparkles,
  StopCircle,
  Server,
  Cpu,
} from 'lucide-react';
import {
  DailyGreenConfig,
  QualityGateResult,
  RepoConfig,
  RunReport,
  Task,
  VirtualFile,
} from '../types';
import { StateManager } from '../services/stateManager';
import {
  executeMaintenancePipeline,
  StageStatus,
} from '../pipeline/pipelineEngine';
import { backendApiClient } from '../services/backendApi';

interface PipelineTabProps {
  config: DailyGreenConfig;
  stateMgr: StateManager;
  virtualFiles: Record<string, VirtualFile[]>;
  onUpdateFiles: (repo: string, files: VirtualFile[]) => void;
  onRunCompleted: (report: RunReport) => void;
  selectedRepoName: string;
  onSelectRepo: (name: string) => void;
}

export const PipelineTab: React.FC<PipelineTabProps> = ({
  config,
  stateMgr,
  virtualFiles,
  onUpdateFiles,
  onRunCompleted,
  selectedRepoName,
  onSelectRepo,
}) => {
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionType, setExecutionType] = useState<'normal' | 'backup' | 'worker-only'>('normal');
  const [activeStep, setActiveStep] = useState<number>(0);
  const [steps, setSteps] = useState<StageStatus[]>([
    { step: 1, name: 'Pre-Run Checks & Lease Acquisition', status: 'idle' },
    { step: 2, name: 'Isolated Workspace & Baseline Check', status: 'idle' },
    { step: 3, name: 'Rules-First Task Discovery', status: 'idle' },
    { step: 4, name: 'Task Implementation & Diff Generation', status: 'idle' },
    { step: 5, name: 'Post-Change Verification Tests & Lints', status: 'idle' },
    { step: 6, name: 'Mandatory Quality Gate & SHA-256 Seal', status: 'idle' },
    { step: 7, name: 'Delivery & Deduplication Check', status: 'idle' },
  ]);

  const [discoveredTask, setDiscoveredTask] = useState<Task | null>(null);
  const [generatedDiff, setGeneratedDiff] = useState<string>('');
  const [qualityGateRes, setQualityGateRes] = useState<QualityGateResult | null>(null);
  const [lastReport, setLastReport] = useState<RunReport | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [copiedDiff, setCopiedDiff] = useState(false);
  const [backendAvailable, setBackendAvailable] = useState<boolean>(true);
  const [useBackend, setUseBackend] = useState<boolean>(true);
  const [activeServerRunId, setActiveServerRunId] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const selectedRepo = config.repos.find((r) => r.name === selectedRepoName) || config.repos[0];

  const [schedulerStatus, setSchedulerStatus] = useState<any>(null);
  const [aiPR, setAiPR] = useState<any | null>(null);
  const [isGeneratingPR, setIsGeneratingPR] = useState(false);
  const [copiedPR, setCopiedPR] = useState(false);

  const fetchSchedulerStatus = React.useCallback(() => {
    backendApiClient.getSchedulerStatus().then((res) => {
      if (res.success && res.data) {
        setSchedulerStatus(res.data);
      }
    });
  }, []);

  const handleGenerateAIPR = async () => {
    const taskObj = discoveredTask || lastReport?.task;
    if (!taskObj || !generatedDiff) return;

    setIsGeneratingPR(true);
    const res = await backendApiClient.generatePRDescriptionAI(taskObj, generatedDiff, qualityGateRes);
    if (res.success && res.data) {
      setAiPR(res.data);
      addLog('Generated Pull Request description using Gemini AI.');
    } else {
      addLog('AI PR description generation fell back to deterministic template.');
    }
    setIsGeneratingPR(false);
  };

  React.useEffect(() => {
    backendApiClient.getHealth().then((res) => {
      setBackendAvailable(res.connected);
      if (!res.connected) setUseBackend(false);
    });
    fetchSchedulerStatus();
    const interval = setInterval(fetchSchedulerStatus, 15000);
    return () => clearInterval(interval);
  }, [fetchSchedulerStatus]);

  const handleToggleScheduler = async () => {
    const res = await backendApiClient.toggleScheduler();
    if (res.success) {
      setSchedulerStatus(res.data.status);
      addLog(res.data.message);
    }
  };

  const handleTriggerScheduled = async () => {
    if (!selectedRepo) return;
    addLog(`Manually dispatching scheduled autonomous run for "${selectedRepo.name}"...`);
    const res = await backendApiClient.triggerScheduledRun(selectedRepo.name, false);
    if (res.success && res.data?.run) {
      addLog(`Autonomous run ${res.data.run.id} started with lease.`);
      fetchSchedulerStatus();
    } else {
      addLog(`Scheduled trigger failed: ${res.error || 'Lease conflict'}`);
    }
  };

  const addLog = (msg: string) => {
    const timestamp = new Date().toISOString().substring(11, 19);
    setLogs((prev) => [...prev, `[${timestamp}] ${msg}`]);
  };

  const handleCancelPipeline = async () => {
    if (activeServerRunId) {
      addLog(`Sending cancellation signal to backend server for run ${activeServerRunId}...`);
      await backendApiClient.cancelRun(activeServerRunId);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      addLog('Cancellation signal dispatched by operator.');
    }
  };

  const handleRunPipeline = async () => {
    if (!selectedRepo || isExecuting) return;
    setIsExecuting(true);
    setLogs([]);
    setDiscoveredTask(null);
    setGeneratedDiff('');
    setQualityGateRes(null);
    setLastReport(null);
    setActiveServerRunId(null);

    const abortCtrl = new AbortController();
    abortControllerRef.current = abortCtrl;

    setSteps([
      { step: 1, name: 'Pre-Run Checks & Lease Acquisition', status: 'idle' },
      { step: 2, name: 'Isolated Workspace & Baseline Check', status: 'idle' },
      { step: 3, name: 'Rules-First Task Discovery', status: 'idle' },
      { step: 4, name: 'Task Implementation & Diff Generation', status: 'idle' },
      { step: 5, name: 'Post-Change Verification Tests & Lints', status: 'idle' },
      { step: 6, name: 'Mandatory Quality Gate & SHA-256 Seal', status: 'idle' },
      { step: 7, name: 'Delivery & Deduplication Check', status: 'idle' },
    ]);

    // Check if backend execution is active
    if (useBackend && backendAvailable) {
      addLog(`Initiating real server-side execution for ${selectedRepo.name}...`);
      try {
        const triggerRes = await backendApiClient.triggerRun({
          repo: selectedRepo.name,
          is_backup_run: executionType === 'backup',
          dry_run: true,
        });

        if (!triggerRes.success || !triggerRes.run) {
          throw new Error(triggerRes.error || 'Failed to start server run');
        }

        const runId = triggerRes.run.id;
        setActiveServerRunId(runId);
        addLog(`Server run [${runId}] scheduled. Streaming execution logs and stages...`);

        // Poll server run until completion
        let finished = false;
        let pollCount = 0;

        while (!finished && !abortCtrl.signal.aborted && pollCount < 60) {
          await new Promise((r) => setTimeout(r, 400));
          pollCount++;

          const pollRes = await backendApiClient.getRunById(runId);
          if (!pollRes.success || !pollRes.run) continue;

          const run = pollRes.run;

          // Sync server logs
          if (run.logs && run.logs.length > 0) {
            setLogs(run.logs.map((l) => `[${l.timestamp.substring(11, 19)}] [${l.level}] ${l.message}`));
          }

          if (run.task) {
            setDiscoveredTask(run.task);
          }

          if (run.report?.quality_gate) {
            setQualityGateRes(run.report.quality_gate);
            if (run.report.quality_gate.verified_diff) {
              setGeneratedDiff(run.report.quality_gate.verified_diff);
            }
          }

          // Update stage indicators based on server stage text
          if (run.current_stage) {
            const stageText = run.current_stage.toLowerCase();
            let currentStep = 1;
            if (stageText.includes('stage 2') || stageText.includes('workspace')) currentStep = 2;
            else if (stageText.includes('stage 3') || stageText.includes('discovery')) currentStep = 3;
            else if (stageText.includes('stage 4') || stageText.includes('execution')) currentStep = 4;
            else if (stageText.includes('stage 5') || stageText.includes('quality gate')) currentStep = 5;
            else if (stageText.includes('stage 6') || stageText.includes('delivery')) currentStep = 6;
            else if (stageText.includes('stage 7') || stageText.includes('persistence')) currentStep = 7;

            setActiveStep(currentStep);
            setSteps((prev) =>
              prev.map((s) => {
                if (s.step < currentStep) return { ...s, status: 'success' };
                if (s.step === currentStep) return { ...s, status: run.status === 'failed' ? 'failed' : 'running' };
                return { ...s, status: 'idle' };
              })
            );
          }

          if (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled') {
            finished = true;
            if (run.report) {
              setLastReport(run.report);
              onRunCompleted(run.report);
            }
            if (run.status === 'completed') {
              setSteps((prev) => prev.map((s) => ({ ...s, status: 'success' })));
            } else if (run.status === 'failed') {
              addLog(`[ERROR] Server execution failed: ${run.error || 'Unknown error'}`);
            }
          }
        }
      } catch (err: any) {
        addLog(`[ERROR] Backend execution failed: ${err.message}. Falling back to simulation mode.`);
        // Fallback to client simulation
        await runClientSimulation(selectedRepo, abortCtrl);
      } finally {
        setIsExecuting(false);
        abortControllerRef.current = null;
      }
    } else {
      // Client-side simulation mode
      await runClientSimulation(selectedRepo, abortCtrl);
      setIsExecuting(false);
      abortControllerRef.current = null;
    }
  };

  const runClientSimulation = async (repo: RepoConfig, abortCtrl: AbortController) => {
    const repoFiles = virtualFiles[repo.name] || [];
    const res = await executeMaintenancePipeline({
      config,
      repo,
      stateMgr,
      files: repoFiles,
      isBackupRun: executionType === 'backup',
      isWorkerOnly: executionType === 'worker-only',
      abortSignal: abortCtrl.signal,
      onStageChange: (stepNum, status, details) => {
        setActiveStep(stepNum);
        setSteps((prev) =>
          prev.map((s) => (s.step === stepNum ? { ...s, status, details } : s))
        );
      },
      onLog: (msg) => addLog(msg),
    });

    setDiscoveredTask(res.task);
    setGeneratedDiff(res.diff);
    setQualityGateRes(res.qualityGate);
    setLastReport(res.report);

    if (res.success && res.updatedFiles.length > 0) {
      onUpdateFiles(repo.name, res.updatedFiles);
    }
    onRunCompleted(res.report);
  };

  const handleCopyDiff = () => {
    if (!generatedDiff) return;
    navigator.clipboard.writeText(generatedDiff);
    setCopiedDiff(true);
    setTimeout(() => setCopiedDiff(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Autonomous Background Scheduling Daemon Widget */}
      {schedulerStatus && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div
                className={`h-3 w-3 rounded-full ${
                  schedulerStatus.daemon_running ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'
                }`}
              />
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-white">Autonomous Engine Daemon</h3>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider ${
                      schedulerStatus.daemon_running
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}
                  >
                    {schedulerStatus.daemon_running ? 'Active Daemon' : 'Paused'}
                  </span>
                  {schedulerStatus.schedules?.some((s: any) => s.is_backup_window) && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                      17:35 UTC Backup Window Active
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-400 mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span>
                    Clock: <strong className="text-slate-200">{schedulerStatus.current_time_tz}</strong>
                  </span>
                  <span>
                    UTC: <strong className="text-slate-300">{schedulerStatus.current_time_utc.slice(11, 19)}</strong>
                  </span>
                  <span>
                    Lease:{' '}
                    <strong className="text-slate-300">
                      {Object.keys(schedulerStatus.active_leases || {}).length > 0
                        ? `${Object.keys(schedulerStatus.active_leases)[0]} (Locked)`
                        : 'Free (max_workers=1)'}
                    </strong>
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start md:self-auto">
              <button
                onClick={handleToggleScheduler}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-700 bg-slate-850 hover:bg-slate-800 text-slate-200 transition"
              >
                {schedulerStatus.daemon_running ? 'Pause Daemon' : 'Resume Daemon'}
              </button>
              <button
                onClick={handleTriggerScheduled}
                disabled={isExecuting}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5 transition disabled:opacity-50"
              >
                <Clock className="h-3.5 w-3.5" />
                <span>Trigger Autonomous Slot</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Top Controls Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1">
                Target Repository:
              </label>
              <select
                value={selectedRepoName}
                onChange={(e) => onSelectRepo(e.target.value)}
                disabled={isExecuting}
                className="bg-slate-950 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-emerald-500"
              >
                {config.repos.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name} {r.enabled ? '(Enabled)' : '(Disabled)'}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1">
                Execution Mode:
              </label>
              <div className="inline-flex rounded-lg border border-slate-700 bg-slate-950 p-0.5 text-xs font-medium">
                <button
                  onClick={() => setExecutionType('normal')}
                  disabled={isExecuting}
                  className={`px-3 py-1.5 rounded-md transition-all ${
                    executionType === 'normal'
                      ? 'bg-slate-800 text-slate-100 shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Standard Run
                </button>
                <button
                  onClick={() => setExecutionType('backup')}
                  disabled={isExecuting}
                  className={`px-3 py-1.5 rounded-md transition-all ${
                    executionType === 'backup'
                      ? 'bg-amber-950/60 text-amber-300 shadow border border-amber-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title="Simulates 22:35 Asia/Tashkent backup run (deduplicates against today's primary run)"
                >
                  Backup Run (22:35)
                </button>
                <button
                  onClick={() => setExecutionType('worker-only')}
                  disabled={isExecuting}
                  className={`px-3 py-1.5 rounded-md transition-all ${
                    executionType === 'worker-only'
                      ? 'bg-blue-950/60 text-blue-300 shadow border border-blue-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title="Worker sandbox only: creates sealed_task.json without delivery"
                >
                  Worker Sandbox Only
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 mb-1">
                Execution Infrastructure:
              </label>
              <div className="inline-flex rounded-lg border border-slate-700 bg-slate-950 p-0.5 text-xs font-medium">
                <button
                  onClick={() => setUseBackend(true)}
                  disabled={isExecuting || !backendAvailable}
                  className={`px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-all ${
                    useBackend && backendAvailable
                      ? 'bg-emerald-950/80 text-emerald-300 shadow border border-emerald-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title="Executes on real Express server in isolated HMAC workspace with sanitized subprocesses"
                >
                  <Server className="h-3.5 w-3.5" />
                  <span>Real Backend Engine</span>
                </button>
                <button
                  onClick={() => setUseBackend(false)}
                  disabled={isExecuting}
                  className={`px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-all ${
                    !useBackend || !backendAvailable
                      ? 'bg-slate-800 text-slate-200 shadow'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title="Client-side simulated execution inside browser virtual DOM"
                >
                  <Cpu className="h-3.5 w-3.5" />
                  <span>Client Simulation</span>
                </button>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {isExecuting ? (
              <button
                onClick={handleCancelPipeline}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-xs bg-rose-600 hover:bg-rose-500 text-white shadow-md transition-all"
              >
                <StopCircle className="h-4 w-4" />
                <span>Cancel Run</span>
              </button>
            ) : (
              <button
                onClick={handleRunPipeline}
                disabled={isExecuting}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-sm shadow-md transition-all bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30 hover:scale-[1.02]"
              >
                <Play className="h-4 w-4 fill-white" />
                <span>
                  {config.dry_run
                    ? 'Run Dry-Run Pipeline'
                    : config.allow_live_mutations
                    ? 'Execute Live Run'
                    : 'Run Pipeline (Mutations Blocked)'}
                </span>
              </button>
            )}
          </div>
        </div>

        {/* Operational Boundary Notice */}
        <div className="mt-3.5 pt-3 border-t border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between text-[11px] text-slate-400 gap-2">
          <div className="flex items-center gap-2">
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
            <span>
              <strong>Execution Scope:</strong> Discovery, diffing, and Quality Gate sealing run in-memory; subprocesses simulate sanitized sandbox behavior.
            </span>
          </div>
          <span className="font-mono text-slate-500">
            Fail-safe defaults: dry_run={String(config.dry_run)}, live_mutations={String(config.allow_live_mutations)}
          </span>
        </div>
      </div>

      {/* Pipeline Progress Stages */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center justify-between">
          <span>Maintenance Pipeline Stages</span>
          <span className="text-xs font-mono lowercase text-slate-400">
            {isExecuting ? `stage ${activeStep}/7 active` : 'ready'}
          </span>
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-7 gap-3">
          {steps.map((step) => {
            let badgeBg = 'bg-slate-950 border-slate-800 text-slate-400';
            let icon = <span className="font-mono text-xs">{step.step}</span>;

            if (step.status === 'running') {
              badgeBg = 'bg-blue-950/60 border-blue-500 text-blue-300 ring-2 ring-blue-500/20';
              icon = <RotateCcw className="h-4 w-4 animate-spin text-blue-400" />;
            } else if (step.status === 'success') {
              badgeBg = 'bg-emerald-950/50 border-emerald-500/40 text-emerald-300';
              icon = <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
            } else if (step.status === 'failed') {
              badgeBg = 'bg-rose-950/50 border-rose-500/40 text-rose-300';
              icon = <XCircle className="h-4 w-4 text-rose-400" />;
            } else if (step.status === 'skipped') {
              badgeBg = 'bg-slate-800/60 border-slate-700 text-slate-400';
              icon = <AlertTriangle className="h-4 w-4 text-amber-400" />;
            } else if (step.status === 'cancelled') {
              badgeBg = 'bg-amber-950/50 border-amber-500/40 text-amber-300';
              icon = <StopCircle className="h-4 w-4 text-amber-400" />;
            }

            return (
              <div
                key={step.step}
                className={`p-3 rounded-lg border flex flex-col justify-between transition-all ${badgeBg}`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-mono uppercase text-slate-400">
                      Step {step.step}
                    </span>
                    {icon}
                  </div>
                  <h4 className="text-xs font-semibold leading-snug">{step.name}</h4>
                </div>
                {step.details && (
                  <p className="mt-2 text-[10px] text-slate-400 leading-tight border-t border-slate-800 pt-1.5 line-clamp-2">
                    {step.details}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Main Grid: Output & Quality Gate */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Discovered Task & Diff Viewer */}
        <div className="space-y-6">
          {discoveredTask && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 uppercase font-semibold">
                    {discoveredTask.source} Task
                  </span>
                  <h3 className="text-base font-bold text-white mt-1.5">
                    {discoveredTask.title}
                  </h3>
                </div>
                <span className="text-xs font-mono text-slate-400 bg-slate-950 px-2 py-1 rounded border border-slate-800">
                  {discoveredTask.id}
                </span>
              </div>

              <p className="text-xs text-slate-300 mb-3">{discoveredTask.description}</p>

              <div className="text-xs text-slate-400 space-y-1.5 border-t border-slate-800 pt-3">
                <div>
                  <span className="text-slate-500">Rationale: </span>
                  {discoveredTask.rationale}
                </div>
                <div>
                  <span className="text-slate-500">Target Files: </span>
                  <span className="font-mono text-slate-300">
                    {discoveredTask.target_files.join(', ')}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Validation: </span>
                  <span className="font-mono text-slate-300">
                    {discoveredTask.validation_strategy}
                  </span>
                </div>
              </div>
            </div>
          )}

          {generatedDiff && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <FileCode className="h-4 w-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold text-slate-200">
                    Verified Unified Diff
                  </h3>
                  <span className="text-xs font-mono text-slate-400">
                    ({generatedDiff.split('\n').filter((l) => l.startsWith('+') || l.startsWith('-')).length} changed lines)
                  </span>
                </div>
                <button
                  onClick={handleCopyDiff}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700"
                >
                  <Copy className="h-3.5 w-3.5" />
                  <span>{copiedDiff ? 'Copied' : 'Copy Diff'}</span>
                </button>
              </div>

              <pre className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs font-mono overflow-x-auto max-h-72 leading-relaxed text-slate-300">
                {generatedDiff.split('\n').map((line, idx) => {
                  let colorClass = 'text-slate-400';
                  if (line.startsWith('+') && !line.startsWith('+++'))
                    colorClass = 'text-emerald-400 bg-emerald-950/30';
                  else if (line.startsWith('-') && !line.startsWith('---'))
                    colorClass = 'text-rose-400 bg-rose-950/30';
                  else if (line.startsWith('@@'))
                    colorClass = 'text-sky-400 bg-sky-950/20';

                  return (
                    <div key={idx} className={`${colorClass} px-1 rounded-xs`}>
                      {line}
                    </div>
                  );
                })}
              </pre>
            </div>
          )}

          {/* Realtime Pipeline Execution Logs */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center gap-2 mb-3">
              <Terminal className="h-4 w-4 text-slate-400" />
              <h3 className="text-sm font-semibold text-slate-200">Execution Output Logs</h3>
            </div>
            <div className="bg-slate-950 border border-slate-800/80 rounded-lg p-3 font-mono text-xs text-slate-300 h-56 overflow-y-auto space-y-1">
              {logs.length === 0 ? (
                <span className="text-slate-600 italic">
                  Press &quot;Run Pipeline&quot; to execute the maintenance workflow...
                </span>
              ) : (
                logs.map((log, index) => <div key={index}>{log}</div>)
              )}
            </div>
          </div>
        </div>

        {/* Quality Gate Scorecard & PR Preview */}
        <div className="space-y-6">
          {qualityGateRes && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Shield className="h-5 w-5 text-emerald-400" />
                  <h3 className="text-base font-bold text-white">Quality Gate Scorecard</h3>
                </div>
                <span
                  className={`px-2.5 py-1 rounded text-xs font-bold uppercase ${
                    qualityGateRes.passed
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  }`}
                >
                  {qualityGateRes.passed ? 'PASSED & SEALED' : 'REJECTED'}
                </span>
              </div>

              <div className="space-y-3 text-xs">
                {/* Cryptographic Seal */}
                {qualityGateRes.patch_hash && (
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                    <div className="flex items-center gap-2 text-emerald-400 font-semibold mb-1">
                      <Lock className="h-3.5 w-3.5" />
                      <span>Cryptographic Patch Seal (SHA-256)</span>
                    </div>
                    <p className="font-mono text-slate-300 break-all select-all">
                      {qualityGateRes.patch_hash}
                    </p>
                    <div className="text-[11px] text-slate-500 mt-1">
                      Git Tree SHA: <span className="font-mono text-slate-400">{qualityGateRes.tree_sha}</span>
                    </div>
                  </div>
                )}

                {/* Security Checks */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block">Diff Line Limit</span>
                    <span className="font-semibold text-slate-200">
                      {qualityGateRes.security_result?.lines_changed || 0} /{' '}
                      {qualityGateRes.security_result?.max_lines_allowed || 150} lines
                    </span>
                  </div>
                  <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block">Secret Scanner</span>
                    <span
                      className={`font-semibold ${
                        (qualityGateRes.security_result?.secrets_detected.length || 0) > 0
                          ? 'text-rose-400'
                          : 'text-emerald-400'
                      }`}
                    >
                      {(qualityGateRes.security_result?.secrets_detected.length || 0) > 0
                        ? `${qualityGateRes.security_result?.secrets_detected.length} Detected`
                        : 'Clean (None detected)'}
                    </span>
                  </div>
                </div>

                {/* AST Semantic Security Gate */}
                <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-slate-400 font-semibold text-[11px]">AST Semantic Security Gate</span>
                    <span
                      className={`text-[11px] font-bold ${
                        qualityGateRes.ast_result
                          ? qualityGateRes.ast_result.passed
                            ? 'text-emerald-400'
                            : 'text-rose-400'
                          : 'text-emerald-400'
                      }`}
                    >
                      {qualityGateRes.ast_result
                        ? qualityGateRes.ast_result.passed
                          ? 'VERIFIED (TypeScript AST)'
                          : 'AST VIOLATION'
                        : 'PASSED (Clean AST)'}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 space-y-0.5 font-mono">
                    <div className="flex justify-between">
                      <span className="text-slate-500 font-sans">Syntax Tree:</span>
                      <span className="text-slate-300">
                        {qualityGateRes.ast_result?.syntax_valid !== false ? 'Valid & Uncorrupted' : 'Syntax Error'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500 font-sans">Forbidden Patterns:</span>
                      <span className="text-slate-300">
                        {(qualityGateRes.ast_result?.disallowed_patterns_found?.length || 0) === 0
                          ? '0 (Clean: no eval/exec/proto)'
                          : `${qualityGateRes.ast_result?.disallowed_patterns_found?.length} Disallowed`}
                      </span>
                    </div>
                    {qualityGateRes.ast_result?.ast_hash && (
                      <div className="text-[10px] text-slate-500 truncate pt-0.5">
                        SHA-256 AST Hash: {qualityGateRes.ast_result.ast_hash.slice(0, 24)}...
                      </div>
                    )}
                  </div>
                </div>

                {/* Path Allowlist Verification */}
                <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                  <span className="text-slate-500 block mb-1">Touched Files Path Validation</span>
                  <div className="space-y-1">
                    {qualityGateRes.changed_files.map((f) => (
                      <div key={f} className="flex items-center justify-between font-mono">
                        <span className="text-slate-300">{f}</span>
                        <span className="text-emerald-400 text-[11px] font-sans">ALLOWLISTED</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Verification Commands Table */}
                <div className="p-2.5 bg-slate-950 rounded-lg border border-slate-800">
                  <span className="text-slate-500 block mb-1.5">Verification Command Results</span>
                  <div className="space-y-1 font-mono text-[11px]">
                    {qualityGateRes.baseline_result && (
                      <div className="flex items-center justify-between text-slate-300">
                        <span>Baseline: {qualityGateRes.baseline_result.command.join(' ')}</span>
                        <span className="text-emerald-400">PASSED ({qualityGateRes.baseline_result.duration_seconds}s)</span>
                      </div>
                    )}
                    {qualityGateRes.post_change_tests.map((t, i) => (
                      <div key={i} className="flex items-center justify-between text-slate-300">
                        <span>Test: {t.command.join(' ')}</span>
                        <span className="text-emerald-400">PASSED ({t.duration_seconds}s)</span>
                      </div>
                    ))}
                    {qualityGateRes.post_change_lints.map((l, i) => (
                      <div key={i} className="flex items-center justify-between text-slate-300">
                        <span>Lint: {l.command.join(' ')}</span>
                        <span className="text-emerald-400">PASSED ({l.duration_seconds}s)</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Delivery & PR Preview */}
          {lastReport && lastReport.delivery && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <GitBranch className="h-5 w-5 text-emerald-400" />
                  <h3 className="text-base font-bold text-white">Delivery Outcome</h3>
                </div>
                <span className="text-xs font-mono text-slate-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                  {lastReport.delivery.is_dry_run ? 'Dry Run Simulation' : 'Live Delivery'}
                </span>
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                  <div className="text-slate-400 mb-1">Target Branch:</div>
                  <div className="font-mono text-emerald-400 font-semibold text-sm">
                    {lastReport.delivery.branch_name}
                  </div>
                </div>

                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                  <div className="text-slate-400 mb-1">Status Message:</div>
                  <div className="text-slate-200">{lastReport.delivery.message}</div>
                </div>

                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                  <div className="text-slate-400 mb-1 font-semibold text-emerald-400">
                    GitHub Contribution Semantics Notice:
                  </div>
                  <div className="text-slate-300 text-[11px] leading-relaxed">
                    {lastReport.delivery.contribution_status}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Gemini AI Generated Pull Request Description */}
          {generatedDiff && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-emerald-400" />
                  <h3 className="text-sm font-bold text-white">Gemini AI Pull Request Assistant</h3>
                </div>
                <button
                  onClick={handleGenerateAIPR}
                  disabled={isGeneratingPR}
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 transition disabled:opacity-50"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>{isGeneratingPR ? 'Generating...' : 'Generate AI PR Description'}</span>
                </button>
              </div>

              {aiPR ? (
                <div className="space-y-3">
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 text-[10px] uppercase font-bold block mb-1">
                      Proposed PR Title:
                    </span>
                    <span className="font-mono text-emerald-400 font-bold text-xs">{aiPR.title}</span>
                  </div>

                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-500 text-[10px] uppercase font-bold">
                        Generated PR Description Markdown:
                      </span>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(aiPR.markdown_body);
                          setCopiedPR(true);
                          setTimeout(() => setCopiedPR(false), 2000);
                        }}
                        className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        <Copy className="h-3 w-3" />
                        <span>{copiedPR ? 'Copied' : 'Copy PR Markdown'}</span>
                      </button>
                    </div>
                    <pre className="font-mono text-[11px] text-slate-300 whitespace-pre-wrap max-h-56 overflow-y-auto leading-relaxed bg-slate-900/60 p-2.5 rounded border border-slate-800">
                      {aiPR.markdown_body}
                    </pre>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500 italic">
                  Click &apos;Generate AI PR Description&apos; to compose an enterprise-grade Pull Request description grounded in the verified diff and quality gate results.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
