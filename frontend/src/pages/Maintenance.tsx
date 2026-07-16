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
    <div className="min-h-screen flex items-center justify-center bg-white dark:bg-[#0f1015] p-6 transition-colors duration-300">
      <div className="max-w-md w-full text-center space-y-8">
        {/* Visual Icon with Premium Gradient & Pulse effect */}
        <div className="relative inline-flex items-center justify-center">
          <div className="absolute inset-0 rounded-full bg-amber-500/20 blur-xl animate-pulse" />
          <div className="relative p-6 rounded-3xl bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/30 text-amber-500">
            <AlertTriangle size={48} className="animate-bounce" />
          </div>
        </div>

        {/* Text Area */}
        <div className="space-y-3">
          <h1 className="text-3xl font-black tracking-tight bg-gradient-to-r from-amber-500 to-orange-600 bg-clip-text text-transparent">
            Service Unreachable
          </h1>
          <p className="text-gray-600 dark:text-gray-400 text-sm leading-relaxed">
            We are having trouble connecting to the GroceryGenie backend. The server might be
            undergoing maintenance or temporarily offline.
          </p>
        </div>

        {/* Dynamic Error Status Message */}
        {errorMsg !== null && errorMsg !== '' && (
          <div className="p-3 text-xs font-semibold rounded-xl bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-950/30 text-red-500 transition-all duration-300">
            {errorMsg}
          </div>
        )}

        {/* Call to Actions */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="w-full sm:w-auto px-8 py-3 bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 font-bold rounded-2xl text-xs transition duration-300 flex items-center justify-center gap-2 active:scale-95 shadow-lg shadow-purple-500/10"
          >
            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
            <span>{retrying ? 'Retrying...' : 'Retry Connection'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
