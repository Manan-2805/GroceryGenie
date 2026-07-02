import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ShoppingCart, ArrowLeft, MessageCircle, HelpCircle } from 'lucide-react';
import { productService, cartService, Product } from '../services/api';

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
  }, [id]);

  const handleAddToCart = async () => {
    if (!product) return;
    setAddingToCart(true);
    try {
      await cartService.add(product.id, quantity);
      alert(`Added ${quantity}x ${product.name} to cart.`);
    } catch (e) {
      console.error(e);
      alert('Failed to add item to cart. Make sure you are logged in.');
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
      // Fetch response from scoped product detailed Q&A RAG route
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
      <div className="flex flex-col md:flex-row gap-8 items-start border rounded-2xl glassmorphism p-6 shadow-md">
        {/* Image */}
        <div className="w-full md:w-1/2 bg-gray-50 dark:bg-gray-900/40 p-8 rounded-xl flex items-center justify-center">
          <img
            src={product.image_url || 'https://via.placeholder.com/250'}
            alt={product.name}
            className="h-64 object-contain rounded-lg"
          />
        </div>

        {/* Info */}
        <div className="flex-1 space-y-6">
          <div>
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-purple-600">
                {product.category}
              </span>
              <span className="text-sm font-bold text-amber-500">
                {product.avg_rating} ⭐
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
            <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
              product.stock > 0
                ? 'bg-green-100 dark:bg-green-950/40 text-green-600'
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
                  className="px-3 py-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900"
                >
                  -
                </button>
                <span className="px-4 font-bold text-sm">{quantity}</span>
                <button
                  onClick={() => setQuantity((q) => Math.min(product.stock, q + 1))}
                  className="px-3 py-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900"
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
      <div className="border rounded-2xl glassmorphism p-6 shadow-md space-y-4">
        <div className="flex items-center gap-2 font-extrabold text-lg text-gray-800 dark:text-gray-200 border-b pb-3 dark:border-gray-900">
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
            className="flex-1 px-4 py-2 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-1 focus:ring-purple-600 text-sm"
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
          <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-900/40 text-sm space-y-2 border border-gray-100 dark:border-gray-900">
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
    </div>
  );
};
