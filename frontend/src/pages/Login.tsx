import React, { useState } from 'react';
import { authService } from '../services/api';

interface LoginProps {
  onLoginSuccess: (name: string, role: string) => void;
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const [loading, setLoading] = useState<string | null>(null);

  const handleMockLogin = async (role: 'customer' | 'seller') => {
    setLoading(role);
    try {
      const data = await authService.mockLogin(role);
      onLoginSuccess(data.name, data.role);
    } catch (e) {
      console.error(e);
      alert('Mock login failed. Make sure backend is running.');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="flex-1 flex flex-col justify-center items-center py-20 px-4">
      <div className="max-w-md w-full p-8 border rounded-2xl glassmorphism shadow-xl text-center space-y-6">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-purple-600 to-indigo-600 bg-clip-text text-transparent">
            GroceryGenie
          </h1>
          <p className="text-sm text-gray-500 mt-2">
            The next-generation voice-first shopping assistant
          </p>
        </div>

        <div className="space-y-4 pt-4">
          <button
            onClick={() => handleMockLogin('customer')}
            disabled={loading !== null}
            className="w-full py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-bold transition flex justify-center items-center gap-2"
          >
            {loading === 'customer' ? 'Logging in...' : 'Sign in as Test Customer'}
          </button>
          
          <button
            onClick={() => handleMockLogin('seller')}
            disabled={loading !== null}
            className="w-full py-3 border border-purple-600 hover:bg-purple-50 dark:hover:bg-purple-950/20 text-purple-600 dark:text-purple-400 rounded-xl font-bold transition flex justify-center items-center gap-2"
          >
            {loading === 'seller' ? 'Logging in...' : 'Sign in as Test Seller'}
          </button>
        </div>

        <p className="text-[10px] text-gray-400 mt-4">
          Note: This local mock auth is only active in development mode. Google OAuth login will be automatically loaded in production.
        </p>
      </div>
    </div>
  );
};
