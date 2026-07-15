import React, { useState } from 'react';
import { AlertOctagon, RefreshCw, ArrowLeft } from 'lucide-react';
import { useUIStore } from '../store/uiStore';
import { healthService } from '../services/api';

export const ErrorPage: React.FC = () => {
  const { appError, setAppError } = useUIStore();
  const [retrying, setRetrying] = useState(false);
  const [retryStatus, setRetryStatus] = useState<string | null>(null);

  const handleRetry = async () => {
    setRetrying(true);
    setRetryStatus(null);
    try {
      // Perform health check to see if the server recovered
      await healthService.checkApiHealth();
      setAppError(null); // Clear error on success (triggers auto redirect to safety)
    } catch (e) {
      setRetryStatus('Server is still reporting errors. Please try again shortly.');
    } finally {
      setRetrying(false);
    }
  };

  const handleBypass = () => {
    setAppError(null);
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center py-20 px-4 bg-gradient-to-br from-red-50/20 via-orange-50/10 to-gray-50/20 dark:from-gray-950 dark:via-red-950/10 dark:to-gray-900 text-left">
      <div className="max-w-lg w-full p-8 border border-red-200/40 dark:border-red-900/40 rounded-3xl glassmorphism shadow-2xl space-y-6 relative overflow-hidden backdrop-blur-xl bg-white/40 dark:bg-gray-950/40">
        
        {/* Glow decoration */}
        <div className="absolute -top-10 -left-10 w-32 h-32 bg-red-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="flex items-center gap-4 border-b dark:border-red-950/40 pb-4">
          <div className="p-3 bg-red-50 dark:bg-red-950/20 text-red-500 rounded-2xl">
            <AlertOctagon size={32} />
          </div>
          <div>
            <h1 className="text-2xl font-black text-gray-800 dark:text-gray-200">Application Error</h1>
            <p className="text-xs text-gray-500">The server encountered an unhandled exception</p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-bold text-red-500 dark:text-red-400 uppercase tracking-widest">Error Traceback Details</label>
          <div className="p-4 border dark:border-gray-800 rounded-2xl bg-gray-50/80 dark:bg-gray-950/80 font-mono text-[11px] leading-relaxed text-gray-700 dark:text-gray-300 max-h-[220px] overflow-y-auto break-all">
            {appError || 'No error details found.'}
          </div>
        </div>

        {retryStatus && (
          <p className="text-xs font-semibold text-red-500 text-center">{retryStatus}</p>
        )}

        <div className="pt-2 flex flex-col sm:flex-row gap-3">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="flex-1 py-3 px-5 bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 rounded-2xl text-xs font-bold transition flex justify-center items-center gap-2 shadow-lg shadow-red-500/10 active:scale-[0.98]"
          >
            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
            <span>{retrying ? 'Retrying Connection...' : 'Retry Connection'}</span>
          </button>
          
          <button
            onClick={handleBypass}
            className="py-3 px-5 border dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-900 rounded-2xl text-xs font-bold text-gray-700 dark:text-gray-300 transition flex justify-center items-center gap-2 active:scale-[0.98]"
          >
            <ArrowLeft size={14} />
            <span>Go to Home</span>
          </button>
        </div>
      </div>
    </div>
  );
};
