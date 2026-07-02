import React, { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Link, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ShoppingCart, User, Settings as SettingsIcon, LogOut } from 'lucide-react';

import { VoiceSessionProvider } from './contexts/VoiceSessionContext';
import { ChatBubble } from './components/ChatBubble';
import { Home } from './pages/Home';
import { Catalog } from './pages/Catalog';
import { ItemDetail } from './pages/ItemDetail';
import { Cart } from './pages/Cart';
import { Checkout } from './pages/Checkout';
import { Orders } from './pages/Orders';
import { Settings } from './pages/Settings';
import { SellerDashboard } from './pages/SellerDashboard';
import { Login } from './pages/Login';
import { authService } from './services/api';

const queryClient = new QueryClient();

// Internal Listener for programmatical navigation intents emitted by the Agent
const NavigationListener: React.FC = () => {
  const navigate = useNavigate();
  useEffect(() => {
    const handleNavigation = (event: any) => {
      const { path } = event.detail;
      if (path) {
        navigate(path);
      }
    };
    window.addEventListener('agent-navigate', handleNavigation);
    return () => window.removeEventListener('agent-navigate', handleNavigation);
  }, [navigate]);

  return null;
};

export const AppContent: React.FC = () => {
  const [user, setUser] = useState<{ name: string; role: string } | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchProfile = async () => {
    try {
      const data = await authService.getMe();
      setUser({ name: data.name, role: data.role });
    } catch (e) {
      // Not logged in
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  const handleLoginSuccess = (name: string, role: string) => {
    setUser({ name, role });
  };

  const handleLogout = async () => {
    try {
      await authService.logout();
      setUser(null);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRoleChange = async (newRole: 'customer' | 'seller') => {
    try {
      // Re-login mock to switch roles
      const data = await authService.mockLogin(newRole);
      setUser({ name: data.name, role: data.role });
    } catch (e) {
      console.error(e);
    }
  };

  // Initialize Dark Theme configuration
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme');
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = savedTheme || (systemDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-950 text-gray-400 text-sm font-semibold">
        Loading GrocerGo application...
      </div>
    );
  }

  if (!user) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-white dark:bg-[#0f1015] text-gray-800 dark:text-gray-200 transition-colors duration-300">
      <NavigationListener />

      {/* Global Navigation Header */}
      <header className="sticky top-0 z-40 border-b border-gray-100 dark:border-gray-900 bg-white/80 dark:bg-[#0f1015]/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link to="/" className="text-xl font-black bg-gradient-to-r from-purple-600 to-indigo-600 bg-clip-text text-transparent">
              GrocerGo
            </Link>
            
            <nav className="hidden md:flex items-center gap-6 text-sm font-semibold text-gray-600 dark:text-gray-400">
              <Link to="/items" className="hover:text-purple-600 transition">Catalog</Link>
              {user.role === 'customer' && (
                <>
                  <Link to="/orders" className="hover:text-purple-600 transition">Orders</Link>
                  <Link to="/cart" className="hover:text-purple-600 transition">Cart</Link>
                </>
              )}
              {user.role === 'seller' && (
                <Link to="/seller" className="hover:text-purple-600 transition text-amber-500">Seller Panel</Link>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-4">
            {/* Cart Icon (Customer Only) */}
            {user.role === 'customer' && (
              <Link to="/cart" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-900 rounded-lg relative text-gray-600 dark:text-gray-400">
                <ShoppingCart size={20} />
              </Link>
            )}

            {/* Profile Info */}
            <div className="flex items-center gap-2 border-l pl-4 dark:border-gray-900">
              <div className="text-right hidden sm:block">
                <p className="text-xs font-bold text-gray-800 dark:text-gray-200">{user.name}</p>
                <p className="text-[10px] text-purple-600 capitalize font-medium">{user.role}</p>
              </div>
              
              <Link to="/settings" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-900 rounded-lg text-gray-600 dark:text-gray-400">
                <SettingsIcon size={20} />
              </Link>

              <button onClick={handleLogout} className="p-2 hover:bg-red-50 dark:hover:bg-red-950/20 rounded-lg text-red-500">
                <LogOut size={20} />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Page Layout Wrapper */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-4 pb-24">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/items" element={<Catalog />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/settings" element={<Settings userRole={user.role} onRoleChange={handleRoleChange} />} />
          <Route path="/seller" element={<SellerDashboard />} />
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
