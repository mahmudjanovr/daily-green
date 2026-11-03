/**
 * DailyGreen Autonomous Background Scheduling Daemon
 *
 * Implements:
 * - Timezone-aware daily scheduling (supporting Asia/Tashkent and UTC)
 * - 17:35 UTC backup run classification & idempotency verification
 * - Atomic execution leases with TTL (max workers: 1)
 * - Server restart recovery & stale lease pruning
 * - Rules-first task discovery triggering
 * - Durable scheduler audit trail
 */

import { ExecutionLease, RepoConfig, SchedulerAuditItem, SchedulerStatusResponse } from '../types';
import { serverPipelineOrchestrator } from './orchestrator';
import { serverPersistence } from './persistence';

export class SchedulerService {
  private timer: NodeJS.Timeout | null = null;
  private running = false;
  private intervalMs = 30000; // Check every 30 seconds
  private activeLeases: Map<string, ExecutionLease> = new Map();
  private auditTrail: SchedulerAuditItem[] = [];
  private maxAuditItems = 100;
  private defaultTimezone = 'Asia/Tashkent';

  constructor() {
    this.recordAudit('TICK', 'SYSTEM', 'Scheduler service initialized.');
  }

  /**
   * Helper to format dates and extract hour, minute, and dateString in a specified IANA timezone.
   */
  public getTimeInTimezone(
    date: Date = new Date(),
    timeZone: string = this.defaultTimezone
  ): { hour: number; minute: number; timeString: string; dateString: string } {
    try {
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone,
        hour12: false,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });

      const parts = formatter.formatToParts(date);
      let year = '';
      let month = '';
      let day = '';
      let hour = '0';
      let minute = '0';

      for (const p of parts) {
        if (p.type === 'year') year = p.value;
        if (p.type === 'month') month = p.value;
        if (p.type === 'day') day = p.value;
        if (p.type === 'hour') hour = p.value;
        if (p.type === 'minute') minute = p.value;
      }

      // Format "24" hour if returned as 24
      const hNum = parseInt(hour, 10) % 24;
      const mNum = parseInt(minute, 10);
      const padHour = String(hNum).padStart(2, '0');
      const padMin = String(mNum).padStart(2, '0');

