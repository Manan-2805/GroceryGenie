import { ChevronLeft, ChevronRight } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { productService, Product } from '../services/api';

export const Home: React.FC = () => {
  const [featuredProducts, setFeaturedProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    const fetchFeatured = async () => {
      try {
        const data = await productService.list(undefined, true);
        setFeaturedProducts(data.items);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchFeatured();
  }, []);

  const nextSlide = () => {
    setCurrentIndex((prevIndex) =>
      prevIndex === featuredProducts.length - 1 ? 0 : prevIndex + 1
    );
  };

  const prevSlide = () => {
    setCurrentIndex((prevIndex) =>
      prevIndex === 0 ? featuredProducts.length - 1 : prevIndex - 1
    );
  };

  return (
    <div className="space-y-10 py-6 px-4 max-w-5xl mx-auto text-left">
      {/* Welcome Banner */}
      <div className="p-8 md:p-12 rounded-3xl bg-gradient-to-r from-purple-600 to-indigo-600 text-white space-y-4 shadow-xl">
        <h1 className="text-4xl md:text-5xl font-black tracking-tight leading-none margin-0">
          Smart Grocery Shopping, Simplified.
        </h1>
        <p className="max-w-xl text-purple-100 text-sm md:text-base leading-relaxed">
          Search products, compare prices, manage your cart, and ask about ingredients using our AI assistant (text or voice) down in the bottom-right bubble.
        </p>
        <div className="pt-2">
          <Link
            to="/items"
            className="px-6 py-3 bg-white text-purple-600 hover:bg-purple-50 rounded-xl font-bold transition shadow-lg inline-block text-sm"
          >
            Browse Products
          </Link>
        </div>
      </div>

      {/* Featured Products Carousel */}
      <div className="space-y-4">
        <h2 className="text-2xl font-black text-gray-800 dark:text-gray-200">Featured Deals</h2>

        {loading ? (
          <p className="text-sm text-gray-400">Loading products...</p>
        ) : featuredProducts.length === 0 ? (
          <div className="p-6 border border-dashed rounded-2xl text-center text-gray-400">
            No products featured yet.
          </div>
        ) : (
          (() => {
            const currentProduct = featuredProducts[currentIndex];
            if (!currentProduct) return null;
            return (
              <div className="relative border rounded-2xl overflow-hidden glassmorphism p-6 flex flex-col md:flex-row items-center gap-6 shadow-md">
                {/* Left arrow */}
                <button
                  onClick={prevSlide}
                  className="absolute left-3 top-1/2 -translate-y-1/2 p-2 bg-white dark:bg-gray-900 border rounded-full hover:bg-gray-50 dark:hover:bg-gray-800 shadow"
                >
                  <ChevronLeft size={20} />
                </button>

                {/* Product display */}
                <div className="w-full md:w-1/3 flex justify-center">
                  <img
                    src={currentProduct.image_url || 'https://via.placeholder.com/150'}
                    alt={currentProduct.name}
                    className="h-48 object-contain rounded-xl"
                  />
                </div>

                <div className="flex-1 space-y-4">
                  <div>
                    <span className="text-[10px] font-extrabold tracking-wider px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400">
                      FEATURED ({currentProduct.avg_rating} ⭐)
                    </span>
                    <h3 className="text-2xl font-extrabold text-gray-800 dark:text-gray-200 mt-2">
                      {currentProduct.name}
                    </h3>
                    <p className="text-sm text-gray-500 mt-1 max-w-md">
                      {currentProduct.description}
                    </p>
                  </div>

                  <div className="flex items-center gap-4">
                    <span className="text-3xl font-black text-purple-600 dark:text-purple-400">
                      €{currentProduct.price.toFixed(2)}
                    </span>
                    <span className="text-xs text-gray-400">
                      Category: {currentProduct.category}
                    </span>
                  </div>

                  <div>
                    <Link
                      to={`/items/${currentProduct.id}`}
                      className="px-5 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-xs font-bold transition inline-flex items-center gap-2"
                    >
                      View Detail
                    </Link>
                  </div>
                </div>

                {/* Right arrow */}
                <button
                  onClick={nextSlide}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 bg-white dark:bg-gray-900 border rounded-full hover:bg-gray-50 dark:hover:bg-gray-800 shadow"
                >
                  <ChevronRight size={20} />
                </button>
              </div>
            );
          })()
        )}
      </div>
    </div>
  );
};
