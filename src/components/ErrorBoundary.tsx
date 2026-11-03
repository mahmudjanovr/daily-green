import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[DailyGreen UI Error Boundary caught an error]:', error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl text-center space-y-4">
            <div className="h-12 w-12 rounded-full bg-rose-950/60 border border-rose-500/40 text-rose-400 flex items-center justify-center mx-auto">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">Application Exception Encountered</h2>
              <p className="text-xs text-slate-400 mt-1">
                The DailyGreen user interface caught an unexpected error. Fail-safe state isolation is active.
              </p>
            </div>
            {this.state.error && (
              <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-[11px] font-mono text-rose-300 text-left overflow-x-auto max-h-32">
                {this.state.error.message}
              </div>
            )}
            <button
              onClick={this.handleReset}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center justify-center gap-2 w-full transition shadow"
            >
              <RefreshCw className="h-4 w-4" />
              <span>Reload Application</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