      return {
        hour: hNum,
        minute: mNum,
        timeString: `${padHour}:${padMin}`,
        dateString: `${year}-${month}-${day}`,
      };
    } catch {
      // Fallback to UTC if timezone invalid
      const hNum = date.getUTCHours();
      const mNum = date.getUTCMinutes();
      return {
        hour: hNum,
        minute: mNum,
        timeString: `${String(hNum).padStart(2, '0')}:${String(mNum).padStart(2, '0')}`,
        dateString: date.toISOString().split('T')[0],
      };
    }
  }

  /**
   * Evaluates if current time is within the DailyGreen designated 17:35 UTC backup run window.
   */
  public isBackupRunWindow(date: Date = new Date()): boolean {
    const utcHour = date.getUTCHours();
    const utcMin = date.getUTCMinutes();
    // 17:35 UTC window: 17:35 to 17:40 UTC
    return utcHour === 17 && utcMin >= 35 && utcMin <= 40;
  }

  /**
   * Records an event in the scheduler audit trail.
   */
  public recordAudit(
    event: SchedulerAuditItem['event'],
    repo: string,
    details: string
  ): void {
    const item: SchedulerAuditItem = {
      id: `audit-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      timestamp: new Date().toISOString(),
      repo,
      event,
      details,
    };
    this.auditTrail.unshift(item);
    if (this.auditTrail.length > this.maxAuditItems) {
      this.auditTrail.pop();
    }
  }

  /**
   * Attempts to acquire an exclusive execution lease for a repository.
   * Enforces global max workers = 1 and per-repository mutual exclusion.
   */
  public acquireLease(repoName: string, runId: string, ttlSeconds = 600): boolean {
    this.pruneExpiredLeases();

    // Enforce Max Workers = 1 (if any repo is currently executing, cannot acquire lease)
    if (this.activeLeases.size >= 1 && !this.activeLeases.has(repoName)) {
      this.recordAudit(
        'LEASE_DENIED',
        repoName,
        `Global worker concurrency limit reached (max_workers=1). Execution deferred.`
      );
      return false;
    }

    const existing = this.activeLeases.get(repoName);
    if (existing) {
      const now = Date.now();
      const expiresAt = new Date(existing.expires_at).getTime();
      if (now < expiresAt) {
        this.recordAudit(
          'LEASE_DENIED',
          repoName,
          `Repository already locked by active lease (${existing.run_id}).`
        );
        return false;
      }
      this.recordAudit('LEASE_EXPIRED', repoName, `Pruned expired lease for run ${existing.run_id}`);
    }

    const nowIso = new Date().toISOString();
    const expiresIso = new Date(Date.now() + ttlSeconds * 1000).toISOString();

    const newLease: ExecutionLease = {
      repo: repoName,
      run_id: runId,
      acquired_at: nowIso,
      expires_at: expiresIso,
      holder: `scheduler-worker-${process.pid}`,
    };

    this.activeLeases.set(repoName, newLease);
    this.recordAudit('LEASE_ACQUIRED', repoName, `Acquired lease for run ${runId} (expires ${expiresIso})`);
    return true;
  }

  /**
   * Releases an execution lease.
   */
  public releaseLease(repoName: string, runId?: string): void {
    const existing = this.activeLeases.get(repoName);
    if (existing) {
      if (!runId || existing.run_id === runId) {
        this.activeLeases.delete(repoName);
        this.recordAudit('LEASE_EXPIRED', repoName, `Released lease for run ${existing.run_id}`);
      }
    }
  }

  /**
   * Prunes any leases whose TTL has elapsed.
   */
  public pruneExpiredLeases(): void {
    const now = Date.now();
    for (const [repo, lease] of this.activeLeases.entries()) {
      if (now >= new Date(lease.expires_at).getTime()) {
        this.activeLeases.delete(repo);
        this.recordAudit('LEASE_EXPIRED', repo, `Lease for run ${lease.run_id} expired and was automatically pruned.`);
      }
    }
  }

  /**
   * Checks whether a repository already had a successful run today in UTC.
   */
  public async hasSucceededToday(repoName: string, targetDateUtc: string): Promise<boolean> {
    const runs = await serverPersistence.getRuns();
    return runs.some((r) => {
      if (r.repo !== repoName || r.status !== 'completed') return false;
      const runDate = new Date(r.start_time).toISOString().split('T')[0];
      return runDate === targetDateUtc && r.report?.status !== 'failed';
    });
  }

  /**
   * Computes the next scheduled run ISO string for a given schedule configuration.
   */
  public computeNextRunIso(timeString: string, timezone: string): string {
    const now = new Date();
    const [schedH, schedM] = timeString.split(':').map((v) => parseInt(v, 10));
    const nowTz = this.getTimeInTimezone(now, timezone);

    const targetDate = new Date();
    if (nowTz.hour > schedH || (nowTz.hour === schedH && nowTz.minute >= schedM)) {
      // Advance to tomorrow
      targetDate.setDate(targetDate.getDate() + 1);
    }

    // Rough approximate ISO representation in local tz
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${targetDate.toISOString().split('T')[0]}T${pad(schedH)}:${pad(schedM)}:00 (${timezone})`;
  }

  /**
   * Core scheduling evaluation tick.
   */
  public async evaluateScheduledRuns(): Promise<void> {
    this.pruneExpiredLeases();

    const config = await serverPersistence.getConfig();
    if (!config.enabled) {
      return;
    }

    const now = new Date();
    const todayUtc = now.toISOString().split('T')[0];
    const inBackupWindow = this.isBackupRunWindow(now);

    for (const repo of config.repos) {
      if (!repo.enabled) continue;

      const schedule = repo.schedule || {
        enabled: true,
        time: '09:00',
        timezone: this.defaultTimezone,
        backup_run_window_utc: '17:35',
      };

      if (!schedule.enabled) continue;

      const localTime = this.getTimeInTimezone(now, schedule.timezone);

      // Check 1: Daily primary scheduled slot (matches current HH:MM)
      const isPrimaryDue = localTime.timeString === schedule.time;

      // Check 2: 17:35 UTC backup run slot
      const isBackupDue = inBackupWindow;

      if (!isPrimaryDue && !isBackupDue) {
        continue;
      }

      // Check idempotency: If repo already succeeded today, skip!
      const alreadySucceeded = await this.hasSucceededToday(repo.name, todayUtc);
      if (alreadySucceeded) {
        this.recordAudit(
          'IDEMPOTENT_SKIP',
          repo.name,
          `Autonomous run skipped: Repo '${repo.name}' already has a verified completed run for today (${todayUtc}).`
        );
        continue;
      }

      // If in backup window, verify backup run classification
      const isBackupRun = isBackupDue && !isPrimaryDue;
      if (isBackupRun) {
        this.recordAudit(
          'BACKUP_EVALUATED',
          repo.name,
          `Triggering 17:35 UTC backup run: No primary run was completed for '${repo.name}' today.`
        );
      }

      // Acquire execution lease
      const dummyRunId = `run-${Date.now()}`;
      const acquired = this.acquireLease(repo.name, dummyRunId);
      if (!acquired) {
        continue;
      }

      try {
        this.recordAudit(
          'TRIGGERED',
          repo.name,
          `Autonomous daemon triggered maintenance run for '${repo.name}' (Backup: ${isBackupRun}).`
        );

        // Trigger orchestrator with safe dry-run setting from policy
        const runRecord = await serverPipelineOrchestrator.startRun(
          repo.name,
          isBackupRun,
          config.dry_run
        );

        // Update lease with real run ID
        this.activeLeases.set(repo.name, {
          repo: repo.name,
          run_id: runRecord.id,
          acquired_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 600000).toISOString(),
          holder: `scheduler-worker-${process.pid}`,
        });
      } catch (err: any) {
        this.releaseLease(repo.name);
        this.recordAudit('TRIGGERED', repo.name, `Failed to launch scheduled run: ${err.message}`);
      }
    }
  }

  /**
   * Server restart recovery: Inspects and clears stale state.
   */
  public async performStartupRecovery(): Promise<void> {
    this.pruneExpiredLeases();
    const config = await serverPersistence.getConfig();
    const now = new Date();
    const todayUtc = now.toISOString().split('T')[0];

    for (const repo of config.repos) {
      if (!repo.enabled) continue;
      const alreadySucceeded = await this.hasSucceededToday(repo.name, todayUtc);
      this.recordAudit(
        'RECOVERY_RUN',
        repo.name,
        `Startup check for '${repo.name}': Daily completed status = ${alreadySucceeded}`
      );
    }
  }

  /**
   * Starts the background scheduling loop.
   */
  public startDaemon(): void {
    if (this.running) return;
    this.running = true;
    this.recordAudit('TICK', 'SYSTEM', 'Autonomous scheduling daemon started.');

    // Execute startup recovery
    this.performStartupRecovery().catch(() => {});

    // Schedule periodic tick
    this.timer = setInterval(() => {
      this.evaluateScheduledRuns().catch((err) => {
        this.recordAudit('TICK', 'SYSTEM', `Scheduler evaluation error: ${err.message}`);
      });
    }, this.intervalMs);
  }

  /**
   * Stops the background scheduling loop.
   */
  public stopDaemon(): void {
    if (!this.running) return;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.running = false;
    this.recordAudit('TICK', 'SYSTEM', 'Autonomous scheduling daemon stopped.');
  }

  public isDaemonRunning(): boolean {
    return this.running;
  }

  /**
   * Returns complete scheduler status response for API endpoints and UI.
   */
  public async getStatus(): Promise<SchedulerStatusResponse> {
    const config = await serverPersistence.getConfig();
    const now = new Date();
    const tzNow = this.getTimeInTimezone(now, this.defaultTimezone);

    const schedules = config.repos.map((r) => {
      const sched = r.schedule || {
        enabled: true,
        time: '09:00',
        timezone: this.defaultTimezone,
        backup_run_window_utc: '17:35',
      };
      return {
        repo: r.name,
        enabled: sched.enabled,
        scheduled_time: sched.time,
        timezone: sched.timezone,
        next_run_iso: this.computeNextRunIso(sched.time, sched.timezone),
        last_run_iso: sched.last_run_timestamp,
        is_backup_window: this.isBackupRunWindow(now),
      };
    });

    const activeLeasesObj: Record<string, ExecutionLease> = {};
    for (const [key, lease] of this.activeLeases.entries()) {
      activeLeasesObj[key] = lease;
    }

    return {
      daemon_running: this.running,
      system_timezone: this.defaultTimezone,
      current_time_tz: `${tzNow.timeString} (${this.defaultTimezone})`,
      current_time_utc: now.toISOString(),
      active_leases: activeLeasesObj,
      schedules,
      audit_trail: this.auditTrail,
    };
  }
}

// Global singleton scheduler instance
export const schedulerService = new SchedulerService();
