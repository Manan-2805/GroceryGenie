import React, { useEffect, useState } from 'react';
import { Trash2, ShieldAlert } from 'lucide-react';
import { memoryService, PersistentFact } from '../services/api';

interface SettingsProps {
  userRole: string;
  onRoleChange: (newRole: 'customer' | 'seller') => void;
}

export const Settings: React.FC<SettingsProps> = ({ userRole, onRoleChange }) => {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  const [facts, setFacts] = useState<PersistentFact[]>([]);
  const [loadingFacts, setLoadingFacts] = useState(false);

  useEffect(() => {
    // Apply theme
    const root = document.documentElement;
    root.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const fetchFacts = async () => {
    setLoadingFacts(true);
    try {
      // Hit endpoint
      const res = await memoryService.listFacts();
      setFacts(res);
    } catch (e) {
      console.error('Failed to load facts', e);
    } finally {
      setLoadingFacts(false);
    }
  };

  useEffect(() => {
    fetchFacts();
  }, []);

  const handleDeleteFact = async (id: string) => {
    try {
      await memoryService.deleteFact(id);
      setFacts((prev) => prev.filter((f) => f.id !== id));
    } catch (e) {
      console.error('Failed to delete fact', e);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Settings</h1>
        <p className="text-sm text-gray-500">Manage your theme, role, and agent memories</p>
      </div>

      {/* Theme Control */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">Visual Theme</h3>
        <div className="flex gap-4">
          <button
            onClick={() => setTheme('light')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              theme === 'light'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Light Mode
          </button>
          <button
            onClick={() => setTheme('dark')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              theme === 'dark'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Dark Mode
          </button>
        </div>
      </div>

      {/* Role Switching */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">Role Selection</h3>
        <p className="text-xs text-gray-500">
          Switching your role will customize your view between buying and managing inventory.
        </p>
        <div className="flex gap-4">
          <button
            onClick={() => onRoleChange('customer')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              userRole === 'customer'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Customer View
          </button>
          <button
            onClick={() => onRoleChange('seller')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              userRole === 'seller'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Seller Panel
          </button>
        </div>
      </div>

      {/* Facts Memory manager */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">What I remember about you</h3>
        <p className="text-xs text-gray-500">
          The agent automatically extracts standing facts (like dietary preferences and allergies) to customize responses. Delete items below if you no longer wish them to be remembered.
        </p>

        {loadingFacts ? (
          <p className="text-sm text-gray-400">Loading memories...</p>
        ) : facts.length === 0 ? (
          <div className="p-4 border border-dashed rounded-lg text-center text-sm text-gray-400">
            No memories stored yet. Try saying "remember I'm lactose intolerant" in chat!
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-900">
            {facts.map((fact) => (
              <div key={fact.id} className="py-3 flex items-center justify-between gap-4">
                <div>
                  <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 mr-3">
                    {fact.category}
                  </span>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    "{fact.fact_text}"
                  </span>
                </div>
                <button
                  onClick={() => handleDeleteFact(fact.id)}
                  className="p-1.5 hover:bg-red-50 dark:hover:bg-red-950/20 text-red-500 rounded-lg transition"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
