import {
  Home,
  MessageSquare,
  Package,
  ShoppingCart,
  ShoppingBag,
  LayoutDashboard,
  ClipboardList,
  Boxes,
  BarChart3,
  Settings as SettingsIcon,
  LogOut,
  Menu,
  X,
  Moon,
  Sun,
} from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { useUIStore } from '../store/uiStore';

type AppSidebarProps = {
  user: { name: string; role: string };
  onLogout: () => void;
};

type NavItem = {
  to: string;
  label: string;
  icon: React.ReactNode;
};

const NavLink: React.FC<{
  item: NavItem;
  active: boolean;
}> = ({ item, active }) => (
  <Link
    to={item.to}
    className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 border-l-2 ${
      active
        ? 'border-accent bg-accent-bg text-accent'
        : 'border-transparent text-muted hover:bg-accent-bg hover:text-accent'
    }`}
  >
    <span className="shrink-0 opacity-80">{item.icon}</span>
    <span>{item.label}</span>
  </Link>
);

export const AppSidebar: React.FC<AppSidebarProps> = ({ user, onLogout }) => {
  const location = useLocation();
  const { theme, toggleTheme } = useUIStore();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname === path || location.pathname.startsWith(`${path}/`);
  };

  const generalItems: NavItem[] = [
    { to: '/agent', label: 'Assistant', icon: <MessageSquare size={18} /> },
    { to: '/settings', label: 'Settings', icon: <SettingsIcon size={18} /> },
  ];

  const shoppingItems: NavItem[] = [
    { to: '/', label: 'Home', icon: <Home size={18} /> },
    { to: '/items', label: 'Catalog', icon: <Package size={18} /> },
    { to: '/cart', label: 'Cart', icon: <ShoppingCart size={18} /> },
    { to: '/orders', label: 'Orders', icon: <ShoppingBag size={18} /> },
  ];

  const sellerItems: NavItem[] = [
    { to: '/seller', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
    { to: '/fulfillment', label: 'Fulfillment', icon: <ClipboardList size={18} /> },
    { to: '/inventory', label: 'Inventory', icon: <Boxes size={18} /> },
    { to: '/analysis', label: 'Analysis', icon: <BarChart3 size={18} /> },
  ];

  function handleCloseMobile() {
    setMobileOpen(false);
  }

  function handleOpenMobile() {
    setMobileOpen(true);
  }

  function handleLogoutClick() {
    setMobileOpen(false);
    onLogout();
  }

  const sidebarContent = (
    <div className="flex flex-col h-full">
      <div className="px-5 py-5 border-b border-border/60">
        <Link
          to={user.role === 'seller' ? '/seller' : '/'}
          className="text-lg font-semibold text-accent tracking-tight"
        >
          GroceryGenie
        </Link>
        <p className="text-[10px] uppercase tracking-wider text-muted mt-1 font-medium">
          Enterprise Shopping
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        <div>
          <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            General
          </p>
          <div className="space-y-0.5">
            {generalItems.map((item) => (
              <NavLink key={item.to} item={item} active={isActive(item.to)} />
            ))}
          </div>
        </div>

        {user.role === 'customer' && (
          <div>
            <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
              Shopping
            </p>
            <div className="space-y-0.5">
              {shoppingItems.map((item) => (
                <NavLink key={item.to} item={item} active={isActive(item.to)} />
              ))}
            </div>
          </div>
        )}

        {user.role === 'seller' && (
          <div>
            <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
              Seller
            </p>
            <div className="space-y-0.5">
              {sellerItems.map((item) => (
                <NavLink key={item.to} item={item} active={isActive(item.to)} />
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className="px-3 py-4 border-t border-border/60 space-y-2">
        <div className="px-3 py-2">
          <p className="text-sm font-semibold text-heading truncate">{user.name}</p>
          <span className="inline-block mt-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md bg-accent-bg text-accent capitalize">
            {user.role}
          </span>
        </div>

        <button
          type="button"
          onClick={toggleTheme}
          className="btn-ghost w-full justify-start"
          aria-label="Toggle theme"
        >
          {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
          <span>{theme === 'light' ? 'Dark mode' : 'Light mode'}</span>
        </button>

        <button
          id="logout-btn"
          type="button"
          onClick={handleLogoutClick}
          className="btn-ghost w-full justify-start text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
        >
          <LogOut size={16} />
          <span>Logout</span>
        </button>
      </div>
    </div>
  );

  return (
    <>
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 h-14 px-4 flex items-center justify-between glass-sidebar border-b border-border/60 border-r-0">
        <Link
          to={user.role === 'seller' ? '/seller' : '/'}
          className="text-base font-semibold text-accent"
        >
          GroceryGenie
        </Link>
        <button
          type="button"
          onClick={handleOpenMobile}
          className="btn-ghost p-2"
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>
      </div>

      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm"
          onClick={handleCloseMobile}
          aria-hidden="true"
        />
      )}

      <aside
        className={`md:hidden fixed top-0 left-0 z-[70] h-full w-64 glass-sidebar transform transition-transform duration-250 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <button
          type="button"
          onClick={handleCloseMobile}
          className="absolute top-4 right-3 btn-ghost p-1.5"
          aria-label="Close menu"
        >
          <X size={18} />
        </button>
        {sidebarContent}
      </aside>

      <aside className="hidden md:flex flex-col w-60 shrink-0 h-screen sticky top-0 glass-sidebar z-40">
        {sidebarContent}
      </aside>
    </>
  );
};
