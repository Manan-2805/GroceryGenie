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
        setFeaturedProducts(data?.items ?? []);
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
    <div className="w-full space-y-12 text-left">
      {/* Hero */}
      <div className="glass-panel p-8 md:p-12 flex flex-col md:flex-row items-center gap-8">
        <div className="flex-1 space-y-5">
          <span className="inline-block px-3 py-1 bg-accent-bg rounded-full text-[10px] font-semibold uppercase tracking-widest text-accent">
            Voice-First AI Assistant
          </span>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-tight text-heading">
            Meet <span className="text-accent">GroceryGenie</span>.
            <br />
            Shopping at the Speed of Voice.
          </h1>
          <p className="max-w-xl text-muted text-sm md:text-base leading-relaxed">
            Search items, verify allergen guardrails, discover store aisles, and modify your cart
            instantly using text SSE or our local WebSocket Voice assistant.
          </p>
          <div className="pt-1 flex flex-wrap gap-3">
            <Link to="/items" className="btn-primary">
              <span>Browse Catalog</span>
              <ArrowRight size={14} />
            </Link>
            <Link to="/agent" className="btn-secondary">
              Open Assistant
            </Link>
          </div>
        </div>

        <div className="w-full md:w-1/3 flex justify-center items-center">
          <div className="glass-card p-6 flex flex-col items-center text-center max-w-[220px]">
            <div className="w-14 h-14 rounded-full bg-accent-bg flex items-center justify-center border border-accent-border">
              <Mic size={28} className="text-accent" />
            </div>
            <p className="text-[10px] uppercase tracking-wider font-semibold text-muted mt-4">
              Voice Assistant
            </p>
            <p className="text-xs text-heading font-medium mt-1">
              &ldquo;Add three organic apples to my cart&rdquo;
            </p>
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="space-y-5">
        <div>
          <h2 className="text-xl font-semibold text-heading">Intelligent Features</h2>
          <p className="text-xs text-muted mt-0.5">
            Engineered to elevate your online grocery shopping experience
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            {
              icon: <Mic size={20} />,
              title: 'Real-time Voice Pipeline',
              desc: 'Persistent WebSocket connection captures 16kHz PCM audio microphone inputs, transcribes speech locally using Parakeet ASR, and responses with TTS Piper.',
            },
            {
              icon: <ShieldCheck size={20} />,
              title: 'Dietary Safety Guardrails',
              desc: 'Strict allergy checks verify ingredients before adding them to your cart. Receive instant warnings if a product violates your allergy profile.',
            },
            {
              icon: <Map size={20} />,
              title: 'Neo4j Aisle Map Routing',
              desc: 'Grocery aisle layout mapping is stored in Neo4j Graph database, allowing you to ask the assistant exactly which aisle a product is located in.',
            },
            {
              icon: <Search size={20} />,
              title: 'Hybrid Vector RAG Search',
              desc: 'Connects vector queries in Qdrant with BM25 keyword matching to perform hybrid searches. Ask the AI assistant questions about products directly.',
            },
          ].map((feature) => (
            <div key={feature.title} className="glass-card p-5 flex gap-4 items-start">
              <div className="p-2.5 bg-accent-bg text-accent rounded-xl shrink-0">
                {feature.icon}
              </div>
              <div className="space-y-1">
                <h3 className="font-semibold text-sm text-heading">{feature.title}</h3>
                <p className="text-xs text-muted leading-relaxed">{feature.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Featured Products */}
      <div className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold text-heading">Featured Deals</h2>
          <p className="text-xs text-muted mt-0.5">Top-rated items selected for you today</p>
        </div>

        {loading ? (
          <p className="text-sm text-muted">Loading products...</p>
        ) : featuredProducts.length === 0 ? (
          <div className="p-6 border border-dashed border-border rounded-2xl text-center text-muted">
            No products featured yet.
          </div>
        ) : (
          (() => {
            const currentProduct = featuredProducts[currentIndex];
            if (!currentProduct) return null;
            return (
              <div className="relative glass-card p-6 flex flex-col md:flex-row items-center gap-6">
                <button
                  onClick={prevSlide}
                  className="absolute left-3 top-1/2 -translate-y-1/2 p-2 bg-surface border border-border rounded-full hover:bg-accent-bg shadow-glass z-10"
                  aria-label="Previous"
                >
                  <ChevronLeft size={18} />
                </button>

                <div className="w-full md:w-1/3 flex justify-center">
                  <img
                    src={
                      typeof currentProduct.image_url === 'string' &&
                      currentProduct.image_url.trim().length > 0
                        ? currentProduct.image_url
                        : 'https://via.placeholder.com/150'
                    }
                    alt={currentProduct.name}
                    className="h-44 object-contain rounded-xl"
                  />
                </div>

                <div className="flex-1 space-y-4">
                  <div>
                    <span className="text-[10px] font-semibold tracking-wider px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400">
                      FEATURED ({(currentProduct.avg_rating || 0).toFixed(1)} ⭐)
                    </span>
                    <h3 className="text-xl font-semibold text-heading mt-2">
                      {currentProduct.name}
                    </h3>
                    <p className="text-sm text-muted mt-1 max-w-md">{currentProduct.description}</p>
                  </div>

                  <div className="flex items-center gap-4">
                    <span className="text-2xl font-semibold text-accent">
                      ₹{currentProduct.price.toFixed(2)}
                    </span>
                    <span className="text-xs text-muted">Category: {currentProduct.category}</span>
                  </div>

                  <Link to={`/items/${currentProduct.id}`} className="btn-primary inline-flex">
                    View Detail
                  </Link>
                </div>

                <button
                  onClick={nextSlide}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-2 bg-surface border border-border rounded-full hover:bg-accent-bg shadow-glass z-10"
                  aria-label="Next"
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            );
          })()
        )}
      </div>
    </div>
  );
};
