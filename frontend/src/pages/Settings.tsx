import { Trash2, MapPin, Plus, Check, PenLine } from 'lucide-react';
import React, { useCallback, useEffect, useState } from 'react';

import { DataTable } from '../components/DataTable';
import { memoryService, PersistentFact, addressService, Address } from '../services/api';
import { useUIStore } from '../store/uiStore';

type SettingsProps = {
  userRole: string;
  onRoleChange: (newRole: 'customer' | 'seller') => void;
};

export const Settings: React.FC<SettingsProps> = ({ userRole, onRoleChange }) => {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log('[Dev Render] Settings Page');
  }

  const { theme, setTheme } = useUIStore();

  const [facts, setFacts] = useState<PersistentFact[]>([]);
  const [loadingFacts, setLoadingFacts] = useState(false);

  // Address states
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [loadingAddresses, setLoadingAddresses] = useState(false);
  const [showAddressForm, setShowAddressForm] = useState(false);
  const [editingAddressId, setEditingAddressId] = useState<string | null>(null);
  const [addressForm, setAddressForm] = useState({
    label: 'Home',
    line1: '',
    line2: '',
    city: '',
    state: '',
    postal_code: '',
    country: 'Ireland',
  });

  const fetchFacts = useCallback(async () => {
    setLoadingFacts(true);
    try {
      const res = await memoryService.listFacts();
      setFacts(res);
    } catch (error) {
      console.error('Failed to load facts', error);
    } finally {
      setLoadingFacts(false);
    }
  }, []);

  const fetchAddresses = useCallback(async () => {
    if (userRole !== 'customer') return;
    setLoadingAddresses(true);
    try {
      const res = await addressService.list();
      setAddresses(res);
    } catch (error) {
      console.error('Failed to load addresses', error);
    } finally {
      setLoadingAddresses(false);
    }
  }, [userRole]);

  useEffect(() => {
    void fetchFacts();
    void fetchAddresses();
  }, [fetchAddresses, fetchFacts]);

  const handleDeleteFact = async (id: string) => {
    try {
      await memoryService.deleteFact(id);
      setFacts((prev) => prev.filter((f) => f.id !== id));
    } catch (e) {
      console.error('Failed to delete fact', e);
    }
  };

  const handleSaveAddress = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addressForm.label || !addressForm.line1 || !addressForm.city || !addressForm.postal_code) {
      return;
    }

    try {
      if (editingAddressId !== null) {
        await addressService.update(editingAddressId, {
          label: addressForm.label,
          line1: addressForm.line1,
          line2: addressForm.line2 || '',
          city: addressForm.city,
          state: addressForm.state,
          postal_code: addressForm.postal_code,
          country: addressForm.country,
        });
      } else {
        await addressService.create({
          label: addressForm.label,
          line1: addressForm.line1,
          line2: addressForm.line2 || '',
          city: addressForm.city,
          state: addressForm.state,
          postal_code: addressForm.postal_code,
          country: addressForm.country,
        });
      }
      setAddressForm({
        label: 'Home',
        line1: '',
        line2: '',
        city: '',
        state: '',
        postal_code: '',
        country: 'Ireland',
      });
      setEditingAddressId(null);
      setShowAddressForm(false);
      await fetchAddresses();
    } catch (e) {
      console.error('Failed to save address', e);
    }
  };

  const handleDeleteAddress = async (id: string) => {
    try {
      await addressService.delete(id);
      await fetchAddresses();
    } catch (e) {
      console.error('Failed to delete address', e);
    }
  };

  const handleSetDefaultAddress = async (id: string) => {
    try {
      await addressService.update(id, { is_default: true });
      await fetchAddresses();
    } catch (e) {
      console.error('Failed to set default address', e);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-8 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Settings</h1>
        <p className="text-sm text-gray-500">
          Manage your theme, role, addresses, and agent memories
        </p>
      </div>

      {/* Theme Control */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">Visual Theme</h3>
        <div className="flex gap-4">
          <button
            onClick={() => setTheme('light')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              theme === 'light'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Light Mode
          </button>
          <button
            onClick={() => setTheme('dark')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              theme === 'dark'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Dark Mode
          </button>
        </div>
      </div>

      {/* Role Switching */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">Role Selection</h3>
        <p className="text-xs text-gray-500">
          Switching your role will customize your view between buying and managing inventory.
        </p>
        <div className="flex gap-4">
          <button
            onClick={() => onRoleChange('customer')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              userRole === 'customer'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Customer View
          </button>
          <button
            onClick={() => onRoleChange('seller')}
            className={`px-4 py-2 rounded-lg font-semibold border transition ${
              userRole === 'seller'
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-300 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-700 dark:text-gray-300'
            }`}
          >
            Seller Panel
          </button>
        </div>
      </div>

      {/* Address Management (Customer Only) */}
      {userRole === 'customer' && (
        <div className="p-6 border rounded-xl glassmorphism space-y-6">
          <div className="flex justify-between items-center border-b pb-3 dark:border-gray-900">
            <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200 flex items-center gap-2">
              <MapPin size={20} className="text-purple-600" />
              <span>Saved Addresses</span>
            </h3>
            <button
              onClick={() => {
                setEditingAddressId(null);
                setAddressForm({
                  label: 'Home',
                  line1: '',
                  line2: '',
                  city: '',
                  state: '',
                  postal_code: '',
                  country: 'Ireland',
                });
                setShowAddressForm(!showAddressForm);
              }}
              className="flex items-center gap-1 px-3 py-1 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition shadow-sm"
            >
              <Plus size={14} />
              <span>Add New</span>
            </button>
          </div>

          {/* Add Address Form */}
          {showAddressForm && (
            <form
              onSubmit={handleSaveAddress}
              className="p-4 border dark:border-gray-900 rounded-xl bg-gray-50 dark:bg-gray-900/40 grid grid-cols-1 md:grid-cols-2 gap-4"
            >
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">
                  Label (e.g. Home, Office)
                </label>
                <input
                  type="text"
                  required
                  value={addressForm.label}
                  onChange={(e) => setAddressForm((f) => ({ ...f, label: e.target.value }))}
                  placeholder="Home"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">Street Address</label>
                <input
                  type="text"
                  required
                  value={addressForm.line1}
                  onChange={(e) => setAddressForm((f) => ({ ...f, line1: e.target.value }))}
                  placeholder="123 Main St"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">
                  Apt, Suite, Unit (Optional)
                </label>
                <input
                  type="text"
                  value={addressForm.line2}
                  onChange={(e) => setAddressForm((f) => ({ ...f, line2: e.target.value }))}
                  placeholder="Apt 4B"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">City</label>
                <input
                  type="text"
                  required
                  value={addressForm.city}
                  onChange={(e) => setAddressForm((f) => ({ ...f, city: e.target.value }))}
                  placeholder="Dublin"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">State / Province</label>
                <input
                  type="text"
                  value={addressForm.state}
                  onChange={(e) => setAddressForm((f) => ({ ...f, state: e.target.value }))}
                  placeholder="Leinster"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">Postal / Zip Code</label>
                <input
                  type="text"
                  required
                  value={addressForm.postal_code}
                  onChange={(e) => setAddressForm((f) => ({ ...f, postal_code: e.target.value }))}
                  placeholder="D02 X285"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="space-y-1 md:col-span-2">
                <label className="text-[10px] font-bold text-gray-400">Country</label>
                <input
                  type="text"
                  required
                  value={addressForm.country}
                  onChange={(e) => setAddressForm((f) => ({ ...f, country: e.target.value }))}
                  placeholder="Ireland"
                  className="w-full px-3 py-2 border dark:border-gray-800 bg-white dark:bg-gray-900 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="md:col-span-2 flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setEditingAddressId(null);
                    setAddressForm({
                      label: 'Home',
                      line1: '',
                      line2: '',
                      city: '',
                      state: '',
                      postal_code: '',
                      country: 'Ireland',
                    });
                    setShowAddressForm(false);
                  }}
                  className="px-4 py-2 border dark:border-gray-800 text-gray-500 rounded-lg text-xs font-bold hover:bg-gray-50 dark:hover:bg-gray-900 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-6 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition shadow-sm"
                >
                  Save Address
                </button>
              </div>
            </form>
          )}

          {/* Address List */}
          {loadingAddresses ? (
            <p className="text-sm text-gray-400">Loading addresses...</p>
          ) : addresses.length === 0 ? (
            <div className="p-4 border border-dashed rounded-lg text-center text-sm text-gray-400">
              No addresses saved yet. Click "Add New" to add one!
            </div>
          ) : (
            <DataTable
              columns={[
                {
                  key: 'label',
                  header: 'Label',
                  render: (val) => (
                    <span className="font-bold text-gray-800 dark:text-gray-200 uppercase text-xs">
                      {String(val)}
                    </span>
                  ),
                },
                {
                  key: 'line1',
                  header: 'Address',
                  render: (_, item) => (
                    <div className="text-xs">
                      <p className="font-semibold text-gray-800 dark:text-gray-300">{item.line1}</p>
                      {typeof item.line2 === 'string' && item.line2.trim().length > 0 ? (
                        <p className="text-gray-450">{item.line2}</p>
                      ) : null}
                      <p className="text-gray-450 dark:text-gray-500 mt-0.5">
                        {item.city}, {item.state} {item.postal_code}, {item.country}
                      </p>
                    </div>
                  ),
                },
                {
                  key: 'is_default',
                  header: 'Status',
                  render: (val) =>
                    val === true ? (
                      <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 border border-purple-200">
                        Default
                      </span>
                    ) : (
                      <span className="text-[9px] text-gray-450 dark:text-gray-500">
                        Alternative
                      </span>
                    ),
                },
                {
                  key: 'actions',
                  header: 'Actions',
                  render: (_, item) => (
                    <div className="flex gap-1.5 justify-center">
                      {!item.is_default && (
                        <button
                          onClick={() => handleSetDefaultAddress(item.id)}
                          title="Set Default"
                          className="p-1 text-purple-600 border border-purple-200 hover:bg-purple-50 dark:border-purple-900/40 dark:hover:bg-purple-950/20 rounded-lg transition"
                        >
                          <Check size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setEditingAddressId(item.id);
                          setAddressForm({
                            label: item.label,
                            line1: item.line1,
                            line2: item.line2 ?? '',
                            city: item.city,
                            state: item.state,
                            postal_code: item.postal_code,
                            country: item.country,
                          });
                          setShowAddressForm(true);
                        }}
                        title="Edit Address"
                        className="p-1 text-blue-600 border border-blue-200 hover:bg-blue-50 dark:border-blue-900/40 dark:hover:bg-blue-950/20 rounded-lg transition"
                      >
                        <PenLine size={14} />
                      </button>
                      <button
                        onClick={() => handleDeleteAddress(item.id)}
                        title="Delete Address"
                        className="p-1 text-red-500 border border-red-200 hover:bg-red-50 dark:border-red-900/40 dark:hover:bg-red-950/20 rounded-lg transition"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ),
                },
              ]}
              data={addresses}
              noDataMessage="No addresses match"
              exportFileName="saved_addresses"
            />
          )}
        </div>
      )}

      {/* Facts Memory manager */}
      <div className="p-6 border rounded-xl glassmorphism space-y-4">
        <h3 className="font-bold text-lg text-gray-800 dark:text-gray-200">
          What I remember about you
        </h3>
        <p className="text-xs text-gray-500">
          The agent automatically extracts standing facts (like dietary preferences and allergies)
          to customize responses. Delete items below if you no longer wish them to be remembered.
        </p>

        {loadingFacts ? (
          <p className="text-sm text-gray-400">Loading memories...</p>
        ) : facts.length === 0 ? (
          <div className="p-4 border border-dashed rounded-lg text-center text-sm text-gray-400">
            No memories stored yet. Try saying "remember I'm lactose intolerant" in chat!
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-900">
            {facts.map((fact) => (
              <div key={fact.id} className="py-3 flex items-center justify-between gap-4">
                <div>
                  <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 mr-3">
                    {fact.category}
                  </span>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    "{fact.fact_text}"
                  </span>
                </div>
                <button
                  onClick={() => handleDeleteFact(fact.id)}
                  className="p-1.5 hover:bg-red-50 dark:hover:bg-red-950/20 text-red-500 rounded-lg transition"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
