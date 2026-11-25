import { create } from 'zustand';

const SESSION_STORAGE_KEY = 'grocerygenie_session_id';

type UIState = {
  theme: 'light' | 'dark';
  sessionId: string | null;
  setTheme: (theme: 'light' | 'dark') => void;
  toggleTheme: () => void;
  setSessionId: (id: string | null) => void;
  clearSession: () => void;
};

export const useUIStore = create<UIState>((set) => ({
  theme: (localStorage.getItem('theme') as 'light' | 'dark') || 'light',
  // Initialize sessionId from localStorage so page refreshes continue the same session
  sessionId: localStorage.getItem(SESSION_STORAGE_KEY) ?? null,
  setTheme: (theme) => {
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    set({ theme });
  },
  toggleTheme: () => {
    set((state) => {
      const newTheme = state.theme === 'light' ? 'dark' : 'light';
      localStorage.setItem('theme', newTheme);
      document.documentElement.setAttribute('data-theme', newTheme);
      return { theme: newTheme };
    });
  },
  setSessionId: (sessionId) => {
    if (sessionId !== null && sessionId !== undefined) {
      localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    } else {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    }
    set({ sessionId });
  },
  clearSession: () => {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    set({ sessionId: null });
  },
}));

export { SESSION_STORAGE_KEY };
