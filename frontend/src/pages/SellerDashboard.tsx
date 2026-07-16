import {
  ShoppingBag,
  Box,
  DollarSign,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
} from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { orderService, productService, Product, Order } from '../services/api';

export const SellerDashboard: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [lowStockProducts, setLowStockProducts] = useState<Product[]>([]);
  const [totalProductsCount, setTotalProductsCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      // 1. Fetch recent orders (page 1, limit 5)
      const ordersData = await orderService.listSellerQueue(1, 5);
      setOrders(ordersData.items);

      // 2. Fetch low stock products (page 1, limit 5)
      const lowStockData = await productService.listSeller(undefined, undefined, 'low', 1, 5);
      setLowStockProducts(lowStockData.items);

      // 3. Fetch total products to show catalog count
      const allSellerProducts = await productService.listSeller(
        undefined,
        undefined,
        undefined,
        1,
        100
      );
      setTotalProductsCount(allSellerProducts.total);
    } catch (e) {
      console.error('Error fetching dashboard data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchDashboardData();
  }, []);

  // Compute stats
  const totalSales = orders.reduce((sum, o) => sum + (o.status === 'delivered' ? o.total : 0), 0);
  const activeOrdersCount = orders.filter((o) => o.status !== 'delivered').length;

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading seller dashboard...</div>;
  }

  return (
    <div className="w-full min-h-screen bg-gray-50/50 dark:bg-gray-950 text-left">
      <div className="max-w-6xl mx-auto py-8 px-4 space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">
            Seller Dashboard
          </h1>
          <p className="text-sm text-gray-500">
            Monitor order fulfillment, catalog stock alerts, and revenue summaries
          </p>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                Gross Sales
              </span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <DollarSign size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">
                €{totalSales.toFixed(2)}
              </p>
              <p className="text-[10px] text-gray-400 mt-1 font-semibold">
                From completed delivered orders
              </p>
            </div>
          </div>

          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                Active Fulfillment
              </span>
              <span className="p-2 bg-amber-50 dark:bg-amber-950/20 text-amber-500 rounded-xl">
                <ShoppingBag size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-amber-500">{activeOrdersCount} Pending</p>
              <p className="text-[10px] text-gray-400 mt-1 font-semibold">
                Orders awaiting delivery status updates
              </p>
            </div>
          </div>

          <div className="p-6 border rounded-2xl bg-white dark:bg-gray-900 shadow-sm relative overflow-hidden group hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                My Catalog
              </span>
              <span className="p-2 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
                <Box size={18} />
              </span>
            </div>
            <div className="mt-4">
              <p className="text-2xl font-black text-gray-800 dark:text-gray-200">
                {totalProductsCount} Products
              </p>
              <p className="text-[10px] text-gray-400 mt-1 font-semibold">
                Active items in the customer store
              </p>
            </div>
          </div>
        </div>

        {/* Dashboard Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Recent Pending Orders */}
          <div className="border border-gray-200 dark:border-gray-800 rounded-2xl p-6 bg-white dark:bg-gray-900 shadow-sm space-y-4">
            <div className="flex justify-between items-center pb-2 border-b dark:border-gray-800">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200 flex items-center gap-2">
                <ShoppingBag size={16} className="text-purple-600" />
                <span>Recent Pending Orders</span>
              </h3>
              <Link
                to="/fulfillment"
                className="flex items-center gap-1 text-[10px] font-bold text-purple-600 hover:text-purple-700 uppercase"
              >
                <span>View All Queue</span>
                <ArrowRight size={12} />
              </Link>
            </div>

            {orders.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-8">
                No orders awaiting fulfillment.
              </p>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-800">
                {orders.map((order) => (
                  <div
                    key={order.id}
                    className="py-3 flex justify-between items-center gap-4 text-xs"
                  >
                    <div>
                      <p className="font-bold text-gray-800 dark:text-gray-200">
                        Order #{order.id.slice(0, 8)}
                      </p>
                      <p className="text-[10px] text-gray-400 font-semibold mt-0.5">
                        Received: {new Date(order.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-black text-gray-800 dark:text-gray-200">
                        €{order.total.toFixed(2)}
                      </p>
                      <span className="text-[9px] font-bold px-2 py-0.5 rounded bg-amber-50 text-amber-600 dark:bg-amber-950/20 dark:text-amber-400 uppercase mt-1 inline-block">
                        {order.status.replace(/_/g, ' ')}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Low Stock Alerts */}
          <div className="border border-gray-200 dark:border-gray-800 rounded-2xl p-6 bg-white dark:bg-gray-900 shadow-sm space-y-4">
            <div className="flex justify-between items-center pb-2 border-b dark:border-gray-800">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200 flex items-center gap-2">
                <AlertTriangle size={16} className="text-amber-500" />
                <span>Low Stock Alerts (&lt; 10)</span>
              </h3>
              <Link
                to="/inventory"
                className="flex items-center gap-1 text-[10px] font-bold text-purple-600 hover:text-purple-700 uppercase"
              >
                <span>Manage Stock</span>
                <ArrowRight size={12} />
              </Link>
            </div>

            {lowStockProducts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center gap-1 text-xs">
                <CheckCircle2 size={24} className="text-green-500" />
                <p className="font-bold text-gray-800 dark:text-gray-200">Inventory Healthy</p>
                <p className="text-[10px] text-gray-400">
                  All products have sufficient stock levels
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-800">
                {lowStockProducts.map((p) => (
                  <div key={p.id} className="py-3 flex justify-between items-center gap-4 text-xs">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-gray-50 dark:bg-gray-900/40 rounded p-1 flex items-center justify-center flex-shrink-0">
                        <img
                          src={
                            typeof p.image_url === 'string' && p.image_url.trim().length > 0
                              ? p.image_url
                              : 'https://via.placeholder.com/80'
                          }
                          alt={p.name}
                          className="h-full object-contain rounded"
                        />
                      </div>
                      <div>
                        <p className="font-bold text-gray-800 dark:text-gray-200">{p.name}</p>
                        <p className="text-[10px] text-gray-400 font-semibold">{p.category}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <span
                        className={`px-2 py-0.5 rounded font-black text-xs ${p.stock === 0 ? 'bg-red-50 text-red-600 dark:bg-red-950/20' : 'bg-amber-50 text-amber-600 dark:bg-amber-950/20'}`}
                      >
                        {p.stock === 0 ? 'OUT' : `${p.stock} left`}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
