export type TaskSource = 'issue' | 'backlog' | 'deterministic' | 'ai';

export type RiskLevel = 'low' | 'medium' | 'high';

export type TaskStatus =
  | 'discovered'
  | 'in_progress'
  | 'validated'
  | 'rejected'
  | 'completed'
  | 'skipped'
  | 'failed';

export type RunStatus =
  | 'task_completed'
  | 'tests_passed'
  | 'pull_request_created'
  | 'pull_request_merged'
  | 'contribution_verified'
  | 'no_task'
  | 'failed'
  | 'skipped'
  | 'dry_run_completed';

export interface Task {
  id: string;
  repo: string;
  title: string;
  description: string;
  rationale: string;
  acceptance_criteria: string[];
  risk_level: RiskLevel;
  validation_strategy: string;
  source: TaskSource;
  target_files: string[];
  patch?: string;
  created_at: string;
  metadata?: Record<string, any>;
}

export interface CommandResult {
  command: string[];
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  timed_out: boolean;
  passed: boolean;
}

export interface SecurityCheckResult {
  passed: boolean;
  secrets_detected: string[];
  denied_files: string[];
  path_traversals: string[];
  lines_changed: number;
  max_lines_allowed: number;
  details: string[];
}

export interface ASTAnalysisResult {
  passed: boolean;
  syntax_valid: boolean;
  errors: string[];
  disallowed_patterns_found: Array<{
    file: string;
    line: number;
    rule: string;
    message: string;
  }>;
  inspected_files: string[];
  ast_hash?: string;
  ast_structural_fingerprint?: string;
  source_integrity_hash?: string;
  ast_integrity_verified?: boolean;
}

export interface QualityGateResult {
  passed: boolean;
  reason: string;
  baseline_result?: CommandResult | null;
  post_change_tests: CommandResult[];
  post_change_lints: CommandResult[];
  security_result?: SecurityCheckResult | null;
  ast_result?: ASTAnalysisResult | null;
  patch_hash?: string | null;
  base_commit_sha?: string | null;
  tree_sha?: string | null;
  verified_diff?: string | null;
  changed_files: string[];
}

export interface DeliveryResult {
  success: boolean;
  branch_name?: string | null;
  pr_number?: number | null;
  pr_url?: string | null;
  is_dry_run: boolean;
  message: string;
  contribution_status: string;
  details?: Record<string, any>;
}

export interface RunReport {
  run_id: string;
  timestamp: string;
  repo: string;
  status: RunStatus;
  task?: Task | null;
  quality_gate?: QualityGateResult | null;
  delivery?: DeliveryResult | null;
  message: string;
  is_backup_run: boolean;
}

export interface RepoScheduleConfig {
  enabled: boolean;
  time: string; // HH:MM e.g. "09:00"
  timezone: string; // e.g. "Asia/Tashkent" or "UTC"
  backup_run_window_utc: string; // default "17:35"
  last_run_timestamp?: string;
  next_run_timestamp?: string;
}

export interface RepoConfig {
  name: string;
  default_branch: string;
  enabled: boolean;
  allowed_paths: string[];
  denied_paths: string[];
  max_diff_lines: number;
  timeout_seconds: number;
  supported_task_types: string[];
  allow_ai_tasks: boolean;
  clone_url?: string;
  schedule?: RepoScheduleConfig;
  baseline_command?: string[] | null;
  test_commands: string[][];
  lint_commands: string[][];
  curated_tasks: Array<{
    id: string;
    title: string;
    description: string;
    rationale: string;
    acceptance_criteria: string[];
    risk_level: RiskLevel;
    validation_strategy: string;
    source: TaskSource;
    target_files: string[];
    patch?: string;
  }>;
}

export interface SecurityPolicyConfig {
  max_diff_lines: number;
  max_tasks_per_run: number;
  block_workflows: boolean;
  block_lockfiles: boolean;
  require_secret_scan: boolean;
  denied_paths: string[];
  disallowed_extensions: string[];
}

export interface AIConfig {
  provider: 'mock' | 'gemini';
  model: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  max_requests_per_run: number;
}

export interface DailyGreenConfig {
  enabled: boolean;
  dry_run: boolean;
  allow_live_mutations: boolean;
  repos: RepoConfig[];
  policy: SecurityPolicyConfig;
  ai: AIConfig;
  state_dir: string;
}

