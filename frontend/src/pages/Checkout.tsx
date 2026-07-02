import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
import { orderService } from '../services/api';

export const Checkout: React.FC = () => {
  const navigate = useNavigate();
  const [address, setAddress] = useState({
    street: '',
    city: '',
    postalCode: '',
  });
  const [placing, setPlacing] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!address.street || !address.city || !address.postalCode) {
      alert('Please fill out all address fields.');
      return;
    }
    
    setPlacing(true);
    try {
      const order = await orderService.place(address);
      alert(`Order placed successfully! Order ID: ${order.id}`);
      navigate('/orders');
    } catch (err) {
      console.error(err);
      alert('Failed to place order. Make sure your cart is not empty.');
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto py-8 px-4 space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Checkout</h1>
        <p className="text-sm text-gray-500">Provide your delivery address to complete order</p>
      </div>

      <form onSubmit={handleSubmit} className="border rounded-2xl glassmorphism p-6 shadow-md space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200 flex items-center gap-2 border-b pb-3 dark:border-gray-900">
          <ShieldCheck className="text-purple-600" />
          <span>Delivery Details</span>
        </h3>

        <div className="space-y-1">
          <label className="text-xs font-bold text-gray-500 uppercase">Street Address</label>
          <input
            type="text"
            required
            value={address.street}
            onChange={(e) => setAddress((a) => ({ ...a, street: e.target.value }))}
            placeholder="123 Main Street"
            className="w-full px-4 py-2 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-xs font-bold text-gray-500 uppercase">City</label>
            <input
              type="text"
              required
              value={address.city}
              onChange={(e) => setAddress((a) => ({ ...a, city: e.target.value }))}
              placeholder="Dublin"
              className="w-full px-4 py-2 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-sm"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-bold text-gray-500 uppercase">Postal Code</label>
            <input
              type="text"
              required
              value={address.postalCode}
              onChange={(e) => setAddress((a) => ({ ...a, postalCode: e.target.value }))}
              placeholder="D01 A234"
              className="w-full px-4 py-2 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-sm"
            />
          </div>
        </div>

        <div className="pt-4">
          <button
            type="submit"
            disabled={placing}
            className="w-full py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-bold transition flex justify-center items-center gap-2 shadow-lg"
          >
            {placing ? 'Placing Order...' : 'Place Secure Order'}
          </button>
        </div>
      </form>
    </div>
  );
};
