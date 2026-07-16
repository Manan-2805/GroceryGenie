import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ShoppingCart, Settings as SettingsIcon, LogOut, ShoppingBag } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  Link,
  useNavigate,
  useLocation,
  Navigate,
} from 'react-router-dom';

import { ChatBubble } from './components/ChatBubble';
import { VoiceSessionProvider } from './contexts/VoiceSessionContext';
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

// Internal Listener for programmatical navigation intents emitted by the Agent
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

  const handleLogout = async () => {
    try {
      await authService.logout();
      setUser(null);
    } catch (e) {
      console.error(e);
    }
  };

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

  // Initialize Dark Theme configuration
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  if (loading && !isMaintenancePage && !isErrorPage) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950 text-gray-400 text-sm font-semibold">
        Loading GroceryGenie application...
      </div>
    );
  }

  if (user === null && !isMaintenancePage && !isErrorPage) {
    return <Login onLoginSuccess={fetchProfile} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-white dark:bg-[#0f1015] text-gray-800 dark:text-gray-200 transition-colors duration-300">
      <NavigationListener />

      {/* Global Navigation Header */}
      <header className="sticky top-0 z-40 border-b border-gray-100 dark:border-gray-900 bg-white/80 dark:bg-[#0f1015]/80 backdrop-blur-md">
        <div className="w-full px-4 md:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link
              to={user?.role === 'seller' ? '/seller' : '/'}
              className="text-xl font-black bg-gradient-to-r from-purple-600 to-indigo-600 bg-clip-text text-transparent"
            >
              GroceryGenie
            </Link>

            <nav className="hidden md:flex items-center gap-6 text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-450">
              {user?.role === 'customer' && (
                <Link to="/items" className="hover:text-purple-600 transition">
                  Catalog
                </Link>
              )}
              {user?.role === 'seller' && (
                <>
                  <Link to="/seller" className="hover:text-purple-600 transition">
                    Dashboard
                  </Link>
                  <Link to="/fulfillment" className="hover:text-purple-600 transition">
                    Fulfillment Queue
                  </Link>
                  <Link to="/inventory" className="hover:text-purple-600 transition">
                    Inventory
                  </Link>
                  <Link to="/analysis" className="hover:text-purple-600 transition">
                    Analysis
                  </Link>
                </>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-4">
            {/* Cart & Orders Icons (Customer Only) */}
            {user?.role === 'customer' && (
              <>
                <Link
                  to="/orders"
                  className="p-2 hover:bg-gray-100 dark:hover:bg-gray-900 rounded-lg relative text-gray-600 dark:text-gray-400"
                >
                  <ShoppingBag size={20} />
                </Link>
                <Link
                  to="/cart"
                  className="p-2 hover:bg-gray-100 dark:hover:bg-gray-900 rounded-lg relative text-gray-600 dark:text-gray-400"
                >
                  <ShoppingCart size={20} />
                </Link>
              </>
            )}

            {/* Profile Info */}
            {user && (
              <div className="flex items-center gap-2 border-l pl-4 dark:border-gray-900">
                <div className="text-right hidden sm:block">
                  <p className="text-xs font-bold text-gray-800 dark:text-gray-200">{user.name}</p>
                  <p className="text-[10px] text-purple-600 capitalize font-medium">{user.role}</p>
                </div>

                <Link
                  to="/settings"
                  className="p-2 hover:bg-gray-100 dark:hover:bg-gray-900 rounded-lg text-gray-600 dark:text-gray-400"
                >
                  <SettingsIcon size={20} />
                </Link>

                <button
                  id="logout-btn"
                  onClick={handleLogout}
                  className="p-2 hover:bg-red-50 dark:hover:bg-red-950/20 rounded-lg text-red-500"
                >
                  <LogOut size={20} />
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Page Layout Wrapper */}
      <main className="flex-1 w-full px-4 md:px-8 pb-24">
        <Routes>
          <Route
            path="/"
            element={user?.role === 'seller' ? <Navigate to="/seller" /> : <Home />}
          />
          <Route
            path="/items"
            element={user?.role === 'seller' ? <Navigate to="/seller" /> : <Catalog />}
          />
          <Route
            path="/items/:id"
            element={user?.role === 'seller' ? <Navigate to="/seller" /> : <ItemDetail />}
          />
          <Route
            path="/cart"
            element={user?.role === 'customer' ? <Cart /> : <Navigate to="/seller" />}
          />
          <Route
            path="/checkout"
            element={user?.role === 'customer' ? <Checkout /> : <Navigate to="/seller" />}
          />
          <Route
            path="/orders"
            element={user?.role === 'customer' ? <Orders /> : <Navigate to="/seller" />}
          />
          <Route path="/settings" element={<Settings {...settingsProps} />} />
          <Route
            path="/seller"
            element={user?.role === 'seller' ? <SellerDashboard /> : <Navigate to="/items" />}
          />
          <Route
            path="/fulfillment"
            element={user?.role === 'seller' ? <FulfillmentQueue /> : <Navigate to="/items" />}
          />
          <Route
            path="/inventory"
            element={user?.role === 'seller' ? <InventoryManagement /> : <Navigate to="/items" />}
          />
          <Route
            path="/analysis"
            element={user?.role === 'seller' ? <SellerAnalysis /> : <Navigate to="/items" />}
          />
          <Route path="/maintenance" element={<Maintenance />} />
          <Route path="/error" element={<ErrorPage />} />
        </Routes>
      </main>

      {/* Floating Chatbubble Overlay */}
      <ChatBubble />
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
