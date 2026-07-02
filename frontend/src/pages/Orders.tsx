import React, { useEffect, useState } from 'react';
import { ShoppingBag, Clock } from 'lucide-react';
import { orderService, Order } from '../services/api';

export const Orders: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);

  const fetchOrders = async () => {
    try {
      const data = await orderService.list();
      setOrders(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  const handleOrderClick = async (orderId: string) => {
    try {
      const detail = await orderService.get(orderId);
      setSelectedOrder(detail);
    } catch (e) {
      console.error(e);
      alert('Failed to load order details.');
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'placed':
        return 'bg-blue-100 text-blue-600 dark:bg-blue-950/40 dark:text-blue-400';
      case 'packed':
        return 'bg-amber-100 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400';
      case 'out_for_delivery':
        return 'bg-purple-100 text-purple-600 dark:bg-purple-950/40 dark:text-purple-400';
      case 'delivered':
        return 'bg-green-100 text-green-600 dark:bg-green-950/40 dark:text-green-400';
      default:
        return 'bg-gray-100 text-gray-600 dark:bg-gray-950/40 dark:text-gray-400';
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading your orders...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Your Orders</h1>
        <p className="text-sm text-gray-500">Track and view history of your grocery orders</p>
      </div>

      {orders.length === 0 ? (
        <div className="p-12 border border-dashed rounded-2xl text-center space-y-4">
          <ShoppingBag className="mx-auto text-gray-300 dark:text-gray-700" size={48} />
          <p className="text-gray-400 text-sm">You haven't placed any orders yet.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {/* Orders List */}
          <div className="md:col-span-2 space-y-4">
            {orders.map((order) => (
              <div
                key={order.id}
                onClick={() => handleOrderClick(order.id)}
                className={`p-5 border rounded-2xl cursor-pointer transition shadow-sm hover:border-purple-600 ${
                  selectedOrder?.id === order.id
                    ? 'border-purple-600 bg-purple-50/20 dark:bg-purple-950/10'
                    : 'glassmorphism'
                }`}
              >
                <div className="flex justify-between items-start gap-4">
                  <div className="space-y-1">
                    <p className="text-xs font-bold text-gray-400">ORDER ID: {order.id.slice(0, 8)}...</p>
                    <p className="text-sm font-extrabold text-gray-800 dark:text-gray-200">
                      Total: €{order.total.toFixed(2)}
                    </p>
                    <div className="flex items-center gap-1.5 text-xs text-gray-500">
                      <Clock size={12} />
                      <span>{new Date(order.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>

                  <span className={`text-xs font-bold px-3 py-1 rounded-full ${getStatusColor(order.status)}`}>
                    {order.status.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Order Details Panel */}
          <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-6">
            <h3 className="font-extrabold text-lg text-gray-800 dark:text-gray-200 border-b pb-3 dark:border-gray-900">
              Order Details
            </h3>

            {selectedOrder ? (
              <div className="space-y-4 text-sm">
                <div className="space-y-1">
                  <p className="text-xs text-gray-400">DELIVERY ADDRESS</p>
                  <p className="font-medium text-gray-800 dark:text-gray-200">
                    {selectedOrder.delivery_address.street}, {selectedOrder.delivery_address.city}
                  </p>
                  <p className="text-xs text-gray-500">{selectedOrder.delivery_address.postalCode}</p>
                </div>

                <div className="space-y-2">
                  <p className="text-xs text-gray-400">ITEMS</p>
                  <div className="divide-y divide-gray-100 dark:divide-gray-900 max-h-48 overflow-y-auto">
                    {selectedOrder.items.map((item) => (
                      <div key={item.id} className="py-2 flex justify-between gap-4">
                        <div>
                          <p className="font-semibold text-xs text-gray-800 dark:text-gray-200">
                            {item.product?.name || 'Unknown Product'}
                          </p>
                          <p className="text-[10px] text-gray-500">Qty: {item.quantity}</p>
                        </div>
                        <span className="font-bold text-xs text-purple-600 dark:text-purple-400">
                          €{(item.price_at_purchase * item.quantity).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex justify-between items-center border-t dark:border-gray-900 pt-3">
                  <span className="text-xs text-gray-500">Total Paid</span>
                  <span className="font-black text-purple-600 dark:text-purple-400">
                    €{selectedOrder.total.toFixed(2)}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-8">
                Select an order from the list to view detailed summaries.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
