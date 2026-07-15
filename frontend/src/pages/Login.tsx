import React, { useState } from 'react';
import { authService } from '../services/api';

type LoginProps = {
  onLoginSuccess?: () => void;
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleGoogleLogin = () => {
    const loginUrl = import.meta.env.DEV
      ? 'http://localhost:8000/api/v1/auth/google/login'
      : '/api/v1/auth/google/login';
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
    } catch (err: any) {
      console.error(err);
      setError(err.response?.data?.detail || 'Dev bypass failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col justify-center items-center py-20 px-4 bg-gradient-to-br from-indigo-50/20 via-purple-50/10 to-pink-50/20 dark:from-gray-950 dark:via-purple-950/10 dark:to-gray-900">
      <div className="max-w-md w-full p-8 border border-white/20 dark:border-gray-800/40 rounded-3xl glassmorphism shadow-2xl text-center space-y-6 relative overflow-hidden backdrop-blur-xl bg-white/40 dark:bg-gray-950/40">

        {/* Subtle decorative background glows */}
        <div className="absolute -top-10 -left-10 w-32 h-32 bg-purple-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-10 -right-10 w-32 h-32 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="space-y-2">
          <h1 className="text-4xl font-black tracking-tight bg-gradient-to-r from-purple-600 via-indigo-600 to-pink-600 bg-clip-text text-transparent">
            GroceryGenie
          </h1>
          <p className="text-[10px] font-semibold tracking-wider text-purple-600 dark:text-purple-400 uppercase">
            Voice-First AI Shopping Assistant
          </p>
        </div>

        {error && (
          <div className="p-3 text-xs bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 rounded-xl border border-red-200 dark:border-red-900 text-left">
            {error}
          </div>
        )}

        <div>
          <button
            onClick={handleGoogleLogin}
            className="group w-full py-3 px-5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-purple-500 dark:hover:border-purple-400 hover:shadow-lg hover:shadow-purple-500/10 rounded-2xl text-xs font-bold text-gray-700 dark:text-gray-300 transition duration-300 flex justify-center items-center gap-3 active:scale-[0.98]"
          >
            <svg className="w-4 h-4 group-hover:scale-110 transition duration-300" viewBox="0 0 24 24">
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
          <div className="pt-2">
            <button
              onClick={handleDevBypass}
              disabled={loading}
              className="w-full py-3 px-5 bg-purple-600 hover:bg-purple-700 text-white rounded-2xl text-xs font-bold transition duration-300 active:scale-[0.98] focus:outline-none"
            >
              {loading ? 'Bypassing...' : 'Continue as Dev User'}
            </button>
          </div>
        )}

        <div className="border-t border-gray-100 dark:border-gray-900 pt-4">
          <p className="text-[9px] text-gray-400 leading-relaxed px-6">
            Authorized logins are fully secured with httpOnly sessions.
          </p>
        </div>
      </div>
    </div>
  );
};
