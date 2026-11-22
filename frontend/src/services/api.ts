import axios from 'axios';

import { useUIStore } from '../store/uiStore';

// Detect base API URL
const BASE_URL = '/api/v1';

type ApiError = Error & {
  response?: {
    data?: {
      detail?: unknown;
    };
    status?: number;
  };
  code?: string;
  message?: string;
};

type UnknownRecord = Record<string, unknown>;

type ApiResponse<T> = {
  data: T;
};

const isApiResponse = <T>(payload: ApiResponse<T> | T): payload is ApiResponse<T> => {
  return typeof payload === 'object' && payload !== null && 'data' in payload;
};

const extractApiData = <T>(payload: ApiResponse<T> | T): T => {
  if (typeof payload === 'string' || payload === null || payload === undefined) {
    return null as unknown as T;
  }
  return isApiResponse(payload) ? payload.data : payload;
};

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (response) => {
    const convertNumericFields = (value: unknown): unknown => {
      if (value === null || value === undefined) return value;
      if (Array.isArray(value)) {
        return value.map((item) => convertNumericFields(item));
      }
      if (typeof value === 'object') {
        const record = value as UnknownRecord;
        const converted: UnknownRecord = {};
        for (const [key, item] of Object.entries(record)) {
          if (
            ['price', 'total', 'avg_rating', 'price_at_purchase'].includes(key) &&
            item !== null &&
            item !== undefined
          ) {
            const numericValue = typeof item === 'number' ? item : Number(item);
            converted[key] = Number.isFinite(numericValue) ? numericValue : item;
          } else {
            converted[key] = convertNumericFields(item);
          }
        }
        return converted;
      }
      return value;
    };

    response.data = convertNumericFields(response.data);
    return response;
  },
  (error: unknown) => {
    const axiosError = error as ApiError;
    if (
      !axiosError.response ||
      axiosError.code === 'ERR_NETWORK' ||
      axiosError.message === 'Network Error'
    ) {
      useUIStore.getState().setBackendUnreachable(true);
    } else if (
      typeof axiosError.response?.status === 'number' &&
      axiosError.response.status >= 500
    ) {
      const detail = axiosError.response.data?.detail ?? axiosError.message;
      useUIStore
        .getState()
        .setAppError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return Promise.reject(error);
  }
);

export type UserProfile = {
  id: string;
  email: string;
  name: string;
  role: 'customer' | 'seller';
};

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
};

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
};

export type Rating = {
  stars: number;
  comment: string;
};

export type OrderItem = {
  id: string;
  rating: Rating | null;
  product_id?: string;
  quantity: number;
  price_at_purchase: number;
  product?: {
    id: string;
    name: string;
    price: number;
    image_url?: string;
    category?: string;
  };
};

export type Order = {
  id: string;
  customer_id: string;
  status: 'placed' | 'packed' | 'out_for_delivery' | 'delivered';
  total: number;
  delivery_address: Record<string, unknown>;
  created_at: string;
  packed_at: string | null;
  out_for_delivery_at: string | null;
  delivered_at: string | null;
  items: OrderItem[];
};

export type PersistentFact = {
  id: string;
  fact_text: string;
  category: 'dietary' | 'preference' | 'instruction' | 'other';
  created_at: string;
};

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
};

export type AuthResponse = {
  role: string;
  name: string;
};

export type HealthStatus = {
  voice_ok: boolean;
  status: string;
  [key: string]: unknown;
};

const isWrappedHealthStatus = (
  payload: ApiResponse<HealthStatus> | HealthStatus
): payload is ApiResponse<HealthStatus> => {
  if (typeof payload !== 'object' || payload === null) return false;
  if (!('data' in payload)) return false;
  const maybeData = payload.data;
  return typeof maybeData === 'object' && maybeData !== null;
};

export const authService = {
  getMe: async (): Promise<UserProfile> => {
    const res = await api.get<ApiResponse<UserProfile> | UserProfile>('/auth/me');
    return extractApiData(res.data);
  },
  register: async (data: UnknownRecord): Promise<AuthResponse> => {
    const res = await api.post<ApiResponse<AuthResponse> | AuthResponse>('/auth/register', data);
    return extractApiData(res.data);
  },
  login: async (data: UnknownRecord): Promise<AuthResponse> => {
    const res = await api.post<ApiResponse<AuthResponse> | AuthResponse>('/auth/login', data);
    return extractApiData(res.data);
  },
  logout: async (): Promise<void> => {
    await api.post('/auth/logout');
  },
  devBypass: async (): Promise<AuthResponse> => {
    const res = await api.post<ApiResponse<AuthResponse> | AuthResponse>('/auth/dev-bypass');
    return extractApiData(res.data);
  },
  switchRole: async (role: 'customer' | 'seller'): Promise<{ role: string }> => {
    const res = await api.patch<ApiResponse<{ role: string }> | { role: string }>(
      '/users/me/role',
      { role }
    );
    return extractApiData(res.data);
  },
};

