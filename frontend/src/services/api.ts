import axios from 'axios';
import { useUIStore } from '../store/uiStore';

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

// Response interceptor to convert decimal strings to numbers
api.interceptors.response.use((response) => {
  const convertNumericFields = (obj: any): any => {
    if (obj === null || obj === undefined) return obj;
    if (Array.isArray(obj)) {
      return obj.map(convertNumericFields);
    }
    if (typeof obj === 'object') {
      for (const key in obj) {
        if (['price', 'total', 'avg_rating', 'price_at_purchase'].includes(key) && obj[key] !== null) {
          obj[key] = Number(obj[key]);
        } else {
          obj[key] = convertNumericFields(obj[key]);
        }
      }
    }
    return obj;
  };
  response.data = convertNumericFields(response.data);
  return response;
}, (error) => {
  if (!error.response || error.code === 'ERR_NETWORK' || error.message === 'Network Error') {
    useUIStore.getState().setBackendUnreachable(true);
  } else if (error.response && error.response.status >= 500) {
    const detail = error.response.data?.detail || error.message;
    useUIStore.getState().setAppError(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return Promise.reject(error);
});


export type UserProfile = {
  id: string;
  email: string;
  name: string;
  role: 'customer' | 'seller';
}

export type Product = {
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

export type CartItem = {
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

export type rating = {
  stars: number;
  comment: string
}

export type OrderItem = {
  id: string;
  rating: rating;
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

export type Order = {
  id: string;
  customer_id: string;
  status: 'placed' | 'packed' | 'out_for_delivery' | 'delivered';
  total: number;
  delivery_address: Record<string, any>;
  created_at: string;
  packed_at: string;
  out_for_delivery_at: string;
  delivered_at: string;
  items: OrderItem[];
}

export type PersistentFact = {
  id: string;
  fact_text: string;
  category: 'dietary' | 'preference' | 'instruction' | 'other';
  created_at: string;
}

export type Address = {
  id: string;
  user_id: string;
  label: string;
  line1: string;
  line2?: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  is_default: boolean;
}


// API Services
export const authService = {
  getMe: async (): Promise<UserProfile> => {
    const res = await api.get('/auth/me');
    return res.data;
  },
  register: async (data: any): Promise<{ role: string; name: string }> => {
    const res = await api.post('/auth/register', data);
    return res.data;
  },
  login: async (data: any): Promise<{ role: string; name: string }> => {
    const res = await api.post('/auth/login', data);
    return res.data;
  },
  logout: async (): Promise<void> => {
    await api.post('/auth/logout');
  },
  devBypass: async (): Promise<{ role: string; name: string }> => {
    const res = await api.post('/auth/dev-bypass');
    return res.data;
  },
  switchRole: async (role: 'customer' | 'seller'): Promise<{ role: string }> => {
    const res = await api.patch('/users/me/role', { role });
    return res.data;
  },
};

export const productService = {
  list: async (
    category?: string,
    featured?: boolean,
    page: number = 1,
    limit: number = 20,
    minPrice?: number,
    maxPrice?: number,
    minRating?: number,
    onlyInStock?: boolean,
    search?: string,
    sortBy?: string,
    sortDir?: string
  ): Promise<{
    items: Product[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get('/products', {
      params: {
        category,
        featured,
        page,
        limit,
        min_price: minPrice,
        max_price: maxPrice,
        min_rating: minRating,
        only_in_stock: onlyInStock,
        search,
        sort_by: sortBy,
        sort_dir: sortDir,
      },
    });
    return res.data;
  },
  listSeller: async (
    category?: string,
    isActive?: boolean,
    stockLevel?: string,
    page: number = 1,
    limit: number = 20
  ): Promise<{
    items: Product[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get('/products/seller', {
      params: {
        category,
        is_active: isActive,
        stock_level: stockLevel,
        page,
        limit,
      },
    });
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
  list: async (page: number = 1, limit: number = 10): Promise<{
    items: Order[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get('/orders', { params: { page, limit } });
    return res.data;
  },
  get: async (id: string): Promise<Order> => {
    const res = await api.get(`/orders/${id}`);
    return res.data;
  },
  listSellerQueue: async (page: number = 1, limit: number = 10): Promise<{
    items: Order[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get('/orders/seller/queue', { params: { page, limit } });
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

export const addressService = {
  list: async (): Promise<Address[]> => {
    const res = await api.get('/addresses');
    return res.data;
  },
  create: async (data: Omit<Address, 'id' | 'user_id' | 'is_default'> & { is_default?: boolean }): Promise<Address> => {
    const res = await api.post('/addresses', data);
    return res.data;
  },
  update: async (id: string, data: Partial<Address>): Promise<Address> => {
    const res = await api.put(`/addresses/${id}`, data);
    return res.data;
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/addresses/${id}`);
  },
};


export const healthService = {
  checkApiHealth: async (): Promise<{ voice_ok: boolean; status: string;[key: string]: any }> => {
    const res = await api.get('/health');
    return res.data;
  },
};
