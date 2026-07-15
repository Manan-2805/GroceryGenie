import { ShoppingBag, Clock, MapPin, Star, Eye } from 'lucide-react';
import React, { useEffect, useState } from 'react';

import { DataTable, Column } from '../components/DataTable';
import { orderService, api, Order } from '../services/api';

export const Orders: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [orderDetails, setOrderDetails] = useState<Record<string, Order>>({});
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  
  // Rating states (keyed by "orderId:productId")
  const [ratings, setRatings] = useState<Record<string, { stars: number; comment: string; submitted: boolean; error: string | null }>>({});

  const fetchOrders = async (pageNum: number = page) => {
    try {
      const data = await orderService.list(pageNum, 10);
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
        
        // Populate existing ratings from the backend order detail payload
        detail.items.forEach((item) => {
          if (item.rating) {
            const key = `${orderId}:${item.product_id}`;
            setRatings((prev) => ({
              ...prev,
              [key]: {
                stars: item.rating.stars,
                comment: item.rating.comment || '',
                submitted: true,
                error: null,
              },
            }));
          }
        });
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleRatingSubmit = async (orderId: string, productId: string) => {
    const key = `${orderId}:${productId}`;
    const ratingData = ratings[key];
    if (!ratingData || ratingData.stars === 0) return;

    try {
      await api.post('/ratings', {
        order_id: orderId,
        product_id: productId,
        stars: ratingData.stars,
        comment: ratingData.comment || null,
      });

      setRatings((prev) => {
        const existing = prev[key] || { stars: 0, comment: '', submitted: false, error: null };
        return {
          ...prev,
          [key]: { ...existing, submitted: true, error: null },
        };
      });
    } catch (err: any) {
      console.error(err);
      setRatings((prev) => {
        const existing = prev[key] || { stars: 0, comment: '', submitted: false, error: null };
        return {
          ...prev,
          [key]: { ...existing, error: err.response?.data?.detail || 'Failed to submit rating.' },
        };
      });
    }
  };

  const handleStarClick = (orderId: string, productId: string, stars: number) => {
    const key = `${orderId}:${productId}`;
    setRatings((prev) => ({
      ...prev,
      [key]: {
        stars,
        comment: prev[key]?.comment || '',
        submitted: false,
        error: null,
      },
    }));
  };

  const handleCommentChange = (orderId: string, productId: string, comment: string) => {
    const key = `${orderId}:${productId}`;
    setRatings((prev) => ({
      ...prev,
      [key]: {
        stars: prev[key]?.stars || 0,
        comment,
        submitted: false,
        error: null,
      },
    }));
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

  const renderTimeline = (order: Order) => {
    const steps = ['placed', 'packed', 'out_for_delivery', 'delivered'];
    const currentStatus = order.status;
    const currentIndex = steps.indexOf(currentStatus);

    const stepTimestamps: Record<string, string | null> = {
      placed: order.created_at ? new Date(order.created_at).toLocaleString() : null,
      packed: order.packed_at ? new Date(order.packed_at).toLocaleString() : null,
      out_for_delivery: order.out_for_delivery_at ? new Date(order.out_for_delivery_at).toLocaleString() : null,
      delivered: order.delivered_at ? new Date(order.delivered_at).toLocaleString() : null,
    };

    return (
      <div className="py-6">
        <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-6 relative">
          {steps.map((step, idx) => {
            const isActive = idx <= currentIndex;
            const isCompleted = idx < currentIndex;
            const timeStr = stepTimestamps[step];
            const stepLabels: Record<string, string> = {
              placed: 'Ordered',
              packed: 'Packed',
              out_for_delivery: 'Out For Delivery',
              delivered: 'Delivered',
            };

            return (
              <div key={step} className="flex-1 flex md:flex-col items-center gap-3 md:gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all duration-300 z-10 ${
                    isActive
                      ? 'bg-purple-600 text-white border-purple-600 shadow-md shadow-purple-500/20'
                      : 'bg-white dark:bg-gray-950 text-gray-400 border-gray-200 dark:border-gray-800'
                  }`}
                >
                  {isCompleted ? '✓' : idx + 1}
                </div>
                <div className="text-left md:text-center">
                  <p className={`text-xs font-bold uppercase tracking-wider ${isActive ? 'text-purple-600' : 'text-gray-400'}`}>
                    {stepLabels[step]}
                  </p>
                  {timeStr ? (
                    <p className="text-[10px] text-gray-500 font-semibold mt-0.5">{timeStr}</p>
                  ) : (
                    <p className="text-[10px] text-gray-400 italic mt-0.5">Pending</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
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
      header: 'Placed On',
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
          <span>View</span>
        </button>
      ),
    },
  ];

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading your orders...</div>;
  }

  const selectedOrder = orders.find((o) => o.id === selectedOrderId);
  const selectedDetails = selectedOrderId ? orderDetails[selectedOrderId] : null;

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-8 text-left">
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
        <div className="space-y-6">
          {/* Order list using our reusable DataTable */}
          <DataTable
            columns={columns}
            data={orders}
            noDataMessage="No matching orders found"
            exportFileName="customer_orders"
          />

          {/* Pagination Controls */}
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

          {/* Details Section of the Selected Order */}
          {selectedOrder && (
            <div className="border border-purple-200 dark:border-purple-900/50 rounded-2xl p-6 bg-purple-50/5 dark:bg-purple-950/5 shadow-md space-y-6">
              <div className="flex flex-wrap justify-between items-center gap-4 border-b border-gray-200 dark:border-gray-800 pb-4">
                <div>
                  <h3 className="text-lg font-extrabold text-gray-800 dark:text-gray-200">
                    Order Details <span className="font-mono text-purple-600 dark:text-purple-400">#{selectedOrder.id.slice(0, 8)}</span>
                  </h3>
                  <p className="text-xs text-gray-400 font-semibold flex items-center gap-1.5 mt-1">
                    <Clock size={12} />
                    Placed on: {new Date(selectedOrder.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold px-3 py-1 rounded-full uppercase ${getStatusColor(selectedOrder.status)}`}>
                    {selectedOrder.status.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>

              {/* Status Timeline */}
              <div className="space-y-2 p-4 border dark:border-gray-900 rounded-xl bg-white dark:bg-gray-950/40">
                <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Delivery Timeline & Status Change Times</h4>
                {renderTimeline(selectedOrder)}
              </div>

              {/* Delivery Address Details */}
              {selectedDetails && selectedDetails.delivery_address && (
                <div className="space-y-2 p-4 border dark:border-gray-900 rounded-xl bg-white dark:bg-gray-950/40">
                  <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-500 uppercase">
                    <MapPin size={12} />
                    <span>Delivery Address: {selectedDetails.delivery_address.label || 'Home'}</span>
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

              {/* Items Breakdown */}
              <div className="space-y-3">
                <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Ordered Items & Review Ratings</h4>
                
                {!selectedDetails ? (
                  <div className="text-xs text-gray-400 text-center py-4">Loading items...</div>
                ) : (
                  <div className="divide-y divide-gray-100 dark:divide-gray-900 border dark:border-gray-900 rounded-xl bg-white dark:bg-gray-950/40 overflow-hidden">
                    {selectedDetails.items.map((item) => {
                      const isDelivered = selectedOrder.status === 'delivered';
                      const key = `${selectedOrder.id}:${item.product_id}`;
                      const ratingState = ratings[key] || { stars: 0, comment: '', submitted: false, error: null };

                      return (
                        <div key={item.id} className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                          <div className="flex items-center gap-3">
                            {item.product?.image_url ? (
                              <img src={item.product.image_url} alt={item.product.name} className="w-10 h-10 rounded-lg object-cover" />
                            ) : (
                              <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/20 flex items-center justify-center font-bold text-purple-600">
                                {item.product?.name?.slice(0, 1) || 'P'}
                              </div>
                            )}
                            <div>
                              <p className="font-bold text-xs text-gray-800 dark:text-gray-200">
                                {item.product?.name || 'Unknown Product'}
                              </p>
                              <p className="text-[10px] text-gray-500 font-semibold">
                                €{item.price_at_purchase.toFixed(2)} × {item.quantity}
                              </p>
                            </div>
                          </div>

                          <div className="flex flex-col md:items-end gap-2">
                            <span className="font-bold text-xs text-purple-600 dark:text-purple-400">
                              Subtotal: €{(item.price_at_purchase * item.quantity).toFixed(2)}
                            </span>

                            {/* Ratings Section for Delivered Orders */}
                            {isDelivered && item.product_id && (
                              <div className="border-t md:border-t-0 md:pt-0 pt-2 flex flex-col md:items-end gap-1.5 mt-1">
                                {ratingState.submitted ? (
                                  <span className="text-[10px] font-bold text-green-600 dark:text-green-400 flex items-center gap-1">
                                    ✓ Rated {ratingState.stars} Stars
                                  </span>
                                ) : (
                                  <div className="space-y-1.5 max-w-xs text-left md:text-right">
                                    <div className="flex items-center md:justify-end gap-1">
                                      <span className="text-[9px] font-bold text-gray-400 mr-1 uppercase">Rate:</span>
                                      {[1, 2, 3, 4, 5].map((star) => (
                                        <button
                                          key={star}
                                          type="button"
                                          onClick={() => handleStarClick(selectedOrder.id, item.product_id!, star)}
                                          className="focus:outline-none"
                                        >
                                          <Star
                                            size={14}
                                            className={
                                              star <= ratingState.stars
                                                ? 'fill-amber-400 text-amber-400'
                                                : 'text-gray-300 dark:text-gray-700'
                                            }
                                          />
                                        </button>
                                      ))}
                                    </div>
                                    
                                    {ratingState.stars > 0 && (
                                      <div className="flex flex-col gap-1 items-end">
                                        <input
                                          type="text"
                                          placeholder="Add comments (optional)"
                                          value={ratingState.comment}
                                          onChange={(e) => handleCommentChange(selectedOrder.id, item.product_id!, e.target.value)}
                                          className="w-48 px-2 py-0.5 border dark:border-gray-800 bg-transparent rounded text-[10px] focus:outline-none"
                                        />
                                        <button
                                          onClick={() => handleRatingSubmit(selectedOrder.id, item.product_id!)}
                                          className="px-2 py-0.5 bg-amber-500 hover:bg-amber-600 text-white rounded text-[9px] font-bold"
                                        >
                                          Submit Review
                                        </button>
                                      </div>
                                    )}

                                    {ratingState.error && (
                                      <p className="text-[9px] text-red-500 font-medium">{ratingState.error}</p>
                                    )}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
