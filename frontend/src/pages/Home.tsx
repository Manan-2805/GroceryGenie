import { ChevronLeft, ChevronRight, Mic, ShieldCheck, Map, Search, ArrowRight } from 'lucide-react';
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
    void fetchFeatured();
  }, []);

  const nextSlide = () => {
    setCurrentIndex((prevIndex) => (prevIndex === featuredProducts.length - 1 ? 0 : prevIndex + 1));
  };

  const prevSlide = () => {
    setCurrentIndex((prevIndex) => (prevIndex === 0 ? featuredProducts.length - 1 : prevIndex - 1));
  };

  return (
    <div className="w-full space-y-16 py-8 px-4 max-w-5xl mx-auto text-left animate-in fade-in duration-300">
      {/* Hero Presentation Section */}
      <div className="relative rounded-3xl overflow-hidden bg-gradient-to-br from-indigo-900 via-purple-800 to-pink-900 text-white p-8 md:p-14 shadow-2xl flex flex-col md:flex-row items-center gap-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_30%,rgba(255,255,255,0.08),transparent)] pointer-events-none" />

        <div className="flex-1 space-y-6 z-10">
          <span className="inline-block px-3 py-1 bg-white/10 backdrop-blur-md rounded-full text-[10px] font-bold uppercase tracking-widest text-pink-300">
            Voice-First AI Assistant
          </span>
          <h1 className="text-4xl md:text-5xl font-black tracking-tight leading-tight">
            Meet{' '}
            <span className="bg-gradient-to-r from-pink-300 to-purple-300 bg-clip-text text-transparent">
              GroceryGenie
            </span>
            .<br />
            Shopping at the Speed of Voice.
          </h1>
          <p className="max-w-xl text-purple-100 text-sm md:text-base leading-relaxed font-medium">
            Search items, verify allergen guardrails, discover store aisles, and modify your cart
            instantly using text SSE or our local WebSocket Voice assistant.
          </p>
          <div className="pt-2 flex flex-wrap gap-4">
            <Link
              to="/items"
              className="px-6 py-3 bg-white text-purple-900 hover:bg-purple-50 rounded-xl font-extrabold text-xs transition-all duration-300 shadow-lg flex items-center gap-2 hover:scale-[1.02] active:scale-95"
            >
              <span>Browse Catalog</span>
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>

        {/* Decorative Graphic mockup */}
        <div className="w-full md:w-1/3 flex justify-center items-center z-10">
          <div className="relative p-6 rounded-3xl bg-white/10 backdrop-blur-md border border-white/10 shadow-2xl flex flex-col items-center text-center max-w-[220px]">
            <div className="w-16 h-16 rounded-full bg-purple-500/20 flex items-center justify-center border border-purple-400/30 animate-pulse">
              <Mic size={32} className="text-pink-300" />
            </div>
            <p className="text-[10px] uppercase tracking-wider font-bold text-purple-200 mt-4">
              Voice Assistant
            </p>
            <p className="text-xs text-white/80 font-semibold mt-1">
              "Add three organic apples to my cart"
            </p>
          </div>
        </div>
      </div>

      {/* Value Propositions Grid */}
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-black text-gray-800 dark:text-gray-200">
            Intelligent Features
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Engineered to elevate your online grocery shopping experience
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="p-6 border dark:border-gray-900 rounded-2xl bg-white dark:bg-gray-900 shadow-sm hover:shadow-md transition duration-300 flex gap-4 items-start">
            <div className="p-3 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
              <Mic size={20} />
            </div>
            <div className="space-y-1">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">
                Real-time Voice Pipeline
              </h3>
              <p className="text-xs text-gray-500 leading-relaxed">
                Persistent WebSocket connection captures 16kHz PCM audio microphone inputs,
                transcribes speech locally using Parakeet ASR, and responses with TTS Piper.
              </p>
            </div>
          </div>

          <div className="p-6 border dark:border-gray-900 rounded-2xl bg-white dark:bg-gray-900 shadow-sm hover:shadow-md transition duration-300 flex gap-4 items-start">
            <div className="p-3 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
              <ShieldCheck size={20} />
            </div>
            <div className="space-y-1">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">
                Dietary Safety Guardrails
              </h3>
              <p className="text-xs text-gray-500 leading-relaxed">
                Strict allergy checks verify ingredients before adding them to your cart. Receive
                instant warnings if a product violates your allergy profile.
              </p>
            </div>
          </div>

          <div className="p-6 border dark:border-gray-900 rounded-2xl bg-white dark:bg-gray-900 shadow-sm hover:shadow-md transition duration-300 flex gap-4 items-start">
            <div className="p-3 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
              <Map size={20} />
            </div>
            <div className="space-y-1">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">
                Neo4j Aisle Map Routing
              </h3>
              <p className="text-xs text-gray-500 leading-relaxed">
                Grocery aisle layout mapping is stored in Neo4j Graph database, allowing you to ask
                the assistant exactly which aisle a product is located in.
              </p>
            </div>
          </div>

          <div className="p-6 border dark:border-gray-900 rounded-2xl bg-white dark:bg-gray-900 shadow-sm hover:shadow-md transition duration-300 flex gap-4 items-start">
            <div className="p-3 bg-purple-50 dark:bg-purple-950/20 text-purple-600 rounded-xl">
              <Search size={20} />
            </div>
            <div className="space-y-1">
              <h3 className="font-extrabold text-sm text-gray-800 dark:text-gray-200">
                Hybrid Vector RAG Search
              </h3>
              <p className="text-xs text-gray-500 leading-relaxed">
                Connects vector queries in Qdrant with BM25 keyword matching to perform hybrid
                searches. Ask the AI assistant questions about products directly.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Featured Products Carousel */}
      <div className="space-y-4 pt-4">
        <div>
          <h2 className="text-2xl font-black text-gray-800 dark:text-gray-200">Featured Deals</h2>
          <p className="text-xs text-gray-400 mt-0.5">Top-rated items selected for you today</p>
        </div>

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
                    src={
                      typeof currentProduct.image_url === 'string' &&
                      currentProduct.image_url.trim().length > 0
                        ? currentProduct.image_url
                        : 'https://via.placeholder.com/150'
                    }
                    alt={currentProduct.name}
                    className="h-48 object-contain rounded-xl"
                  />
                </div>

                <div className="flex-1 space-y-4">
                  <div>
                    <span className="text-[10px] font-extrabold tracking-wider px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400">
                      FEATURED ({(currentProduct.avg_rating || 0).toFixed(1)} ⭐)
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
