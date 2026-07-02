import React, { useEffect, useState } from 'react';
import { LayoutDashboard, ShoppingBag, Plus, Trash2, Edit3 } from 'lucide-react';
import { orderService, productService, Product, Order } from '../services/api';

export const SellerDashboard: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  
  // New Product Form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [newProduct, setNewProduct] = useState({
    name: '',
    description: '',
    category: 'Produce',
    price: '',
    stock: '',
    image_url: '',
  });

  const categories = ['Dairy & Eggs', 'Produce', 'Pantry', 'Bakery', 'Beverages'];

  const fetchData = async () => {
    setLoading(true);
    try {
      const [productsData, ordersData] = await Promise.all([
        productService.list(),
        orderService.listSellerQueue(),
      ]);
      setProducts(productsData);
      setOrders(ordersData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleUpdateStatus = async (orderId: string, currentStatus: string) => {
    let nextStatus = '';
    if (currentStatus === 'placed') nextStatus = 'packed';
    else if (currentStatus === 'packed') nextStatus = 'out_for_delivery';
    else if (currentStatus === 'out_for_delivery') nextStatus = 'delivered';

    if (!nextStatus) return;

    try {
      await orderService.updateStatus(orderId, nextStatus);
      await fetchData();
    } catch (e) {
      console.error(e);
      alert('Failed to update status.');
    }
  };

  const handleAddProductSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProduct.name || !newProduct.price || !newProduct.stock) {
      alert('Please fill out Name, Price and Stock.');
      return;
    }

    try {
      await productService.create({
        name: newProduct.name,
        description: newProduct.description,
        category: newProduct.category,
        price: parseFloat(newProduct.price),
        stock: parseInt(newProduct.stock, 10),
        image_url: newProduct.image_url || undefined,
      });
      setShowAddForm(false);
      setNewProduct({
        name: '',
        description: '',
        category: 'Produce',
        price: '',
        stock: '',
        image_url: '',
      });
      await fetchData();
    } catch (err) {
      console.error(err);
      alert('Failed to create product.');
    }
  };

  const handleDeleteProduct = async (id: string) => {
    if (!confirm('Are you sure you want to delete this product?')) return;
    try {
      await productService.delete(id);
      await fetchData();
    } catch (e) {
      console.error(e);
      alert('Failed to delete product.');
    }
  };

  // KPIs
  const totalSales = products.reduce((sum, p) => sum + p.price * p.sold_count, 0);
  const pendingOrdersCount = orders.filter((o) => o.status !== 'delivered').length;

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading seller dashboard...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-8 text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Seller Dashboard</h1>
        <p className="text-sm text-gray-500">Manage your orders and coordinate inventory</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div className="p-6 border rounded-2xl glassmorphism shadow-sm">
          <p className="text-xs font-bold text-gray-400 uppercase">Estimated Sales Revenue</p>
          <p className="text-3xl font-black text-purple-600 dark:text-purple-400 mt-2">
            €{totalSales.toFixed(2)}
          </p>
        </div>
        <div className="p-6 border rounded-2xl glassmorphism shadow-sm">
          <p className="text-xs font-bold text-gray-400 uppercase">Products catalog</p>
          <p className="text-3xl font-black text-purple-600 dark:text-purple-400 mt-2">
            {products.length} Items
          </p>
        </div>
        <div className="p-6 border rounded-2xl glassmorphism shadow-sm">
          <p className="text-xs font-bold text-gray-400 uppercase">Pending Fulfillment Orders</p>
          <p className="text-3xl font-black text-amber-500 mt-2">
            {pendingOrdersCount} Active
          </p>
        </div>
      </div>

      {/* Grid: Orders & Products */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
        {/* Pending Orders Fulfillment queue */}
        <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-4">
          <h3 className="font-extrabold text-lg text-gray-800 dark:text-gray-200 flex items-center gap-2 border-b pb-3 dark:border-gray-900">
            <ShoppingBag className="text-purple-600" />
            <span>Fulfillment Queue</span>
          </h3>

          {orders.length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">No orders awaiting fulfillment.</p>
          ) : (
            <div className="space-y-4 max-h-[400px] overflow-y-auto pr-1">
              {orders.map((order) => (
                <div key={order.id} className="p-4 border dark:border-gray-900 rounded-xl bg-white dark:bg-gray-950/20 space-y-3">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-xs font-bold text-gray-400">ORDER {order.id.slice(0, 8)}...</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Address: {order.delivery_address.street}, {order.delivery_address.city}
                      </p>
                    </div>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-200">
                      {order.status}
                    </span>
                  </div>

                  <div className="border-t dark:border-gray-900 pt-2 flex justify-between items-center">
                    <span className="text-xs font-semibold text-gray-500">
                      Value: €{order.total.toFixed(2)}
                    </span>
                    
                    {order.status !== 'delivered' && (
                      <button
                        onClick={() => handleUpdateStatus(order.id, order.status)}
                        className="px-3 py-1 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition"
                      >
                        {order.status === 'placed' && 'Mark as Packed'}
                        {order.status === 'packed' && 'Mark Out for Delivery'}
                        {order.status === 'out_for_delivery' && 'Mark Delivered'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Inventory CRUD */}
        <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-4">
          <div className="flex justify-between items-center border-b pb-3 dark:border-gray-900">
            <h3 className="font-extrabold text-lg text-gray-800 dark:text-gray-200 flex items-center gap-2">
              <LayoutDashboard className="text-purple-600" />
              <span>Inventory CRUD</span>
            </h3>
            <button
              onClick={() => setShowAddForm(!showAddForm)}
              className="p-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition"
            >
              <Plus size={16} />
            </button>
          </div>

          {/* Add Product Form */}
          {showAddForm && (
            <form onSubmit={handleAddProductSubmit} className="p-4 border dark:border-gray-900 rounded-xl bg-gray-50 dark:bg-gray-900/40 space-y-3">
              <h4 className="text-xs font-bold uppercase text-purple-600">New Inventory Product</h4>
              
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">Product Name</label>
                <input
                  type="text"
                  required
                  value={newProduct.name}
                  onChange={(e) => setNewProduct((p) => ({ ...p, name: e.target.value }))}
                  placeholder="Fresh Organic Strawberries"
                  className="w-full px-3 py-1.5 border dark:border-gray-800 bg-transparent rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-gray-400">Price (€)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={newProduct.price}
                    onChange={(e) => setNewProduct((p) => ({ ...p, price: e.target.value }))}
                    placeholder="3.99"
                    className="w-full px-3 py-1.5 border dark:border-gray-800 bg-transparent rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-gray-400">Stock Qty</label>
                  <input
                    type="number"
                    required
                    value={newProduct.stock}
                    onChange={(e) => setNewProduct((p) => ({ ...p, stock: e.target.value }))}
                    placeholder="24"
                    className="w-full px-3 py-1.5 border dark:border-gray-800 bg-transparent rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">Category</label>
                <select
                  value={newProduct.category}
                  onChange={(e) => setNewProduct((p) => ({ ...p, category: e.target.value }))}
                  className="w-full px-3 py-1.5 border dark:border-gray-800 bg-transparent rounded-lg text-xs focus:outline-none"
                >
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-gray-400">Description</label>
                <textarea
                  value={newProduct.description}
                  onChange={(e) => setNewProduct((p) => ({ ...p, description: e.target.value }))}
                  placeholder="Organic, sweet strawberries..."
                  rows={2}
                  className="w-full px-3 py-1.5 border dark:border-gray-800 bg-transparent rounded-lg text-xs focus:outline-none"
                />
              </div>

              <button
                type="submit"
                className="w-full py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition"
              >
                Add to Catalog
              </button>
            </form>
          )}

          {/* Products List */}
          <div className="space-y-3 max-h-[400px] overflow-y-auto pr-1">
            {products.map((p) => (
              <div key={p.id} className="flex justify-between items-center gap-4 p-3 border dark:border-gray-900 rounded-xl">
                <div>
                  <h4 className="font-extrabold text-xs text-gray-800 dark:text-gray-200">{p.name}</h4>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    Price: €{p.price.toFixed(2)} | Stock: {p.stock} | Sold: {p.sold_count}
                  </p>
                </div>
                <button
                  onClick={() => handleDeleteProduct(p.id)}
                  className="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 rounded-lg transition"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