export interface VirtualFile {
  path: string;
  content: string;
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
  message: string;
  extra?: Record<string, any>;
}

export interface BackendHealthResponse {
  status: 'ok' | 'degraded';
  uptime_seconds: number;
  timestamp: string;
  version: string;
  environment: {
    node_version: string;
    python_version: string | null;
    git_version: string | null;
    platform: string;
  };
  security_invariants: {
    dry_run_default: boolean;
    allow_live_mutations: boolean;
    max_workers: number;
    kill_switch_active: boolean;
  };
}

export interface CapabilityItem {
  name: string;
  supported: boolean;
  mode: 'native' | 'simulated' | 'missing_dependency';
  notes: string;
}

export interface BackendCapabilitiesResponse {
  capabilities: {
    git_cli: boolean;
    isolated_workspace: boolean;
    subprocess_sandbox: boolean;
    python_runtime: boolean;
    python_dailygreen_engine: boolean;
    durable_persistence: boolean;
    live_github_delivery: boolean;
  };
  limitations: string[];
  matrix: CapabilityItem[];
}

export interface ServerRunRecord {
  id: string;
  repo: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_stage?: string;
  start_time: string;
  end_time?: string;
  task?: Task | null;
  report?: RunReport | null;
  logs: ExecutionLog[];
  cancellable: boolean;
  error?: string | null;
  is_backup_run?: boolean;
  dry_run: boolean;
}

export interface CreateRunRequest {
  repo: string;
  is_backup_run?: boolean;
  dry_run?: boolean;
}

export interface CancelRunResponse {
  success: boolean;
  message: string;
  run_id: string;
}

export interface ApiErrorResponse {
  error: string;
  code: string;
  details?: Record<string, any>;
}

export interface ExecutionLease {
  repo: string;
  run_id: string;
  acquired_at: string;
  expires_at: string;
  holder: string;
}

export interface SchedulerAuditItem {
  id: string;
  timestamp: string;
  repo: string;
  event: 'TICK' | 'TRIGGERED' | 'IDEMPOTENT_SKIP' | 'BACKUP_EVALUATED' | 'LEASE_ACQUIRED' | 'LEASE_DENIED' | 'LEASE_EXPIRED' | 'RECOVERY_RUN';
  details: string;
}

export interface SchedulerStatusResponse {
  daemon_running: boolean;
  system_timezone: string;
  current_time_tz: string;
  current_time_utc: string;
  active_leases: Record<string, ExecutionLease>;
  schedules: Array<{
    repo: string;
    enabled: boolean;
    scheduled_time: string;
    timezone: string;
    next_run_iso: string;
    last_run_iso?: string;
    is_backup_window: boolean;
  }>;
  audit_trail: SchedulerAuditItem[];
}

export interface GitDiffSummary {
  files_changed: string[];
  total_lines_added: number;
  total_lines_deleted: number;
  raw_diff: string;
  branch_created?: string;
}

export interface DiscoveredRepo {
  id: number;
  name: string;
  full_name: string;
  private: boolean;
  html_url: string;
  description: string | null;
  default_branch: string;
  stars_count: number;
  forks_count: number;
  open_issues_count: number;
  pushed_at: string;
  updated_at: string;
  monitored: boolean;
  active?: boolean;
  permissions?: {
    admin: boolean;
    maintain: boolean;
    push: boolean;
    triage: boolean;
    pull: boolean;
  };
  health_score?: number;
  last_inspected?: string;
}

export interface RepoInspectionResult {
  repo: string;
  default_branch: string;
  visibility: 'public' | 'private';
  html_url: string;
  description: string | null;
  pushed_at: string;
  latest_commits: Array<{
    sha: string;
    message: string;
    author: string;
    date: string;
  }>;
  tree_summary: {
    total_files: number;
    file_types: Record<string, number>;
    docs_count: number;
    tests_count: number;
    workflow_files: string[];
  };
  maintenance_status: {
    health_score: number;
    has_readme: boolean;
    has_license: boolean;
    has_contributing: boolean;
    has_tests: boolean;
    has_ci: boolean;
    open_issues_count: number;
    stale_days: number;
    recommendations: string[];
    detected_issues: Array<{
      category: 'security' | 'documentation' | 'code_quality' | 'maintenance' | 'hygiene';
      severity: 'low' | 'medium' | 'high';
      title: string;
      description: string;
      suggested_action: string;
    }>;
  };
}

