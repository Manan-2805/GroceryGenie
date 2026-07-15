import { ShoppingCart, ArrowLeft, MessageCircle, HelpCircle, Star } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';

import { CustomDialog } from '../components/CustomDialog';
import { productService, cartService, Product, api } from '../services/api';

export const ItemDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [product, setProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  const [addingToCart, setAddingToCart] = useState(false);
  const [quantity, setQuantity] = useState(1);

  // Scoped Q&A / RAG Box States
  const [qaInput, setQaInput] = useState('');
  const [qaAnswer, setQaAnswer] = useState<string | null>(null);
  const [qaLoading, setQaLoading] = useState(false);

  // Reviews States
  const [reviews, setReviews] = useState<any[]>([]);
  const [reviewsMeta, setReviewsMeta] = useState<any>({
    avg_rating: 0,
    total_count: 0,
    rating_distribution: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
  });
  const [reviewsPage, setReviewsPage] = useState(1);
  const [reviewsTotalPages, setReviewsTotalPages] = useState(1);
  const [loadingReviews, setLoadingReviews] = useState(false);
  const [showAllReviews, setShowAllReviews] = useState(false);

  // Custom Dialog States
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTitle, setDialogTitle] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');

  const showDialog = (title: string, message: string) => {
    setDialogTitle(title);
    setDialogMessage(message);
    setDialogOpen(true);
  };

  const fetchReviews = async (pageNum: number, append: boolean = false) => {
    if (!id) return;
    setLoadingReviews(true);
    try {
      const res = await api.get(`/ratings/product/${id}`, {
        params: { page: pageNum, limit: 5 },
      });
      setReviewsMeta(res.data.metadata);
      setReviewsTotalPages(res.data.pages);
      if (append) {
        setReviews((prev) => {
          // Avoid duplicate keys
          const existingTimestamps = new Set(prev.map(r => new Date(r.created_at).getTime()));
          const newItems = res.data.items.filter((item: any) => !existingTimestamps.has(new Date(item.created_at).getTime()));
          return [...prev, ...newItems];
        });
      } else {
        setReviews(res.data.items);
      }
    } catch (e) {
      console.error('Error fetching reviews:', e);
    } finally {
      setLoadingReviews(false);
    }
  };

  const loadMoreReviews = () => {
    if (reviewsPage < reviewsTotalPages && !loadingReviews) {
      const nextPage = reviewsPage + 1;
      setReviewsPage(nextPage);
      fetchReviews(nextPage, true);
    }
  };

  useEffect(() => {
    const fetchProduct = async () => {
      if (!id) return;
      try {
        const data = await productService.get(id);
        setProduct(data);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchProduct();
    fetchReviews(1, false);
  }, [id]);

  const handleAddToCart = async () => {
    if (!product) return;
    setAddingToCart(true);
    try {
      await cartService.add(product.id, quantity);
      showDialog('Success', `Added ${quantity}x ${product.name} to cart.`);
    } catch (e: any) {
      console.error(e);
      const detail = e.response?.data?.detail;
      showDialog('Error', detail ? (typeof detail === 'string' ? detail : JSON.stringify(detail)) : 'Failed to add item to cart. Make sure you are logged in.');
    } finally {
      setAddingToCart(false);
    }
  };

  const handleQaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!qaInput.trim() || !product) return;
    
    setQaLoading(true);
    setQaAnswer(null);
    
    try {
      // Include credentials: 'include' for CORS cookies auth
      const response = await fetch(`http://localhost:8000/api/v1/products/${product.id}/qa`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: qaInput }),
      });

      if (!response.body) throw new Error('No response stream');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answerText = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const rawText = decoder.decode(value);
        const lines = rawText.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data:')) {
            const dataStr = line.replace('data:', '').trim();
            try {
              const data = JSON.parse(dataStr);
              if (data.type === 'delta') {
                answerText += data.text;
                setQaAnswer(answerText);
              }
            } catch (err) {
              // Not JSON delta, ignore
            }
          }
        }
      }
    } catch (err) {
      console.error(err);
      setQaAnswer('Unable to retrieve an answer at this time.');
    } finally {
      setQaLoading(false);
    }
  };

  const renderStarBreakdown = () => {
    const total = reviewsMeta.total_count || 1;
    return (
      <div className="space-y-2 w-full max-w-xs text-xs font-semibold text-gray-500">
        {[5, 4, 3, 2, 1].map((star) => {
          const count = reviewsMeta.rating_distribution[star.toString()] || 0;
          const percentage = Math.round((count / total) * 100);
          return (
            <div key={star} className="flex items-center gap-3">
              <span className="w-6 text-right font-bold">{star} ★</span>
              <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-amber-400 rounded-full"
                  style={{ width: `${percentage}%` }}
                />
              </div>
              <span className="w-8 text-left font-bold">{count}</span>
            </div>
          );
        })}
      </div>
    );
  };

  if (loading) {
    return <div className="p-8 text-center text-gray-400">Loading product details...</div>;
  }

  if (!product) {
    return (
      <div className="p-8 text-center text-gray-400 space-y-4">
        <p>Product not found.</p>
        <button onClick={() => navigate('/items')} className="text-purple-600 font-bold underline">
          Return to Catalog
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-8 text-left">
      {/* Back button */}
      <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-sm text-gray-500 hover:text-purple-600 transition">
        <ArrowLeft size={16} />
        <span>Back</span>
      </button>

      {/* Main product info split layout */}
      <div className="flex flex-col md:flex-row gap-8 items-start border rounded-2xl glassmorphism p-6 shadow-md bg-white dark:bg-gray-900">
        {/* Image */}
        <div className="w-full md:w-1/2 bg-gray-50 dark:bg-gray-950/40 p-8 rounded-xl flex items-center justify-center border dark:border-gray-800">
          <img
            src={product.image_url || 'https://via.placeholder.com/250'}
            alt={product.name}
            className="h-64 object-contain rounded-lg"
          />
        </div>

        {/* Info */}
        <div className="flex-1 space-y-6 w-full">
          <div>
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-purple-600">
                {product.category}
              </span>
              <span className="text-sm font-bold text-amber-500 flex items-center gap-0.5">
                {(product.avg_rating || 0).toFixed(1)} <Star size={14} className="fill-amber-400 text-amber-400" />
              </span>
            </div>
            <h1 className="text-3xl font-extrabold text-gray-800 dark:text-gray-200 mt-2">
              {product.name}
            </h1>
            <p className="text-sm text-gray-500 mt-3 leading-relaxed">
              {product.description}
            </p>
          </div>

          <div className="flex items-baseline gap-4">
            <span className="text-4xl font-black text-purple-600 dark:text-purple-400">
              €{product.price.toFixed(2)}
            </span>
            <span className={`text-xs font-semibold px-2.5 py-0.5 rounded ${
              product.stock > 0
                ? 'bg-green-100 dark:bg-green-950/40 text-green-600 dark:text-green-400'
                : 'bg-red-100 dark:bg-red-950/40 text-red-600'
            }`}>
              {product.stock > 0 ? `${product.stock} items remaining` : 'Out of stock'}
            </span>
          </div>

          {/* Add to Cart Actions */}
          {product.stock > 0 && (
            <div className="flex items-center gap-4 pt-2">
              <div className="flex items-center border dark:border-gray-800 rounded-xl overflow-hidden bg-white dark:bg-gray-950">
                <button
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                  className="px-3 py-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 focus:outline-none font-bold"
                >
                  -
                </button>
                <input
                  type="number"
                  min={1}
                  max={product.stock}
                  value={quantity}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    if (!isNaN(val)) {
                      setQuantity(Math.max(1, Math.min(product.stock, val)));
                    }
                  }}
                  className="w-12 text-center font-bold text-sm bg-transparent border-none outline-none focus:ring-0 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
                <button
                  onClick={() => setQuantity((q) => Math.min(product.stock, q + 1))}
                  className="px-3 py-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900 focus:outline-none font-bold"
                >
                  +
                </button>
              </div>

              <button
                onClick={handleAddToCart}
                disabled={addingToCart}
                className="flex-1 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-bold transition flex justify-center items-center gap-2 shadow-lg"
              >
                <ShoppingCart size={18} />
                <span>{addingToCart ? 'Adding...' : 'Add to Cart'}</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Scoped Product Q&A / RAG Box */}
      <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-4 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-2 font-extrabold text-lg text-gray-800 dark:text-gray-200 border-b pb-3 dark:border-gray-800">
          <HelpCircle className="text-purple-600" />
          <span>Product Advisor Q&A</span>
        </div>
        
        <p className="text-xs text-gray-500">
          Ask questions specifically about this product. The system will retrieve related facts and ingredients to respond.
        </p>

        <form onSubmit={handleQaSubmit} className="flex gap-2">
          <input
            type="text"
            value={qaInput}
            onChange={(e) => setQaInput(e.target.value)}
            placeholder="Is this product gluten-free? Does it contain milk?"
            className="flex-1 px-4 py-2 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-xs text-gray-850 dark:text-gray-200"
          />
          <button
            type="submit"
            disabled={qaLoading}
            className="px-5 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-bold transition"
          >
            Ask
          </button>
        </form>

        {/* Answer view */}
        {(qaLoading || qaAnswer) && (
          <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-950/40 text-sm space-y-2 border border-gray-100 dark:border-gray-800">
            <div className="font-semibold text-xs text-purple-600 dark:text-purple-400 flex items-center gap-1.5">
              <MessageCircle size={14} />
              <span>Advisor Response</span>
            </div>
            
            {qaLoading && !qaAnswer ? (
              <div className="flex gap-1 py-1">
                <span className="w-1.5 h-1.5 bg-purple-600 rounded-full animate-bounce"></span>
                <span className="w-1.5 h-1.5 bg-purple-600 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                <span className="w-1.5 h-1.5 bg-purple-600 rounded-full animate-bounce [animation-delay:0.4s]"></span>
              </div>
            ) : (
              <p className="leading-relaxed text-gray-700 dark:text-gray-300 font-medium">
                {qaAnswer}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Reviews and Star Breakdown Section */}
      <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-6 bg-white dark:bg-gray-900">
        <h3 className="font-extrabold text-lg text-gray-800 dark:text-gray-200 border-b pb-3 dark:border-gray-800">
          Customer Reviews
        </h3>

        <div className="flex flex-col md:flex-row gap-8 items-start">
          {/* Average Rating Summary */}
          <div className="flex flex-col items-center justify-center p-6 border dark:border-gray-800 rounded-2xl bg-gray-50 dark:bg-gray-950/20 text-center w-full md:w-fit min-w-[200px]">
            <span className="text-5xl font-black text-purple-600 dark:text-purple-400">
              {(product.avg_rating || 0).toFixed(1)}
            </span>
            <div className="flex gap-1.5 mt-2">
              {[1, 2, 3, 4, 5].map((star) => (
                <Star
                  key={star}
                  size={16}
                  className={
                    star <= Math.round(product.avg_rating || 0)
                      ? 'fill-amber-400 text-amber-400'
                      : 'text-gray-300 dark:text-gray-700'
                  }
                />
              ))}
            </div>
            <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider mt-2">
              Based on {reviewsMeta.total_count} reviews
            </span>
          </div>

          {/* Star breakdown counts */}
          <div className="flex-1 w-full">
            <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Rating Breakdown</h4>
            {renderStarBreakdown()}
          </div>
        </div>

        {/* Reviews List */}
        <div className="space-y-4 pt-4 border-t dark:border-gray-800">
          <div className="flex justify-between items-center">
            <h4 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">User Comments & Reviews</h4>
            {!showAllReviews && reviewsMeta.total_count > 3 && (
              <button
                onClick={() => {
                  setShowAllReviews(true);
                  fetchReviews(1, false);
                }}
                className="text-xs font-bold text-purple-600 hover:text-purple-700 uppercase"
              >
                Show All Reviews
              </button>
            )}
          </div>

          <div
            className={`space-y-4 ${
              showAllReviews ? 'max-h-[300px] overflow-y-auto pr-2' : ''
            }`}
            onScroll={(e) => {
              if (!showAllReviews) return;
              const target = e.currentTarget;
              const atBottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 10;
              if (atBottom) {
                loadMoreReviews();
              }
            }}
          >
            {(showAllReviews ? reviews : reviews.slice(0, 3)).map((rev, idx) => (
              <div key={idx} className="p-4 border dark:border-gray-800 rounded-xl bg-gray-50/50 dark:bg-gray-950/20 space-y-2 text-xs">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-800 dark:text-gray-200">{rev.user_name}</span>
                    <div className="flex gap-0.5">
                      {[1, 2, 3, 4, 5].map((star) => (
                        <Star
                          key={star}
                          size={10}
                          className={
                            star <= rev.stars
                              ? 'fill-amber-400 text-amber-400'
                              : 'text-gray-300 dark:text-gray-700'
                          }
                        />
                      ))}
                    </div>
                  </div>
                  <span className="text-[10px] text-gray-400 font-semibold">
                    {new Date(rev.created_at).toLocaleDateString()}
                  </span>
                </div>
                <p className="text-gray-600 dark:text-gray-300 leading-relaxed font-medium">
                  {rev.comment || 'No comment left'}
                </p>
              </div>
            ))}

            {reviews.length === 0 && (
              <p className="text-xs text-gray-400 py-4 text-center">No reviews left for this product yet.</p>
            )}

            {loadingReviews && (
              <div className="text-center py-2 text-[10px] font-semibold text-gray-400">
                Loading more reviews...
              </div>
            )}
          </div>
        </div>
      </div>

      <CustomDialog
        isOpen={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title={dialogTitle}
        message={dialogMessage}
      />
    </div>
  );
};
