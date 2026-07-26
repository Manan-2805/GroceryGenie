import { AlertTriangle, RefreshCw } from 'lucide-react';
import React, { useState } from 'react';

import { healthService } from '../services/api';
import { useUIStore } from '../store/uiStore';

export const Maintenance: React.FC = () => {
  const { setBackendUnreachable } = useUIStore();
  const [retrying, setRetrying] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleRetry = async () => {
    setRetrying(true);
    setErrorMsg(null);
    try {
      await healthService.checkApiHealth();
      setBackendUnreachable(false);
    } catch {
      setErrorMsg(
        'The server is still unreachable. Please verify your connection or try again later.'
      );
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-app p-6 transition-colors duration-300">
      <div className="glass-card max-w-md w-full text-center space-y-8 p-8">
        <div className="inline-flex items-center justify-center p-5 rounded-2xl bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/30 text-amber-500">
          <AlertTriangle size={40} />
        </div>

        <div className="space-y-3">
          <h1 className="text-2xl font-semibold tracking-tight text-heading">
            Service Unreachable
          </h1>
          <p className="text-muted text-sm leading-relaxed">
            We are having trouble connecting to the GroceryGenie backend. The server might be
            undergoing maintenance or temporarily offline.
          </p>
        </div>

        {errorMsg !== null && errorMsg !== '' && (
          <div className="p-3 text-xs font-medium rounded-xl bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-950/30 text-red-500">
            {errorMsg}
          </div>
        )}

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-2">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="btn-primary w-full sm:w-auto"
          >
            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
            <span>{retrying ? 'Retrying...' : 'Retry Connection'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
