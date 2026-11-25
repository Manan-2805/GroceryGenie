import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AxiosError } from 'axios';
import React, { useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Link, Routes, Route, useLocation, Navigate } from 'react-router-dom';

import { AppSidebar } from './components/AppSidebar';
import { Agent } from './pages/Agent';
import { Cart } from './pages/Cart';
import { Catalog } from './pages/Catalog';
import { Checkout } from './pages/Checkout';
import { FulfillmentQueue } from './pages/FulfillmentQueue';
import { Home } from './pages/Home';
import { InventoryManagement } from './pages/InventoryManagement';
import { ItemDetail } from './pages/ItemDetail';
import { Login } from './pages/Login';
import { Orders } from './pages/Orders';
import { SellerAnalysis } from './pages/SellerAnalysis';
import { SellerDashboard } from './pages/SellerDashboard';
import { Settings } from './pages/Settings';
import { authService } from './services/api';
import { useUIStore } from './store/uiStore';

const queryClient = new QueryClient();

export const AppContent: React.FC = () => {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log('[Dev Render] App / AppContent');
  }

  const { theme } = useUIStore();
  const [user, setUser] = useState<{ name: string; role: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const location = useLocation();

  const [connectionError, setConnectionError] = useState(false);

  const fetchProfile = useCallback(async () => {
    try {
      setConnectionError(false);
      const data = await authService.getMe();
      if ('name' in data && 'role' in data) {
        setUser({ name: data.name, role: data.role });
      } else {
        setUser(null);
      }
    } catch (error) {
      setUser(null);
      if (!(error instanceof AxiosError) || error.response?.status !== 401)
        setConnectionError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchProfile();
  }, [fetchProfile]);

  const handleLogout = useCallback(async () => {
    try {
      await authService.logout();
      setUser(null);
      useUIStore.getState().clearSession();
      queryClient.clear();
    } catch (e) {
      console.error(e);
    }
  }, []);

  async function handleRoleChange(newRole: 'customer' | 'seller') {
    try {
      await authService.switchRole(newRole);
      const data = await authService.getMe();
      if ('name' in data && 'role' in data) {
        setUser({ name: data.name, role: data.role });
      } else {
        setUser(null);
      }
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

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-app text-muted text-sm font-medium">
        Loading GroceryGenie application...
      </div>
    );
  }

  if (connectionError) {
    return (
      <main className="m-8 glass-card max-w-lg space-y-4 p-6">
        <h1 className="text-xl font-semibold">GroceryGenie is unavailable</h1>
        <p role="alert">The app could not reach the account service.</p>
        <button
          className="rounded-lg border px-3 py-2"
          type="button"
          onClick={() => void fetchProfile()}
        >
          Retry
        </button>
      </main>
    );
  }

  if (user === null) {
    if (location.pathname === '/items' || location.pathname.startsWith('/items/')) {
      return (
        <main className="w-full max-w-7xl mx-auto px-4 py-6">
          <Link to="/login" className="block mb-4 text-accent">
            Sign in
          </Link>
          <Routes>
            <Route path="/items" element={<Catalog />} />
            <Route path="/items/:id" element={<ItemDetail />} />
          </Routes>
        </main>
      );
    }
    return <Login />;
  }

  return (
    <div className="min-h-screen flex bg-app text-heading transition-colors duration-300">
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
          </Routes>
        </div>
      </main>
    </div>
  );
};

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
