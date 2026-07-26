import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React, { useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';

import { AppSidebar } from './components/AppSidebar';
import { VoiceSessionProvider } from './contexts/VoiceSessionContext';
import { Agent } from './pages/Agent';
import { Cart } from './pages/Cart';
import { Catalog } from './pages/Catalog';
import { Checkout } from './pages/Checkout';
import { ErrorPage } from './pages/ErrorPage';
import { FulfillmentQueue } from './pages/FulfillmentQueue';
import { Home } from './pages/Home';
import { InventoryManagement } from './pages/InventoryManagement';
import { ItemDetail } from './pages/ItemDetail';
import { Login } from './pages/Login';
import { Maintenance } from './pages/Maintenance';
import { Orders } from './pages/Orders';
import { SellerAnalysis } from './pages/SellerAnalysis';
import { SellerDashboard } from './pages/SellerDashboard';
import { Settings } from './pages/Settings';
import { authService, healthService } from './services/api';
import { useUIStore } from './store/uiStore';

const queryClient = new QueryClient();

const NavigationListener: React.FC = () => {
  const navigate = useNavigate();
  useEffect(() => {
    const handleNavigation = (event: Event) => {
      const customEvent = event as CustomEvent<{ path?: string }>;
      const path = customEvent.detail?.path;
      if (typeof path === 'string' && path.trim().length > 0) {
        void navigate(path);
      }
    };
    window.addEventListener('agent-navigate', handleNavigation);
    return () => window.removeEventListener('agent-navigate', handleNavigation);
  }, [navigate]);

  return null;
};

export const AppContent: React.FC = () => {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log('[Dev Render] App / AppContent');
  }

  const { theme, backendUnreachable, appError } = useUIStore();
  const [user, setUser] = useState<{ name: string; role: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const isMaintenancePage = location.pathname === '/maintenance';
  const isErrorPage = location.pathname === '/error';
  const hasBackendUnreachable = backendUnreachable === true;
  const hasAppError = typeof appError === 'string' && appError.trim().length > 0;

  useEffect(() => {
    if (hasBackendUnreachable && location.pathname !== '/maintenance') {
      void navigate('/maintenance');
    } else if (!hasBackendUnreachable && location.pathname === '/maintenance') {
      void navigate('/');
    }

    if (hasAppError && location.pathname !== '/error') {
      void navigate('/error');
    } else if (!hasAppError && location.pathname === '/error') {
      void navigate('/');
    }
  }, [hasAppError, hasBackendUnreachable, location.pathname, navigate]);

  const fetchProfile = useCallback(async () => {
    try {
      const data = await authService.getMe();
      setUser({ name: data.name, role: data.role });
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      const data = await healthService.checkApiHealth();
      useUIStore.getState().setVoiceOk(data.voice_ok);
    } catch (error) {
      console.error('Health check failed', error);
      useUIStore.getState().setVoiceOk(false);
    }
  }, []);

  useEffect(() => {
    void fetchProfile();
    void checkHealth();
  }, [checkHealth, fetchProfile]);

  const handleLogout = useCallback(async () => {
    try {
      await authService.logout();
      setUser(null);
    } catch (e) {
      console.error(e);
    }
  }, []);

  async function handleRoleChange(newRole: 'customer' | 'seller') {
    try {
      await authService.switchRole(newRole);
      const data = await authService.getMe();
      setUser({ name: data.name, role: data.role });
    } catch (e) {
      console.error(e);
    }
  }

  const settingsProps = {
    userRole: user?.role ?? 'customer',
    onRoleChange: handleRoleChange,
  };

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  if (loading && !isMaintenancePage && !isErrorPage) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-app text-muted text-sm font-medium">
        Loading GroceryGenie application...
      </div>
    );
  }

  if (isMaintenancePage) {
    return <Maintenance />;
  }

  if (isErrorPage) {
    return <ErrorPage />;
  }

  if (user === null) {
    return <Login onLoginSuccess={fetchProfile} />;
  }

  return (
    <div className="min-h-screen flex bg-app text-heading transition-colors duration-300">
      <NavigationListener />
      <AppSidebar user={user} onLogout={handleLogout} />

      <main className="flex-1 min-w-0 h-screen overflow-y-auto pt-14 md:pt-0">
        <div className="w-full max-w-7xl mx-auto px-4 md:px-8 py-6 pb-24">
          <Routes>
            <Route
              path="/"
              element={user.role === 'seller' ? <Navigate to="/seller" /> : <Home />}
            />
            <Route
              path="/items"
              element={user.role === 'seller' ? <Navigate to="/seller" /> : <Catalog />}
            />
            <Route
              path="/items/:id"
              element={user.role === 'seller' ? <Navigate to="/seller" /> : <ItemDetail />}
            />
            <Route
              path="/cart"
              element={user.role === 'customer' ? <Cart /> : <Navigate to="/seller" />}
            />
            <Route
              path="/checkout"
              element={user.role === 'customer' ? <Checkout /> : <Navigate to="/seller" />}
            />
            <Route
              path="/orders"
              element={user.role === 'customer' ? <Orders /> : <Navigate to="/seller" />}
            />
            <Route path="/settings" element={<Settings {...settingsProps} />} />
            <Route
              path="/seller"
              element={user.role === 'seller' ? <SellerDashboard /> : <Navigate to="/items" />}
            />
            <Route
              path="/fulfillment"
              element={user.role === 'seller' ? <FulfillmentQueue /> : <Navigate to="/items" />}
            />
            <Route
              path="/inventory"
              element={user.role === 'seller' ? <InventoryManagement /> : <Navigate to="/items" />}
            />
            <Route
              path="/analysis"
              element={user.role === 'seller' ? <SellerAnalysis /> : <Navigate to="/items" />}
            />
            <Route path="/agent" element={<Agent />} />
            <Route path="/maintenance" element={<Maintenance />} />
            <Route path="/error" element={<ErrorPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
};

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <VoiceSessionProvider>
        <BrowserRouter>
          <AppContent />
        </BrowserRouter>
      </VoiceSessionProvider>
    </QueryClientProvider>
  );
}
