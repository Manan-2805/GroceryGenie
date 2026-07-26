import React, { useState } from 'react';

import { authService } from '../services/api';

type LoginProps = {
  onLoginSuccess?: () => void;
};

type ErrorPayload = {
  response?: {
    data?: {
      detail?: unknown;
    };
  };
};

const getErrorMessage = (error: unknown): string => {
  const payload = error as ErrorPayload;
  const detail = payload.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'Dev bypass failed.';
};

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGoogleLogin = () => {
    const loginUrl = '/api/v1/auth/google/login';
    window.location.href = loginUrl;
  };

  const handleDevBypass = async () => {
    setError(null);
    setLoading(true);
    try {
      await authService.devBypass();
      if (onLoginSuccess) {
        onLoginSuccess();
      } else {
        window.location.reload();
      }
    } catch (err: unknown) {
      console.error(err);
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center py-20 px-4 bg-app">
      <div className="glass-card max-w-md w-full p-8 text-center space-y-6">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-accent">GroceryGenie</h1>
          <p className="text-[10px] font-semibold tracking-wider text-muted uppercase">
            Voice-First AI Shopping Assistant
          </p>
        </div>

        {error !== null && error !== '' && (
          <div className="p-3 text-xs bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 rounded-xl border border-red-200 dark:border-red-900 text-left">
            {error}
          </div>
        )}

        <div>
          <button
            onClick={handleGoogleLogin}
            className="group w-full py-3 px-5 bg-surface border border-border hover:border-accent rounded-xl text-xs font-semibold text-heading transition duration-200 flex justify-center items-center gap-3 active:scale-[0.98]"
          >
            <svg
              className="w-4 h-4 group-hover:scale-105 transition duration-200"
              viewBox="0 0 24 24"
            >
              <path
                fill="#4285F4"
                d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v3.92h6.58c-.28 1.48-1.11 2.74-2.36 3.59v2.98h3.8c2.22-2.05 3.5-5.07 3.5-8.42z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.24 0 5.97-1.08 7.96-2.91l-3.8-2.98c-1.05.7-2.4 1.12-4.16 1.12-3.2 0-5.91-2.16-6.87-5.07H1.31v3.08C3.29 20.87 7.37 24 12 24z"
              />
              <path
                fill="#FBBC05"
                d="M5.13 14.16c-.25-.76-.39-1.57-.39-2.41s.14-1.65.39-2.41V6.26H1.31C.48 7.92 0 9.8 0 11.75s.48 3.83 1.31 5.49l3.82-3.08z"
              />
              <path
                fill="#EA4335"
                d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.22 0 12 0 7.37 0 3.29 3.13 1.31 7.21l3.82 3.08c.96-2.91 3.67-5.07 6.87-5.07z"
              />
            </svg>
            <span>Sign in with Google</span>
          </button>
        </div>

        {import.meta.env.DEV && (
          <div className="pt-1">
            <button onClick={handleDevBypass} disabled={loading} className="btn-primary w-full">
              {loading ? 'Bypassing...' : 'Continue as Dev User'}
            </button>
          </div>
        )}

        <div className="border-t border-border/60 pt-4">
          <p className="text-[9px] text-muted leading-relaxed px-6">
            Authorized logins are fully secured with httpOnly sessions.
          </p>
        </div>
      </div>
    </div>
  );
};
