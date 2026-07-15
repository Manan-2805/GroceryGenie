import { LayoutDashboard, ShoppingBag, Box, BarChart2 } from 'lucide-react';
import React from 'react';
import { Link, useLocation } from 'react-router-dom';

export const SellerNav: React.FC = () => {
  const location = useLocation();
  const currentPath = location.pathname;

  const navItems = [
    { path: '/seller', label: 'Dashboard', icon: <LayoutDashboard size={16} /> },
    { path: '/fulfillment', label: 'Fulfillment Queue', icon: <ShoppingBag size={16} /> },
    { path: '/inventory', label: 'Inventory', icon: <Box size={16} /> },
    { path: '/analysis', label: 'Analysis', icon: <BarChart2 size={16} /> },
  ];

  return (
    <div className="w-full border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950/40 backdrop-blur sticky top-14 z-20">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex gap-6 overflow-x-auto py-3 scrollbar-hide">
          {navItems.map((item) => {
            const isActive = currentPath === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-2 text-xs font-bold uppercase tracking-wider transition-all whitespace-nowrap pb-1 border-b-2 ${
                  isActive
                    ? 'border-purple-600 text-purple-600 dark:text-purple-400'
                    : 'border-transparent text-gray-500 hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
};
