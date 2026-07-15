import { create } from 'zustand';

type UIState = {
  theme: 'light' | 'dark';
  sessionId: string | null;
  voiceOk: boolean;
  backendUnreachable: boolean;
  appError: string | null;
  setTheme: (theme: 'light' | 'dark') => void;
  toggleTheme: () => void;
  setSessionId: (id: string | null) => void;
  setVoiceOk: (ok: boolean) => void;
  setBackendUnreachable: (unreachable: boolean) => void;
  setAppError: (error: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  theme: (localStorage.getItem('theme') as 'light' | 'dark') || 'light',
  sessionId: null,
  voiceOk: true, // Default to true, updated on app mount
  backendUnreachable: false,
  appError: null,
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
  setSessionId: (sessionId) => set({ sessionId }),
  setVoiceOk: (voiceOk) => set({ voiceOk }),
  setBackendUnreachable: (backendUnreachable) => set({ backendUnreachable }),
  setAppError: (appError) => set({ appError }),
}));
