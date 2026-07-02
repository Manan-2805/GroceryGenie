import React, { useEffect, useState } from 'react';
import { Trash2, ShoppingCart, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { cartService, CartItem } from '../services/api';

export const Cart: React.FC = () => {
  const [items, setItems] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

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
    fetchCart();
  }, []);

  const handleUpdateQuantity = async (productId: string, currentQty: number, change: number) => {
    const newQty = currentQty + change;
    if (newQty <= 0) return;
    
    setUpdatingId(productId);
    try {
      await cartService.update(productId, newQty);
      await fetchCart();
    } catch (e) {
      console.error(e);
      alert('Failed to update cart quantity.');
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
      alert('Failed to remove item from cart.');
    } finally {
      setUpdatingId(null);
    }
  };

  const total = items.reduce((sum, item) => sum + item.product.price * item.quantity, 0);

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading your cart...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Shopping Cart</h1>
        <p className="text-sm text-gray-500">Review your grocery items before checking out</p>
      </div>

      {items.length === 0 ? (
        <div className="p-12 border border-dashed rounded-2xl text-center space-y-4">
          <ShoppingCart className="mx-auto text-gray-300 dark:text-gray-700" size={48} />
          <p className="text-gray-400 text-sm">Your shopping cart is empty.</p>
          <Link
            to="/items"
            className="px-5 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition inline-block"
          >
            Start Shopping
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {/* Items List */}
          <div className="md:col-span-2 space-y-4">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-4 border rounded-2xl glassmorphism p-4 shadow-sm"
              >
                {/* Image */}
                <div className="w-16 h-16 bg-gray-50 dark:bg-gray-900/40 rounded-xl p-2 flex items-center justify-center flex-shrink-0">
                  <img
                    src={item.product.image_url || 'https://via.placeholder.com/80'}
                    alt={item.product.name}
                    className="h-full object-contain rounded"
                  />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <h4 className="font-extrabold text-sm text-gray-800 dark:text-gray-200 truncate">
                    {item.product.name}
                  </h4>
                  <p className="text-xs text-gray-400">€{item.product.price.toFixed(2)} each</p>
                </div>

                {/* Quantity Editor */}
                <div className="flex items-center border dark:border-gray-800 rounded-lg overflow-hidden bg-white dark:bg-gray-950">
                  <button
                    disabled={updatingId !== null || item.quantity <= 1}
                    onClick={() => handleUpdateQuantity(item.product_id, item.quantity, -1)}
                    className="px-2 py-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-50"
                  >
                    -
                  </button>
                  <span className="px-3 text-xs font-bold">{item.quantity}</span>
                  <button
                    disabled={updatingId !== null || item.quantity >= item.product.stock}
                    onClick={() => handleUpdateQuantity(item.product_id, item.quantity, 1)}
                    className="px-2 py-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-50"
                  >
                    +
                  </button>
                </div>

                {/* Total & Action */}
                <div className="text-right pl-2">
                  <p className="font-extrabold text-sm text-purple-600 dark:text-purple-400">
                    €{(item.product.price * item.quantity).toFixed(2)}
                  </p>
                  <button
                    disabled={updatingId !== null}
                    onClick={() => handleRemoveItem(item.product_id)}
                    className="text-red-500 hover:text-red-600 p-1 mt-1 rounded transition"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Cart Summary */}
          <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-6">
            <h3 className="font-extrabold text-lg text-gray-800 dark:text-gray-200">Cart Summary</h3>
            
            <div className="divide-y divide-gray-100 dark:divide-gray-900 space-y-3">
              <div className="flex justify-between text-sm py-2">
                <span className="text-gray-500">Subtotal</span>
                <span className="font-semibold text-gray-800 dark:text-gray-200">€{total.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-sm py-2">
                <span className="text-gray-500">Delivery</span>
                <span className="font-semibold text-gray-800 dark:text-gray-200">FREE</span>
              </div>
              <div className="flex justify-between text-base font-black py-3">
                <span>Total</span>
                <span className="text-purple-600 dark:text-purple-400">€{total.toFixed(2)}</span>
              </div>
            </div>

            <Link
              to="/checkout"
              className="w-full py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-bold transition flex justify-center items-center gap-2 shadow-lg"
            >
              <span>Proceed to Checkout</span>
              <ArrowRight size={18} />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};
