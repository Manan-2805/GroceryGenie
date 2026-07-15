import { ShieldCheck, Home as HomeIcon, Briefcase, PlusCircle } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { CustomDialog } from '../components/CustomDialog';
import { orderService, addressService, Address } from '../services/api';

export const Checkout: React.FC = () => {
  const navigate = useNavigate();
  const [savedAddresses, setSavedAddresses] = useState<Address[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState<string | null>(null);
  const [useNewAddress, setUseNewAddress] = useState(false);
  const [loading, setLoading] = useState(true);

  // New Address Form State
  const [newAddress, setNewAddress] = useState({
    line1: '',
    line2: '',
    city: '',
    state: '',
    postal_code: '',
    country: 'Ireland',
    label: 'Home',
  });

  const [placing, setPlacing] = useState(false);

  // Custom Dialog States
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTitle, setDialogTitle] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');
  const [onDialogClose, setOnDialogClose] = useState<(() => void) | undefined>(undefined);

  const showDialog = (title: string, message: string, onCloseCallback?: () => void) => {
    setDialogTitle(title);
    setDialogMessage(message);
    setOnDialogClose(() => onCloseCallback);
    setDialogOpen(true);
  };

  const fetchAddresses = async () => {
    try {
      const list = await addressService.list();
      setSavedAddresses(list);
      if (list.length > 0) {
        const defaultAddr = list.find((a) => a.is_default) || list[0];
        if (defaultAddr) {
          setSelectedAddressId(defaultAddr.id);
        } else {
          setUseNewAddress(true);
        }
      } else {
        setUseNewAddress(true);
      }
    } catch (e) {
      console.error(e);
      setUseNewAddress(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAddresses();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    let finalAddressPayload: Record<string, any>;

    if (useNewAddress) {
      if (!newAddress.line1 || !newAddress.city || !newAddress.postal_code) {
        showDialog('Error', 'Please fill out all required address fields.');
        return;
      }
      finalAddressPayload = {
        line1: newAddress.line1,
        line2: newAddress.line2 || '',
        city: newAddress.city,
        state: newAddress.state || '',
        postal_code: newAddress.postal_code,
        country: newAddress.country,
        label: newAddress.label,
      };
    } else {
      const selected = savedAddresses.find((a) => a.id === selectedAddressId);
      if (!selected) {
        showDialog('Error', 'Please select a delivery address.');
        return;
      }
      finalAddressPayload = {
        line1: selected.line1,
        line2: selected.line2 || '',
        city: selected.city,
        state: selected.state || '',
        postal_code: selected.postal_code,
        country: selected.country,
        label: selected.label,
      };
    }
    
    setPlacing(true);
    try {
      // The backend place_order endpoint expects PlaceOrderPayload which is { delivery_address: dict }
      const order = await orderService.place(finalAddressPayload);
      showDialog('Success', `Order placed successfully! Order ID: ${order.id}`, () => {
        navigate('/orders');
      });
    } catch (err) {
      console.error(err);
      showDialog('Error', 'Failed to place order. Make sure your cart is not empty.');
    } finally {
      setPlacing(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading checkout...</div>;
  }

  return (
    <div className="max-w-xl mx-auto py-8 px-4 space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Checkout</h1>
        <p className="text-sm text-gray-500">Select or enter a delivery address to complete your order</p>
      </div>

      <form onSubmit={handleSubmit} className="border rounded-2xl glassmorphism p-6 shadow-md space-y-6">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200 flex items-center gap-2 border-b pb-3 dark:border-gray-900">
          <ShieldCheck className="text-purple-600" />
          <span>Delivery Details</span>
        </h3>

        {/* Saved Addresses Section */}
        {savedAddresses.length > 0 && (
          <div className="space-y-3">
            <label className="text-xs font-bold text-gray-500 uppercase">Select Delivery Address</label>
            <div className="grid grid-cols-1 gap-3">
              {savedAddresses.map((addr) => {
                const isSelected = !useNewAddress && selectedAddressId === addr.id;
                return (
                  <div
                    key={addr.id}
                    onClick={() => {
                      setUseNewAddress(false);
                      setSelectedAddressId(addr.id);
                    }}
                    className={`p-4 border rounded-xl cursor-pointer transition flex items-start gap-3 bg-white dark:bg-gray-950 ${
                      isSelected
                        ? 'border-purple-600 ring-1 ring-purple-600'
                        : 'border-gray-200 dark:border-gray-800 hover:bg-gray-50/50 dark:hover:bg-gray-900/20'
                    }`}
                  >
                    <div className="mt-0.5 text-purple-600">
                      {addr.label?.toLowerCase() === 'work' ? <Briefcase size={16} /> : <HomeIcon size={16} />}
                    </div>
                    <div className="flex-1 text-xs">
                      <p className="font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wide text-[9px] mb-1">
                        {addr.label} {addr.is_default && '(Default)'}
                      </p>
                      <p className="font-medium text-gray-800 dark:text-gray-300">
                        {addr.line1} {addr.line2 ? `, ${addr.line2}` : ''}
                      </p>
                      <p className="text-gray-400 mt-0.5">
                        {addr.city}, {addr.state} - {addr.postal_code}, {addr.country}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
            
            <button
              type="button"
              onClick={() => setUseNewAddress(true)}
              className={`flex items-center gap-1.5 text-xs font-bold transition mt-2 ${
                useNewAddress
                  ? 'text-purple-600'
                  : 'text-gray-500 hover:text-purple-600'
              }`}
            >
              <PlusCircle size={16} />
              <span>Deliver to a new address</span>
            </button>
          </div>
        )}

        {/* New Address Fields */}
        {useNewAddress && (
          <div className="space-y-4 pt-2 border-t dark:border-gray-900">
            {savedAddresses.length > 0 && (
              <div className="flex justify-between items-center">
                <span className="text-xs font-bold text-purple-600">New Delivery Address</span>
                <button
                  type="button"
                  onClick={() => {
                    setUseNewAddress(false);
                    if (savedAddresses.length > 0 && !selectedAddressId) {
                      const firstAddr = savedAddresses[0];
                      if (firstAddr) {
                        setSelectedAddressId(firstAddr.id);
                      }
                    }
                  }}
                  className="text-xs font-bold text-gray-400 hover:text-gray-600"
                >
                  Cancel
                </button>
              </div>
            )}

            {/* Address Label */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-500 uppercase">Address Label</label>
                <input
                  type="text"
                  required
                  value={newAddress.label}
                  onChange={(e) => setNewAddress((a) => ({ ...a, label: e.target.value }))}
                  placeholder="Home, Office, Work"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-500 uppercase">Country</label>
                <input
                  type="text"
                  required
                  value={newAddress.country}
                  onChange={(e) => setNewAddress((a) => ({ ...a, country: e.target.value }))}
                  placeholder="Ireland"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
                />
              </div>
            </div>

            {/* Line 1 */}
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-500 uppercase">Street Address</label>
              <input
                type="text"
                required
                value={newAddress.line1}
                onChange={(e) => setNewAddress((a) => ({ ...a, line1: e.target.value }))}
                placeholder="123 Main Street"
                className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
              />
            </div>

            {/* Line 2 */}
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-500 uppercase">Apt, Suite, Unit (Optional)</label>
              <input
                type="text"
                value={newAddress.line2}
                onChange={(e) => setNewAddress((a) => ({ ...a, line2: e.target.value }))}
                placeholder="Apt 4B"
                className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
              />
            </div>

            {/* City & State & Postal Code */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-500 uppercase">City</label>
                <input
                  type="text"
                  required
                  value={newAddress.city}
                  onChange={(e) => setNewAddress((a) => ({ ...a, city: e.target.value }))}
                  placeholder="Dublin"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-500 uppercase">State</label>
                <input
                  type="text"
                  required
                  value={newAddress.state}
                  onChange={(e) => setNewAddress((a) => ({ ...a, state: e.target.value }))}
                  placeholder="Leinster"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-500 uppercase">Postal Code</label>
                <input
                  type="text"
                  required
                  value={newAddress.postal_code}
                  onChange={(e) => setNewAddress((a) => ({ ...a, postal_code: e.target.value }))}
                  placeholder="D01 A234"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs"
                />
              </div>
            </div>
          </div>
        )}

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

      <CustomDialog
        isOpen={dialogOpen}
        title={dialogTitle}
        message={dialogMessage}
        onClose={() => {
          setDialogOpen(false);
          if (onDialogClose) onDialogClose();
        }}
      />
    </div>
  );
};
