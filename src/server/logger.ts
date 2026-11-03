/**
 * DailyGreen Production Structured Logger
 *
 * Provides:
 * - Structured JSON logging with ISO-8601 timestamps and correlation IDs
 * - Invariant secret redaction on all message strings and metadata objects
 * - In-memory rolling buffer for UI observability and SRE monitoring
 * - Local filesystem log persistence in .dailygreen-data/logs/
 */

import * as fs from 'fs';
import * as path from 'path';
import { redactSecrets } from '../services/security';

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'AUDIT';

export interface StructuredLogEntry {
  timestamp: string;
  level: LogLevel;
  module: string;
  message: string;
  correlationId?: string;
  details?: Record<string, any>;
}

class Logger {
  private inMemoryLogs: StructuredLogEntry[] = [];
  private readonly maxInMemoryLogs = 200;
  private logDirectory: string;
  private logFilePath: string;
  private fileLoggingEnabled = false;

  constructor() {
    this.logDirectory = path.join(process.cwd(), '.dailygreen-data', 'logs');
    this.logFilePath = path.join(this.logDirectory, 'dailygreen.log');
    this.initFileLogging();
  }

  private initFileLogging(): void {
    try {
      if (!fs.existsSync(this.logDirectory)) {
        fs.mkdirSync(this.logDirectory, { recursive: true, mode: 0o750 });
      }
      this.fileLoggingEnabled = true;
    } catch {
      this.fileLoggingEnabled = false;
    }
  }

  private sanitizeDetails(obj: any): any {
    if (!obj) return obj;
    try {
      const str = JSON.stringify(obj);
      return JSON.parse(redactSecrets(str));
    } catch {
      return { note: 'Unserializable details sanitized' };
    }
  }

  public log(level: LogLevel, module: string, message: string, correlationId?: string, details?: Record<string, any>): void {
    const entry: StructuredLogEntry = {
      timestamp: new Date().toISOString(),
      level,
      module,
      message: redactSecrets(message),
      correlationId,
      details: this.sanitizeDetails(details),
    };

    // Store in memory buffer
    this.inMemoryLogs.unshift(entry);
    if (this.inMemoryLogs.length > this.maxInMemoryLogs) {
      this.inMemoryLogs.pop();
    }

    const logLine = JSON.stringify(entry);

    // Standard output based on level
    if (level === 'ERROR') {
      console.error(logLine);
    } else if (level === 'WARN') {
      console.warn(logLine);
    } else {
      console.log(logLine);
    }

    // Persist to log file if enabled
    if (this.fileLoggingEnabled) {
      try {
        fs.appendFileSync(this.logFilePath, logLine + '\n', { mode: 0o640 });
      } catch {
        // Suppress disk write error to prevent process crash
      }
    }
  }

  public info(module: string, message: string, correlationId?: string, details?: Record<string, any>): void {
    this.log('INFO', module, message, correlationId, details);
  }

  public warn(module: string, message: string, correlationId?: string, details?: Record<string, any>): void {
    this.log('WARN', module, message, correlationId, details);
  }

  public error(module: string, message: string, correlationId?: string, details?: Record<string, any>): void {
    this.log('ERROR', module, message, correlationId, details);
  }

  public audit(module: string, message: string, correlationId?: string, details?: Record<string, any>): void {
    this.log('AUDIT', module, message, correlationId, details);
  }

  public getRecentLogs(limit = 100, level?: LogLevel, correlationId?: string): StructuredLogEntry[] {
    let filtered = this.inMemoryLogs;
    if (level) {
      filtered = filtered.filter((l) => l.level === level);
    }
    if (correlationId) {
      filtered = filtered.filter((l) => l.correlationId === correlationId);
    }
    return filtered.slice(0, limit);
  }

  public clearInMemoryLogs(): void {
    this.inMemoryLogs = [];
  }
}

export const logger = new Logger();
