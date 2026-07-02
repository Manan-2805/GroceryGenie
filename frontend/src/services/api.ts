import axios from 'axios';

// Detect base API URL
const BASE_URL = import.meta.env.DEV
  ? 'http://localhost:8000/api/v1'
  : '/api/v1';

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true, // Crucial for httpOnly JWT cookie
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  role: 'customer' | 'seller';
}

export interface Product {
  id: string;
  seller_id: string;
  name: string;
  description: string;
  category: string;
  price: number;
  stock: number;
  image_url?: string;
  avg_rating: number;
  sold_count: number;
  is_active: boolean;
}

export interface CartItem {
  id: string;
  product_id: string;
  quantity: number;
  product: {
    id: string;
    name: string;
    price: number;
    image_url?: string;
    stock: number;
  };
}

export interface OrderItem {
  id: string;
  product_id?: string;
  quantity: number;
  price_at_purchase: number;
  product?: {
    id: string;
    name: string;
    price: number;
    image_url?: string;
  };
}

export interface Order {
  id: string;
  customer_id: string;
  status: 'placed' | 'packed' | 'out_for_delivery' | 'delivered';
  total: number;
  delivery_address: Record<string, any>;
  created_at: string;
  items: OrderItem[];
}

export interface PersistentFact {
  id: string;
  fact_text: string;
  category: 'dietary' | 'preference' | 'instruction' | 'other';
  created_at: string;
}

// API Services
export const authService = {
  getMe: async (): Promise<UserProfile> => {
    const res = await api.get('/auth/me');
    return res.data;
  },
  mockLogin: async (role: 'customer' | 'seller'): Promise<{ role: string; name: string }> => {
    const res = await api.post('/auth/mock-login', { role });
    return res.data;
  },
  logout: async (): Promise<void> => {
    await api.post('/auth/logout');
  },
};

export const productService = {
  list: async (category?: string, featured?: boolean): Promise<Product[]> => {
    const res = await api.get('/products', { params: { category, featured } });
    return res.data;
  },
  get: async (id: string): Promise<Product> => {
    const res = await api.get(`/products/${id}`);
    return res.data;
  },
  create: async (data: Omit<Product, 'id' | 'seller_id' | 'avg_rating' | 'sold_count' | 'is_active'>): Promise<Product> => {
    const res = await api.post('/products', data);
    return res.data;
  },
  update: async (id: string, data: Partial<Product>): Promise<Product> => {
    const res = await api.put(`/products/${id}`, data);
    return res.data;
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/products/${id}`);
  },
};

export const cartService = {
  get: async (): Promise<CartItem[]> => {
    const res = await api.get('/cart');
    return res.data;
  },
  add: async (productId: string, quantity: number = 1): Promise<CartItem> => {
    const res = await api.post('/cart', { product_id: productId, quantity });
    return res.data;
  },
  update: async (productId: string, quantity: number): Promise<CartItem> => {
    const res = await api.put(`/cart/${productId}`, { quantity });
    return res.data;
  },
  remove: async (productId: string): Promise<void> => {
    await api.delete(`/cart/${productId}`);
  },
};

export const orderService = {
  place: async (address: Record<string, any>): Promise<Order> => {
    const res = await api.post('/orders', { delivery_address: address });
    return res.data;
  },
  list: async (): Promise<Order[]> => {
    const res = await api.get('/orders');
    return res.data;
  },
  get: async (id: string): Promise<Order> => {
    const res = await api.get(`/orders/${id}`);
    return res.data;
  },
  listSellerQueue: async (): Promise<Order[]> => {
    const res = await api.get('/orders/seller/queue');
    return res.data;
  },
  updateStatus: async (id: string, status: string): Promise<Order> => {
    const res = await api.put(`/orders/${id}/status`, { status });
    return res.data;
  },
};

export const memoryService = {
  listFacts: async (): Promise<PersistentFact[]> => {
    const res = await api.get('/users/facts');
    return res.data;
  },
  deleteFact: async (factId: string): Promise<void> => {
    await api.delete(`/users/facts/${factId}`);
  },
};