export const productService = {
  list: async (
    category?: string,
    featured?: boolean,
    page = 1,
    limit = 20,
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
    const res = await api.get<
      ApiResponse<{
        items: Product[];
        total: number;
        page: number;
        limit: number;
        pages: number;
      }>
    >('/products', {
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
    return extractApiData(res.data);
  },
  listSeller: async (
    category?: string,
    isActive?: boolean,
    stockLevel?: string,
    page = 1,
    limit = 20
  ): Promise<{
    items: Product[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get<
      ApiResponse<{
        items: Product[];
        total: number;
        page: number;
        limit: number;
        pages: number;
      }>
    >('/products/seller', {
      params: {
        category,
        is_active: isActive,
        stock_level: stockLevel,
        page,
        limit,
      },
    });
    return extractApiData(res.data);
  },
  get: async (id: string): Promise<Product> => {
    const res = await api.get<ApiResponse<Product>>(`/products/${id}`);
    return extractApiData(res.data);
  },
  create: async (
    data: Omit<Product, 'id' | 'seller_id' | 'avg_rating' | 'sold_count' | 'is_active'>
  ): Promise<Product> => {
    const res = await api.post<ApiResponse<Product>>('/products', data);
    return extractApiData(res.data);
  },
  update: async (id: string, data: Partial<Product>): Promise<Product> => {
    const res = await api.put<ApiResponse<Product>>(`/products/${id}`, data);
    return extractApiData(res.data);
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/products/${id}`);
  },
};

export const cartService = {
  get: async (): Promise<CartItem[]> => {
    const res = await api.get<ApiResponse<CartItem[]>>('/cart');
    return extractApiData(res.data);
  },
  add: async (productId: string, quantity = 1): Promise<CartItem> => {
    const res = await api.post<ApiResponse<CartItem>>('/cart', { product_id: productId, quantity });
    return extractApiData(res.data);
  },
  update: async (productId: string, quantity: number): Promise<CartItem> => {
    const res = await api.put<ApiResponse<CartItem>>(`/cart/${productId}`, { quantity });
    return extractApiData(res.data);
  },
  remove: async (productId: string): Promise<void> => {
    await api.delete(`/cart/${productId}`);
  },
};

export const orderService = {
  place: async (address: UnknownRecord): Promise<Order> => {
    const res = await api.post<ApiResponse<Order>>('/orders', { delivery_address: address });
    return extractApiData(res.data);
  },
  list: async (
    page = 1,
    limit = 10
  ): Promise<{
    items: Order[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get<
      ApiResponse<{
        items: Order[];
        total: number;
        page: number;
        limit: number;
        pages: number;
      }>
    >('/orders', { params: { page, limit } });
    return extractApiData(res.data);
  },
  get: async (id: string): Promise<Order> => {
    const res = await api.get<ApiResponse<Order>>(`/orders/${id}`);
    return extractApiData(res.data);
  },
  listSellerQueue: async (
    page = 1,
    limit = 10
  ): Promise<{
    items: Order[];
    total: number;
    page: number;
    limit: number;
    pages: number;
  }> => {
    const res = await api.get<
      ApiResponse<{
        items: Order[];
        total: number;
        page: number;
        limit: number;
        pages: number;
      }>
    >('/orders/seller/queue', { params: { page, limit } });
    return extractApiData(res.data);
  },
  updateStatus: async (id: string, status: string): Promise<Order> => {
    const res = await api.put<ApiResponse<Order>>(`/orders/${id}/status`, { status });
    return extractApiData(res.data);
  },
};

export const memoryService = {
  listFacts: async (): Promise<PersistentFact[]> => {
    const res = await api.get<ApiResponse<PersistentFact[]>>('/users/facts');
    return extractApiData(res.data);
  },
  deleteFact: async (factId: string): Promise<void> => {
    await api.delete(`/users/facts/${factId}`);
  },
};

export const addressService = {
  list: async (): Promise<Address[]> => {
    const res = await api.get<ApiResponse<Address[]>>('/addresses');
    return extractApiData(res.data);
  },
  create: async (
    data: Omit<Address, 'id' | 'user_id' | 'is_default'> & { is_default?: boolean }
  ): Promise<Address> => {
    const res = await api.post<ApiResponse<Address>>('/addresses', data);
    return extractApiData(res.data);
  },
  update: async (id: string, data: Partial<Address>): Promise<Address> => {
    const res = await api.put<ApiResponse<Address>>(`/addresses/${id}`, data);
    return extractApiData(res.data);
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/addresses/${id}`);
  },
};

export const healthService = {
  checkApiHealth: async (): Promise<HealthStatus> => {
    const res = await api.get<ApiResponse<HealthStatus> | HealthStatus>('/health');
    const payload = res.data;
    if (isWrappedHealthStatus(payload)) {
      return payload.data;
    }
    return payload;
  },
};
