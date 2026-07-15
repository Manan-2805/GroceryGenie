import { Clock, MapPin, Eye, ArrowRight, CheckCircle2 } from 'lucide-react';
import React, { useEffect, useState } from 'react';

import { CustomDialog } from '../components/CustomDialog';
import { DataTable, Column } from '../components/DataTable';
import { SellerNav } from '../components/SellerNav';
import { orderService, Order } from '../services/api';

export const FulfillmentQueue: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [orderDetails, setOrderDetails] = useState<Record<string, Order>>({});
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  // Custom Dialog States
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTitle, setDialogTitle] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');

  const showDialog = (title: string, message: string) => {
    setDialogTitle(title);
    setDialogMessage(message);
    setDialogOpen(true);
  };

  const fetchOrders = async (pageNum: number = page) => {
    try {
      const data = await orderService.listSellerQueue(pageNum, 10);
      setOrders(data.items);
      setTotalPages(data.pages);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, [page]);

  const handleSelectOrder = async (orderId: string) => {
    setSelectedOrderId(orderId);
    if (!orderDetails[orderId]) {
      try {
        const detail = await orderService.get(orderId);
        setOrderDetails((prev) => ({ ...prev, [orderId]: detail }));
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleUpdateStatus = async (orderId: string, currentStatus: string) => {
    let nextStatus: 'placed' | 'packed' | 'out_for_delivery' | 'delivered' | '' = '';
    if (currentStatus === 'placed') nextStatus = 'packed';
    else if (currentStatus === 'packed') nextStatus = 'out_for_delivery';
    else if (currentStatus === 'out_for_delivery') nextStatus = 'delivered';

    if (!nextStatus) return;

    try {
      const updated = await orderService.updateStatus(orderId, nextStatus);
      // Update locally
      setOrders((prev) => prev.map((o) => (o.id === orderId ? { ...o, status: nextStatus } : o)));
      setOrderDetails((prev) => ({ ...prev, [orderId]: updated }));
      showDialog('Success', `Order status updated to "${nextStatus.replace(/_/g, ' ')}".`);
    } catch (e) {
      console.error(e);
      showDialog('Error', 'Failed to update order status.');
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

  const getStatusButtonText = (status: string) => {
    switch (status) {
      case 'placed':
        return 'Mark Packed';
      case 'packed':
        return 'Mark Out for Delivery';
      case 'out_for_delivery':
        return 'Mark Delivered';
      default:
        return '';
    }
  };

  // Define columns for DataTable
  const columns: Column<Order>[] = [
    {
      key: 'id',
      header: 'Order ID',
      sortable: true,
      filterable: true,
      render: (val) => <span className="font-mono text-xs font-bold">{String(val).slice(0, 8)}...</span>,
    },
    {
      key: 'created_at',
      header: 'Received On',
      sortable: true,
      render: (val) => (
        <span className="flex items-center gap-1 text-xs">
          <Clock size={12} className="text-gray-400" />
          {new Date(val).toLocaleString()}
        </span>
      ),
    },
    {
      key: 'total',
      header: 'Total Value',
      sortable: true,
      render: (val) => <span className="font-bold text-purple-600 dark:text-purple-400">€{Number(val).toFixed(2)}</span>,
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      filterable: true,
      filterType: 'select',
      filterOptions: ['placed', 'packed', 'out_for_delivery', 'delivered'],
      render: (val) => (
        <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase ${getStatusColor(val)}`}>
          {String(val).replace(/_/g, ' ')}
        </span>
      ),
    },
    {
      key: 'action',
      header: 'Action',
      render: (_, item) => (
        <button
          onClick={() => handleSelectOrder(item.id)}
          className={`flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-bold transition ${
            selectedOrderId === item.id
              ? 'bg-purple-600 text-white'
              : 'bg-purple-100 hover:bg-purple-200 text-purple-600 dark:bg-purple-950/40 dark:hover:bg-purple-950/70 dark:text-purple-400'
          }`}
        >
          <Eye size={12} />
          <span>Fulfill</span>
        </button>
      ),
    },
  ];

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading fulfillment queue...</div>;
  }

  const selectedOrder = orders.find((o) => o.id === selectedOrderId);
  const selectedDetails = selectedOrderId ? orderDetails[selectedOrderId] : null;

  return (
    <div className="w-full min-h-screen bg-gray-50/50 dark:bg-gray-950 text-left">
      <SellerNav />
      <div className="max-w-6xl mx-auto py-8 px-4 space-y-6">
        <div>
          <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Fulfillment Queue</h1>
          <p className="text-sm text-gray-500">Manage orders, update packing statuses, and coordinate deliveries</p>
        </div>

        <DataTable
          columns={columns}
          data={orders}
          noDataMessage="No orders in the fulfillment queue"
          exportFileName="fulfillment_queue"
        />

        {totalPages > 1 && (
          <div className="flex justify-center items-center gap-4">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-4 py-2 text-xs font-bold rounded-lg border border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 disabled:opacity-40 transition"
            >
              Previous
            </button>
            <span className="text-xs text-gray-500 font-semibold">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-4 py-2 text-xs font-bold rounded-lg border border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 disabled:opacity-40 transition"
            >
              Next
            </button>
          </div>
        )}

        {/* Selected Order Breakdown */}
        {selectedOrder && (
          <div className="border border-purple-200 dark:border-purple-900/50 rounded-2xl p-6 bg-white dark:bg-gray-900 shadow-md space-y-6">
            <div className="flex flex-wrap justify-between items-center gap-4 border-b border-gray-100 dark:border-gray-800 pb-4">
              <div>
                <h3 className="text-lg font-extrabold text-gray-800 dark:text-gray-200">
                  Fulfill Order <span className="font-mono text-purple-600 dark:text-purple-400">#{selectedOrder.id.slice(0, 8)}</span>
                </h3>
                <p className="text-xs text-gray-400 font-semibold flex items-center gap-1.5 mt-1">
                  <Clock size={12} />
                  Received on: {new Date(selectedOrder.created_at).toLocaleString()}
                </p>
              </div>

              {/* Status Update Actions */}
              {selectedOrder.status !== 'delivered' ? (
                <button
                  onClick={() => handleUpdateStatus(selectedOrder.id, selectedOrder.status)}
                  className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-bold transition shadow-md shadow-purple-500/20"
                >
                  <CheckCircle2 size={16} />
                  <span>{getStatusButtonText(selectedOrder.status)}</span>
                  <ArrowRight size={14} />
                </button>
              ) : (
                <span className="flex items-center gap-1 text-xs font-bold text-green-600 dark:text-green-400">
                  <CheckCircle2 size={16} />
                  <span>Delivered Successfully</span>
                </span>
              )}
            </div>

            {/* Status Change Timestamps Timeline */}
            <div className="p-4 border border-gray-100 dark:border-gray-800 rounded-xl bg-gray-50/50 dark:bg-gray-900/20 space-y-3">
              <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Delivery Status Log</h4>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
                <div>
                  <span className="text-gray-400 block font-semibold uppercase text-[9px]">1. Placed At</span>
                  <span className="font-bold text-gray-800 dark:text-gray-200">
                    {new Date(selectedOrder.created_at).toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400 block font-semibold uppercase text-[9px]">2. Packed At</span>
                  <span className="font-bold text-gray-800 dark:text-gray-200">
                    {selectedOrder.packed_at ? new Date(selectedOrder.packed_at).toLocaleString() : 'Pending'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400 block font-semibold uppercase text-[9px]">3. Shipped At</span>
                  <span className="font-bold text-gray-800 dark:text-gray-200">
                    {selectedOrder.out_for_delivery_at ? new Date(selectedOrder.out_for_delivery_at).toLocaleString() : 'Pending'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400 block font-semibold uppercase text-[9px]">4. Delivered At</span>
                  <span className="font-bold text-gray-800 dark:text-gray-200">
                    {selectedOrder.delivered_at ? new Date(selectedOrder.delivered_at).toLocaleString() : 'Pending'}
                  </span>
                </div>
              </div>
            </div>

            {/* Customer Details & Address */}
            {selectedDetails && selectedDetails.delivery_address && (
              <div className="p-4 border border-gray-100 dark:border-gray-800 rounded-xl bg-gray-50/50 dark:bg-gray-900/20 space-y-2">
                <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-500 uppercase">
                  <MapPin size={12} />
                  <span>Ship To: {selectedDetails.delivery_address.label || 'Home'}</span>
                </div>
                <p className="text-xs text-gray-800 dark:text-gray-300 font-medium">
                  {selectedDetails.delivery_address.line1}
                  {selectedDetails.delivery_address.line2 ? `, ${selectedDetails.delivery_address.line2}` : ''}
                </p>
                <p className="text-[10px] text-gray-400">
                  {selectedDetails.delivery_address.city}, {selectedDetails.delivery_address.state} - {selectedDetails.delivery_address.postal_code}, {selectedDetails.delivery_address.country}
                </p>
              </div>
            )}

            {/* Items List */}
            <div className="space-y-3">
              <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Items to Pack</h4>
              {!selectedDetails ? (
                <div className="text-xs text-gray-400 text-center py-4">Loading items...</div>
              ) : (
                <div className="divide-y divide-gray-100 dark:divide-gray-800 border border-gray-100 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-950/40 overflow-hidden">
                  {selectedDetails.items.map((item) => (
                    <div key={item.id} className="p-4 flex items-center justify-between gap-4 text-xs">
                      <div className="flex items-center gap-3">
                        {item.product?.image_url ? (
                          <img src={item.product.image_url} alt={item.product.name} className="w-10 h-10 rounded-lg object-cover" />
                        ) : (
                          <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/20 flex items-center justify-center font-bold text-purple-600">
                            {item.product?.name?.slice(0, 1) || 'P'}
                          </div>
                        )}
                        <div>
                          <p className="font-bold text-gray-800 dark:text-gray-200">
                            {item.product?.name || 'Unknown Product'}
                          </p>
                          <p className="text-[10px] text-gray-500 font-semibold">
                            €{item.price_at_purchase.toFixed(2)} each
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="font-bold text-purple-600 dark:text-purple-400">
                          Qty: {item.quantity}
                        </p>
                        <p className="text-[10px] text-gray-400">
                          Subtotal: €{(item.price_at_purchase * item.quantity).toFixed(2)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <CustomDialog
        isOpen={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={dialogTitle}
        message={dialogMessage}
      />
    </div>
  );
};
