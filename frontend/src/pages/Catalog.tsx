import { Search, Filter, Star } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { productService, Product } from '../services/api';

export const Catalog: React.FC = () => {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  
  // Filter & Search states
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [minPrice, setMinPrice] = useState<string>('');
  const [maxPrice, setMaxPrice] = useState<string>('');
  const [minRating, setMinRating] = useState<number>(0);
  const [onlyInStock, setOnlyInStock] = useState<boolean>(false);
  
  // Sort states
  const [sortBy, setSortBy] = useState<string>('name');
  const [sortDir, setSortDir] = useState<string>('asc');

  // Pagination states
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  
  // Hardcoded standard categories for filters
  const categories = ['Dairy & Eggs', 'Produce', 'Pantry', 'Bakery', 'Beverages'];

  const fetchProducts = async (pageNum: number, append: boolean = false) => {
    if (loading) return;
    setLoading(true);
    try {
      const data = await productService.list(
        selectedCategory || undefined,
        undefined,
        pageNum,
        10, // 10 products per page
        minPrice ? parseFloat(minPrice) : undefined,
        maxPrice ? parseFloat(maxPrice) : undefined,
        minRating > 0 ? minRating : undefined,
        onlyInStock || undefined,
        searchQuery || undefined,
        sortBy || undefined,
        sortDir || undefined
      );

      if (append) {
        setProducts((prev) => {
          // Filter out duplicates to avoid duplicate key warnings
          const existingIds = new Set(prev.map(p => p.id));
          const newItems = data.items.filter(item => !existingIds.has(item.id));
          return [...prev, ...newItems];
        });
      } else {
        setProducts(data.items);
      }
      setTotalPages(data.pages);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Triggered when filters change: reset page to 1 and replace list
  useEffect(() => {
    setPage(1);
    fetchProducts(1, false);
  }, [selectedCategory, minPrice, maxPrice, minRating, onlyInStock, searchQuery, sortBy, sortDir]);

  // Triggered when infinite scroll increments page
  useEffect(() => {
    if (page > 1) {
      fetchProducts(page, true);
    }
  }, [page]);

  // Infinite scroll listener
  useEffect(() => {
    const handleScroll = () => {
      if (loading || page >= totalPages) return;

      const threshold = 200; // pixels from the bottom
      const docHeight = document.documentElement.scrollHeight;
      const scrolled = window.innerHeight + window.scrollY;

      if (docHeight - scrolled < threshold) {
        setPage((p) => p + 1);
      }
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [loading, page, totalPages]);

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 text-left space-y-6">
      <div>
        <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200">Catalog</h1>
        <p className="text-sm text-gray-500">Explore and search our premium grocery catalog</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Sidebar Filters */}
        <div className="lg:col-span-1 border dark:border-gray-800 bg-white dark:bg-gray-900 p-6 rounded-2xl shadow-sm h-fit space-y-6">
          <div className="flex items-center gap-2 pb-3 border-b dark:border-gray-800">
            <Filter size={18} className="text-purple-600" />
            <h3 className="font-bold text-gray-800 dark:text-gray-200">Filters & Sorting</h3>
          </div>

          {/* Search Query */}
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Search</label>
            <div className="relative">
              <input
                type="text"
                placeholder="Apple, Milk..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
              />
              <Search size={14} className="absolute left-3 top-3 text-gray-400" />
            </div>
          </div>

          {/* Category Dropdown */}
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Category</label>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
            >
              <option value="">All Categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Price Range */}
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Price Range (€)</label>
            <div className="flex gap-2 items-center">
              <input
                type="number"
                placeholder="Min"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
              />
              <span className="text-gray-400 text-xs">-</span>
              <input
                type="number"
                placeholder="Max"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
              />
            </div>
          </div>

          {/* Minimum Rating */}
          <div className="space-y-1.5">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Minimum Rating</label>
            <div className="flex gap-1.5">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  type="button"
                  onClick={() => setMinRating(minRating === star ? 0 : star)}
                  className="focus:outline-none"
                >
                  <Star
                    size={18}
                    className={
                      star <= minRating
                        ? 'fill-amber-400 text-amber-400'
                        : 'text-gray-300 dark:text-gray-700'
                    }
                  />
                </button>
              ))}
            </div>
          </div>

          {/* Stock Availability */}
          <div className="flex items-center justify-between pt-2 border-t dark:border-gray-800">
            <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">In Stock Only</label>
            <input
              type="checkbox"
              checked={onlyInStock}
              onChange={(e) => setOnlyInStock(e.target.checked)}
              className="w-4 h-4 rounded text-purple-600 focus:ring-purple-500 dark:bg-gray-900 border-gray-300"
            />
          </div>

          {/* Sort Configuration */}
          <div className="space-y-2 pt-4 border-t dark:border-gray-800">
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-400 uppercase">Sort By</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
              >
                <option value="name">Name</option>
                <option value="price">Price</option>
                <option value="avg_rating">Rating</option>
                <option value="sold_count">Popularity</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-400 uppercase">Sort Direction</label>
              <select
                value={sortDir}
                onChange={(e) => setSortDir(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
              >
                <option value="asc">Ascending (A-Z / Low-High)</option>
                <option value="desc">Descending (Z-A / High-Low)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Product Listing */}
        <div className="lg:col-span-3 space-y-6">
          {products.length === 0 && !loading ? (
            <div className="p-12 border border-dashed rounded-2xl text-center text-gray-400 bg-white dark:bg-gray-900">
              No matching products found in the catalog.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
              {products.map((product) => (
                <Link
                  key={product.id}
                  to={`/items/${product.id}`}
                  className="group border border-gray-100 dark:border-gray-900 bg-white dark:bg-gray-900 hover:-translate-y-1 hover:shadow-md rounded-2xl overflow-hidden shadow-sm flex flex-col transition duration-300"
                >
                  {/* Product Image */}
                  <div className="h-44 w-full bg-gray-50 dark:bg-gray-950/40 p-4 flex items-center justify-center border-b dark:border-gray-800">
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
                        <span className="text-xs font-bold text-amber-500 flex items-center gap-0.5">
                          {(product.avg_rating || 0).toFixed(1)} <Star size={10} className="fill-amber-400 text-amber-400" />
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
                      <span className="text-base font-black text-purple-600 dark:text-purple-400">
                        €{product.price.toFixed(2)}
                      </span>
                      <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${product.stock > 0 ? 'bg-gray-100 dark:bg-gray-800 text-gray-500' : 'bg-red-50 text-red-600 dark:bg-red-950/20'}`}>
                        {product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}

          {loading && (
            <div className="text-center py-4 text-xs font-semibold text-gray-400">
              Loading catalog items...
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
