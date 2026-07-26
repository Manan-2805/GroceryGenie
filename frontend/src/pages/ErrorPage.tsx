import { AlertOctagon, RefreshCw, ArrowLeft } from 'lucide-react';
import React, { useState } from 'react';

import { healthService } from '../services/api';
import { useUIStore } from '../store/uiStore';

export const ErrorPage: React.FC = () => {
  const { appError, setAppError } = useUIStore();
  const [retrying, setRetrying] = useState(false);
  const [retryStatus, setRetryStatus] = useState<string | null>(null);

  const handleRetry = async () => {
    setRetrying(true);
    setRetryStatus(null);
    try {
      await healthService.checkApiHealth();
      setAppError(null);
    } catch {
      setRetryStatus('Server is still reporting errors. Please try again shortly.');
    } finally {
      setRetrying(false);
    }
  };

  const handleBypass = () => {
    setAppError(null);
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center py-20 px-4 bg-app text-left">
      <div className="glass-card max-w-lg w-full p-8 space-y-6">
        <div className="flex items-center gap-4 border-b border-border/60 pb-4">
          <div className="p-3 bg-red-50 dark:bg-red-950/20 text-red-500 rounded-2xl">
            <AlertOctagon size={28} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-heading">Application Error</h1>
            <p className="text-xs text-muted">The server encountered an unhandled exception</p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-semibold text-red-500 dark:text-red-400 uppercase tracking-widest">
            Error Traceback Details
          </label>
          <div className="p-4 border border-border rounded-xl bg-surface/80 font-mono text-[11px] leading-relaxed text-heading max-h-[220px] overflow-y-auto break-all">
            {appError ?? 'No error details found.'}
          </div>
        </div>

        {retryStatus !== null && retryStatus !== '' && (
          <p className="text-xs font-medium text-red-500 text-center">{retryStatus}</p>
        )}

        <div className="pt-2 flex flex-col sm:flex-row gap-3">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="flex-1 py-3 px-5 bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 rounded-xl text-xs font-semibold transition flex justify-center items-center gap-2"
          >
            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
            <span>{retrying ? 'Retrying Connection...' : 'Retry Connection'}</span>
          </button>

          <button onClick={handleBypass} className="btn-secondary">
            <ArrowLeft size={14} />
            <span>Go to Home</span>
          </button>
        </div>
      </div>
    </div>
  );
};
