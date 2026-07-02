import React, { useEffect, useState } from 'react';
import { Search, Filter } from 'lucide-react';
import { Link } from 'react-router-dom';
import { productService, Product } from '../services/api';

export const Catalog: React.FC = () => {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  
  // Hardcoded standard categories for filters
  const categories = ['Dairy & Eggs', 'Produce', 'Pantry', 'Bakery', 'Beverages'];

  const fetchProducts = async () => {
    setLoading(true);
    try {
      const data = await productService.list(selectedCategory || undefined);
      setProducts(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, [selectedCategory]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) {
      fetchProducts();
      return;
    }
    // Filter locally based on search term
    const query = searchQuery.toLowerCase();
    setProducts((prev) =>
      prev.filter(
        (p) =>
          p.name.toLowerCase().includes(query) ||
          p.description.toLowerCase().includes(query) ||
          p.category.toLowerCase().includes(query)
      )
    );
  };

  return (
    <div className="space-y-6 py-6 px-4 max-w-5xl mx-auto text-left">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Catalog</h1>
        <p className="text-sm text-gray-500">Search and filter our premium grocery catalog</p>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row gap-4">
        {/* Search Input */}
        <form onSubmit={handleSearchSubmit} className="flex-1 flex border dark:border-gray-800 bg-white dark:bg-gray-950 rounded-xl overflow-hidden focus-within:ring-1 focus-within:ring-purple-600 shadow-sm">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search items by name, description..."
            className="flex-1 px-4 py-3 bg-transparent focus:outline-none text-sm"
          />
          <button type="submit" className="p-3 bg-purple-600 text-white hover:bg-purple-700 transition">
            <Search size={18} />
          </button>
        </form>

        {/* Category Selector */}
        <div className="flex gap-2 items-center overflow-x-auto pb-1">
          <button
            onClick={() => setSelectedCategory('')}
            className={`px-4 py-2 text-xs font-bold rounded-lg border transition ${
              selectedCategory === ''
                ? 'bg-purple-600 border-purple-600 text-white'
                : 'border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-600 dark:text-gray-400'
            }`}
          >
            All Categories
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`whitespace-nowrap px-4 py-2 text-xs font-bold rounded-lg border transition ${
                selectedCategory === cat
                  ? 'bg-purple-600 border-purple-600 text-white'
                  : 'border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 text-gray-600 dark:text-gray-400'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Products Grid */}
      {loading ? (
        <p className="text-sm text-gray-400">Loading catalog...</p>
      ) : products.length === 0 ? (
        <div className="p-12 border border-dashed rounded-2xl text-center text-gray-400">
          No matching products found in the catalog.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
          {products.map((product) => (
            <Link
              key={product.id}
              to={`/items/${product.id}`}
              className="group border border-gray-100 dark:border-gray-900 bg-white dark:bg-gray-950 hover:-translate-y-1 hover:shadow-lg rounded-2xl overflow-hidden shadow-sm flex flex-col transition duration-300"
            >
              {/* Product Image */}
              <div className="h-44 w-full bg-gray-50 dark:bg-gray-900/40 p-4 flex items-center justify-center border-b dark:border-gray-900">
                <img
                  src={product.image_url || 'https://via.placeholder.com/150'}
                  alt={product.name}
                  className="h-full object-contain group-hover:scale-105 transition duration-300"
                />
              </div>

              {/* Product Info */}
              <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                <div className="space-y-1">
                  <div className="flex justify-between items-center">
                    <span className="text-[9px] font-bold uppercase tracking-wider text-purple-600">
                      {product.category}
                    </span>
                    <span className="text-xs font-bold text-amber-500">
                      {product.avg_rating} ⭐
                    </span>
                  </div>
                  <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">
                    {product.name}
                  </h3>
                  <p className="text-xs text-gray-400 line-clamp-2">
                    {product.description}
                  </p>
                </div>

                <div className="flex justify-between items-center pt-2">
                  <span className="text-lg font-black text-purple-600 dark:text-purple-400">
                    €{product.price.toFixed(2)}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-900 font-semibold text-gray-500">
                    {product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
};
