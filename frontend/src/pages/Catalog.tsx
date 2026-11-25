import { useQuery } from '@tanstack/react-query';
import { Search, Filter, Star, ShoppingBasket } from 'lucide-react';
import { useState, type FC } from 'react';
import { Link } from 'react-router-dom';

import { productService } from '../services/api';

export const Catalog: FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [minPrice, setMinPrice] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [minRating, setMinRating] = useState(0);
  const [onlyInStock, setOnlyInStock] = useState(false);
  const [sortBy, setSortBy] = useState('');
  const [sortDir, setSortDir] = useState('asc');
  const [page, setPage] = useState(1);
  const categories = [
    'Dairy & Eggs',
    'Produce',
    'Pantry',
    'Bakery',
    'Beverages',
    'Frozen',
    'Snacks',
  ];

  const query = useQuery({
    queryKey: [
      'catalog',
      selectedCategory,
      searchQuery,
      minPrice,
      maxPrice,
      minRating,
      onlyInStock,
      sortBy,
      sortDir,
      page,
    ],
    queryFn: ({ signal }) =>
      productService.list(
        selectedCategory || undefined,
        undefined,
        page,
        20,
        minPrice.length > 0 ? Number(minPrice) : undefined,
        maxPrice.length > 0 ? Number(maxPrice) : undefined,
        minRating > 0 ? minRating : undefined,
        onlyInStock,
        searchQuery.trim() || undefined,
        sortBy || undefined,
        sortDir,
        signal
      ),
  });
  const products = query.data?.items ?? [];
  const loading = query.isPending;
  const totalPages = query.data?.pages ?? 1;

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 text-left space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-800 dark:text-gray-200">Catalog</h1>
        <p className="text-sm text-gray-500">Explore and search our premium grocery catalog</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Sidebar Filters */}
        <div className="lg:col-span-1 glass-card p-6 h-fit space-y-6" onChange={() => setPage(1)}>
          <div className="flex items-center gap-2 pb-3 border-b dark:border-gray-800">
            <Filter size={18} className="text-accent" />
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
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setPage(1);
                }}
                className="w-full pl-9 pr-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
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
              className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="">All Categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {/* Price Range */}
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Price Range (₹)</label>
            <div className="flex gap-2 items-center">
              <input
                type="number"
                placeholder="Min"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <span className="text-gray-400 text-xs">-</span>
              <input
                type="number"
                placeholder="Max"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
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
            <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
              In Stock Only
            </label>
            <input
              type="checkbox"
              checked={onlyInStock}
              onChange={(e) => setOnlyInStock(e.target.checked)}
              className="w-4 h-4 rounded text-accent focus:ring-accent dark:bg-gray-900 border-gray-300"
            />
          </div>

          {/* Sort Configuration */}
          <div className="space-y-2 pt-4 border-t dark:border-gray-800">
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-400 uppercase">Sort By</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              >
                <option value="">Relevance</option>
                <option value="name">Name</option>
                <option value="price">Price</option>
                <option value="avg_rating">Rating</option>
                <option value="sold_count">Popularity</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-gray-400 uppercase">
                Sort Direction
              </label>
              <select
                value={sortDir}
                onChange={(e) => setSortDir(e.target.value)}
                className="w-full px-3 py-2 border dark:border-gray-800 bg-transparent rounded-xl text-xs focus:outline-none focus:ring-1 focus:ring-accent"
              >
                <option value="asc">Ascending (A-Z / Low-High)</option>
                <option value="desc">Descending (Z-A / High-Low)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Product Listing */}
        <div className="lg:col-span-3 space-y-6">
          {query.isError ? (
            <div role="alert" className="glass-card p-4">
              Catalog is unavailable.{' '}
              <button type="button" onClick={() => void query.refetch()}>
                Retry
              </button>
            </div>
          ) : products.length === 0 && !loading ? (
            <div className="p-12 border border-dashed border-border rounded-2xl text-center text-muted glass-card">
              No matching products found in the catalog.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
              {products.map((product) => (
                <Link
                  key={product.id}
                  to={`/items/${product.id}`}
                  className="group glass-card hover:-translate-y-0.5 overflow-hidden flex flex-col transition duration-200"
                >
                  {/* Product Image */}
                  <div className="h-44 w-full bg-gray-50 dark:bg-gray-950/40 p-4 flex items-center justify-center border-b dark:border-gray-800">
                    {typeof product.image_url === 'string' &&
                    product.image_url.trim().length > 0 ? (
                      <img
                        src={product.image_url}
                        loading="lazy"
                        alt=""
                        className="h-full object-contain"
                      />
                    ) : (
                      <ShoppingBasket aria-hidden className="h-12 w-12 text-accent" />
                    )}
                  </div>

                  {/* Product Info */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                    <div className="space-y-1">
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] font-bold uppercase tracking-wider text-accent">
                          {product.category}
                        </span>
                        <span className="text-xs font-bold text-amber-500 flex items-center gap-0.5">
                          {(product.avg_rating || 0).toFixed(1)}{' '}
                          <Star size={10} className="fill-amber-400 text-amber-400" />
                        </span>
                      </div>
                      <h3 className="font-semibold text-sm text-gray-800 dark:text-gray-200">
                        {product.name}
                      </h3>
                      <p className="text-xs text-gray-400 line-clamp-2">{product.description}</p>
                    </div>

                    <div className="flex justify-between items-center pt-2">
                      <span className="text-base font-semibold text-accent dark:text-accent">
                        ₹{product.price.toFixed(2)}
                      </span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded font-bold ${product.stock > 0 ? 'bg-gray-100 dark:bg-gray-800 text-gray-500' : 'bg-red-50 text-red-600 dark:bg-red-950/20'}`}
                      >
                        {product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}

          {totalPages > 1 && (
            <nav aria-label="Catalog pages" className="flex items-center justify-center gap-4">
              <button
                type="button"
                className="rounded border px-3 py-2"
                disabled={page <= 1 || loading}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span>
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="rounded border px-3 py-2"
                disabled={page >= totalPages || loading}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </nav>
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
