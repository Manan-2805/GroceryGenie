import { Trash2, ShoppingCart, ArrowRight } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { CustomDialog } from '../components/CustomDialog';
import { DataTable, Column } from '../components/DataTable';
import { cartService, CartItem } from '../services/api';

export const Cart: React.FC = () => {
  const [items, setItems] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  // Custom Dialog States
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTitle, setDialogTitle] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');

  const showDialog = (title: string, message: string) => {
    setDialogTitle(title);
    setDialogMessage(message);
    setDialogOpen(true);
  };

  const closeDialog = () => {
    setDialogOpen(false);
  };

  const dialogProps = {
    isOpen: dialogOpen,
    onClose: closeDialog,
    title: dialogTitle,
    message: dialogMessage,
  };

  const fetchCart = async () => {
    try {
      const data = await cartService.get();
      setItems(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchCart();
  }, []);

  const handleUpdateQuantity = async (productId: string, currentQty: number, change: number) => {
    const newQty = currentQty + change;
    if (newQty <= 0) return;

    setUpdatingId(productId);
    try {
      await cartService.update(productId, newQty);
      await fetchCart();
    } catch (e: unknown) {
      console.error(e);
      const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      showDialog(
        'Error',
        detail !== undefined && detail !== null
          ? typeof detail === 'string'
            ? detail
            : JSON.stringify(detail)
          : 'Failed to update cart quantity.'
      );
    } finally {
      setUpdatingId(null);
    }
  };

  const handleRemoveItem = async (productId: string) => {
    setUpdatingId(productId);
    try {
      await cartService.remove(productId);
      await fetchCart();
    } catch (e) {
      console.error(e);
      showDialog('Error', 'Failed to remove item from cart.');
    } finally {
      setUpdatingId(null);
    }
  };

  const total = items.reduce((sum, item) => sum + item.product.price * item.quantity, 0);

  // Define table columns
  const columns: Column<CartItem>[] = [
    {
      key: 'image',
      header: 'Product',
      render: (_, item) => (
        <div className="w-12 h-12 bg-gray-50 dark:bg-gray-900/40 rounded-lg p-1 flex items-center justify-center">
          <img
            src={
              typeof item.product.image_url === 'string' && item.product.image_url.trim().length > 0
                ? item.product.image_url
                : 'https://via.placeholder.com/80'
            }
            alt={item.product.name}
            className="h-full object-contain rounded"
          />
        </div>
      ),
    },
    {
      key: 'name',
      header: 'Name',
      sortable: true,
      filterable: true,
      render: (_, item) => (
        <span className="font-semibold text-gray-800 dark:text-gray-200">{item.product.name}</span>
      ),
    },
    {
      key: 'price',
      header: 'Price',
      sortable: true,
      render: (_, item) => `€${item.product.price.toFixed(2)}`,
    },
    {
      key: 'quantity',
      header: 'Quantity',
      sortable: true,
      render: (_, item) => (
        <div className="flex items-center border dark:border-gray-800 rounded-lg overflow-hidden bg-white dark:bg-gray-950 w-fit">
          <button
            disabled={updatingId !== null || item.quantity <= 1}
            onClick={() => {
              void handleUpdateQuantity(item.product_id, item.quantity, -1);
            }}
            className="px-2 py-0.5 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-50 text-xs font-bold"
          >
            -
          </button>
          <span className="px-2 text-xs font-bold">{item.quantity}</span>
          <button
            disabled={updatingId !== null || item.quantity >= item.product.stock}
            onClick={() => {
              void handleUpdateQuantity(item.product_id, item.quantity, 1);
            }}
            className="px-2 py-0.5 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-50 text-xs font-bold"
          >
            +
          </button>
        </div>
      ),
    },
    {
      key: 'total',
      header: 'Total',
      sortable: true,
      render: (_, item) => (
        <span className="font-bold text-accent dark:text-accent">
          €{(item.product.price * item.quantity).toFixed(2)}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Action',
      render: (_, item) => (
        <button
          disabled={updatingId !== null}
          onClick={() => {
            void handleRemoveItem(item.product_id);
          }}
          className="text-red-500 hover:text-red-600 p-1 rounded transition"
        >
          <Trash2 size={16} />
        </button>
      ),
    },
  ];

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading your cart...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-semibold text-gray-800 dark:text-gray-200">Shopping Cart</h1>
        <p className="text-sm text-gray-500">Review your grocery items before checking out</p>
      </div>

      {items.length === 0 ? (
        <div className="p-12 border border-dashed rounded-2xl text-center space-y-4">
          <ShoppingCart className="mx-auto text-gray-300 dark:text-gray-700" size={48} />
          <p className="text-gray-400 text-sm">Your shopping cart is empty.</p>
          <Link
            to="/items"
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-bold transition inline-block"
          >
            Start Shopping
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          {/* Items Table */}
          <div className="lg:col-span-2">
            <DataTable
              columns={columns}
              data={items}
              noDataMessage="Your cart is empty"
              exportFileName="shopping_cart"
            />
          </div>

          {/* Cart Summary */}
          <div className="glass-card p-6 space-y-6">
            <h3 className="font-semibold text-lg text-gray-800 dark:text-gray-200">Cart Summary</h3>

            <div className="divide-y divide-gray-100 dark:divide-gray-900 space-y-3">
              <div className="flex justify-between text-sm py-2">
                <span className="text-gray-500">Subtotal</span>
                <span className="font-semibold text-gray-800 dark:text-gray-200">
                  €{total.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-sm py-2">
                <span className="text-gray-500">Delivery</span>
                <span className="font-semibold text-gray-800 dark:text-gray-200">FREE</span>
              </div>
              <div className="flex justify-between text-base font-semibold py-3">
                <span>Total</span>
                <span className="text-accent dark:text-accent">€{total.toFixed(2)}</span>
              </div>
            </div>

            <Link
              to="/checkout"
              className="w-full py-3 bg-accent hover:bg-accent-hover text-white rounded-xl font-bold transition flex justify-center items-center gap-2 shadow-lg"
            >
              <span>Proceed to Checkout</span>
              <ArrowRight size={18} />
            </Link>
          </div>
        </div>
      )}

      <CustomDialog {...dialogProps} />
    </div>
  );
};
