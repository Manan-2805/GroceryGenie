# GroceryGenie - Frontend Client

> **React + TypeScript Frontend for the Voice-First AI Grocery Shopping Assistant**

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)](https://vitejs.dev)
[![Tailwind](https://img.shields.io/badge/Tailwind-3-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)

---

## 📋 Overview

The GroceryGenie frontend is a **modern, responsive web application** built with React 19 and TypeScript. It provides:

- **🎤 AI Assistant Page**: Full-page agent interface with text and voice chat modes
- **📦 Shopping Experience**: Product catalog, cart management, checkout, order tracking
- **🏪 Seller Dashboard**: Inventory management, fulfillment queue, analytics
- **🌙 Dark Mode**: System-wide theme with CSS variables and data-theme attributes
- **🎵 Voice System**: Real-time audio capture and playback with Web Audio API

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    React Application                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    App (Root)                            │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │  QueryClient  │  │VoiceSession  │  │  BrowserRouter│  │    │
│  │  │  Provider     │  │  Provider    │  │              │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    AppContent                            │    │
│  │  ┌──────────┐  ┌──────────────────┐  ┌──────────────┐  │    │
│  │  │ NavHeader│  │     Routes       │  │ Navigation   │  │    │
│  │  │ (Sticky) │  │  ┌──────────┐    │  │ Listener     │  │    │
│  │  └──────────┘  │  │ /agent   │    │  └──────────────┘  │    │
│  │                │  │ /items   │    │                     │    │
│  │                │  │ /cart    │    │                     │    │
│  │                │  │ /orders  │    │                     │    │
│  │                │  │ /seller  │    │                     │    │
│  │                │  │ ...      │    │                     │    │
│  │                │  └──────────┘    │                     │    │
│  │                └──────────────────┘                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    State Layer                           │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │  Zustand     │  │ TanStack     │  │  Axios       │  │    │
│  │  │  (uiStore)   │  │  Query       │  │  (API client)│  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Setup

### Prerequisites

- Node.js >= 18
- npm (or pnpm/yarn)

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
npm run dev
```

Opens at [http://localhost:5173](http://localhost:5173)

### Production Build

```bash
npm run build
```

Output in `dist/` directory.

### Code Quality

```bash
npm run check        # Lint + TypeScript check
npm run lint         # ESLint only
npm run typecheck    # TypeScript only
```

---

## 📁 Project Structure

```
frontend/
├── public/                   # Static assets (favicon, icons)
├── src/
│   ├── main.tsx              # React entry point
│   ├── App.tsx               # Root component (routing, layout, navigation)
│   ├── index.css             # Tailwind + global styles + dark mode
│   ├── assets/               # Images, SVGs
│   ├── components/           # Shared components
│   │   ├── ChatBubble.tsx    # Floating chat bubble (legacy, replaced by Agent page)
│   │   ├── CustomDialog.tsx  # Reusable dialog
│   │   └── DataTable.tsx     # Reusable data table with sorting/filtering/export
│   ├── contexts/
│   │   └── VoiceSessionContext.tsx  # Voice WebSocket provider
│   ├── pages/
│   │   ├── Agent.tsx         # Full AI Assistant page (text + voice)
│   │   ├── Cart.tsx          # Shopping cart
│   │   ├── Catalog.tsx       # Product catalog with filters + infinite scroll
│   │   ├── Checkout.tsx      # Checkout flow
│   │   ├── ErrorPage.tsx     # Global error display
│   │   ├── FulfillmentQueue.tsx  # Seller order fulfillment
│   │   ├── Home.tsx          # Landing page with featured products
│   │   ├── InventoryManagement.tsx # Seller inventory with CRUD
│   │   ├── ItemDetail.tsx    # Product detail page + RAG Q&A + reviews
│   │   ├── Login.tsx         # Authentication (Google OAuth + dev bypass)
│   │   ├── Maintenance.tsx   # Backend unavailable page
│   │   ├── Orders.tsx        # Customer order history + ratings
│   │   ├── SellerAnalysis.tsx # Seller analytics (revenue, categories, trends)
│   │   ├── SellerDashboard.tsx # Seller dashboard (KPI cards, pending orders)
│   │   └── Settings.tsx      # User settings (theme, role, addresses, facts)
│   ├── services/
│   │   └── api.ts            # Axios-based API client with all services
│   └── store/
│       └── uiStore.ts        # Zustand UI state (theme, session, health)
├── index.html                # HTML entry point
├── vite.config.ts            # Vite configuration (proxy to backend)
├── tailwind.config.js        # Tailwind CSS configuration
├── tsconfig.json             # TypeScript configuration
├── eslint.config.js          # ESLint configuration
├── prettier.config.js        # Prettier configuration
└── package.json              # Dependencies and scripts
```

---

## 🎯 Pages

| Route | Page | Purpose | Access |
|-------|------|---------|--------|
| `/` | Home | Landing page with featured products | Customer |
| `/agent` | **Agent** | Full AI Assistant (text + voice chat) | All users |
| `/items` | Catalog | Product listing with filters + infinite scroll | Customer |
| `/items/:id` | Item Detail | Product details + RAG Q&A + reviews | Customer |
| `/cart` | Cart | Shopping cart management | Customer |
| `/checkout` | Checkout | Order placement flow | Customer |
| `/orders` | Orders | Order history and tracking + ratings | Customer |
| `/settings` | Settings | Profile, theme, role switch, addresses, facts | All users |
| `/seller` | Seller Dashboard | Business overview (KPI cards) | Seller |
| `/fulfillment` | Fulfillment Queue | Order processing (status transitions) | Seller |
| `/inventory` | Inventory | Product management (CRUD + image upload) | Seller |
| `/analysis` | Analysis | Sales analytics (revenue, categories, trends) | Seller |
| `/maintenance` | Maintenance | Backend unavailable | All |
| `/error` | Error | Application error | All |

---

## 🤖 AI Agent Page (`/agent`)

The flagship AI Assistant page replaces the old floating ChatBubble overlay with a full-page experience:

### Features

- **Mode Selection**: Welcome screen with Text and Voice options
- **Text Chat**: SSE streaming with real-time word-by-word display
- **Voice Chat**: WebSocket-based with VAD, ASR, TTS pipeline
- **Structured Options**: Agent can present clickable choices
- **Free Input**: Custom text alongside structured options
- **Permission Cards**: Rich UI for approving/denying actions
- **Role Switch Cards**: Structured UI for role switching with confirm/deny
- **Navigation Suggestions**: Agent can suggest page navigation
- **Loading States**: Animated dots during processing
- **Error Handling**: Graceful error recovery
- **Auto-focus**: Input field auto-focuses on chat start

### Text Chat Flow

1. User types message → POST `/api/v1/chat/text` (SSE)
2. Backend streams `data:` events with:
   - `delta`: Word chunks for real-time display
   - `permission_request`: Action approval needed
   - `options_request`: Structured choices from agent
   - `role_switch_request`: Role change confirmation
   - `navigate_to`: Suggested page navigation
3. Frontend renders each event type appropriately

### Voice Chat Flow

1. User clicks "Voice Chat" → WebSocket connects
2. Audio captured via `getUserMedia()` at 16kHz
3. PCM chunks sent to backend via WebSocket
4. Backend processes: VAD → ASR → Agent → TTS
5. Audio response streamed back and played via Web Audio API
6. Supports barge-in (interrupt agent while speaking)

---

## 🎵 Voice System

### Audio Capture (Microphone → Backend)

```typescript
// In VoiceSessionContext.tsx
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    channelCount: 1,        // Mono
    sampleRate: 16000,      // 16kHz
    echoCancellation: true,
    noiseSuppression: true,
  },
});

// Convert Float32 to PCM16 Int16 and send via WebSocket
const pcmData = new Int16Array(inputData.length);
for (let i = 0; i < inputData.length; i++) {
  pcmData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
}
ws.send(pcmData.buffer);
```

### Audio Playback (Backend → Speaker)

```typescript
// Receive PCM16 binary chunks from WebSocket
const float32Array = new Float32Array(int16Array.length);
for (let i = 0; i < int16Array.length; i++) {
  float32Array[i] = int16Array[i] / 32768.0;
}

// Queue and play with AudioContext
const audioBuffer = audioCtx.createBuffer(1, chunk.length, 16000);
audioBuffer.getChannelData(0).set(float32Array);
const source = audioCtx.createBufferSource();
source.buffer = audioBuffer;
source.connect(audioCtx.destination);
source.start(playTime);
```

### Key Features
- **Audio Queue**: Progressive playback with gap-free scheduling
- **Barge-in**: Stop playback immediately when user starts speaking
- **WebSocket Heartbeat**: Ping/pong every 25 seconds
- **Auto-reconnection**: Up to 3 retries with exponential backoff
- **Audio Level**: Real-time RMS calculation for waveform visualization

---

## 🌙 Theming

The application supports **light and dark themes** via CSS variables and the `data-theme` attribute on `<html>`.

```typescript
// In uiStore.ts
const theme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', theme);
```

Theme classes:
- Light: `bg-white dark:bg-gray-950`
- Dark: `text-gray-800 dark:text-gray-200`
- Borders: `border-gray-100 dark:border-gray-900`

---

## 📦 State Management

### Zustand (UI Store)
```typescript
// In uiStore.ts
type UIState = {
  theme: 'light' | 'dark';
  sessionId: string | null;
  voiceOk: boolean;
  backendUnreachable: boolean;
  appError: string | null;
  // ... setters
};
```

### TanStack Query (Server State)
```typescript
// Automatic caching and revalidation
const { data: products } = useQuery({
  queryKey: ['products', filters],
  queryFn: () => productService.list(filters),
});
```

### Axios (HTTP Client)
- Automatic JWT cookie passing (`withCredentials: true`)
- Numeric field conversion (price, ratings)
- Error interceptor for backend unreachable detection
- Network error → redirect to `/maintenance`
- 500 errors → redirect to `/error`

---

## 🎨 Styling

Built with **Tailwind CSS v3**:

```javascript
// tailwind.config.js
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {},
  },
};
```

### Common Patterns
- Cards: `rounded-2xl border shadow-xl`
- Buttons: `rounded-xl px-4 py-2 font-bold transition`
- Inputs: `rounded-xl border focus:ring-2 focus:ring-purple-600/50`
- Badges: `rounded-full px-3 py-1 text-xs font-medium`
- Gradients: `bg-gradient-to-r from-purple-600 to-indigo-600`

---

## 🔧 Configuration

### Environment Variables (via Vite)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `/api/v1` | Backend API base URL |

The API base URL is configured in `src/services/api.ts`:
```typescript
const BASE_URL = '/api/v1';
```

This works with Vite's proxy in development and nginx in production.

---

## 📦 Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^19.2.7 | UI framework |
| `react-router-dom` | ^7.18.1 | Client-side routing |
| `@tanstack/react-query` | ^5.101.2 | Server state management |
| `zustand` | ^5.0.14 | Client state management |
| `axios` | ^1.18.1 | HTTP client |
| `lucide-react` | ^1.22.0 | Icon library |
| `tailwindcss` | ^3.4.19 | Utility CSS |
| `vite` | ^8.1.1 | Build tool |
| `typescript` | ~6.0.2 | Type safety |

---

## 🐳 Docker

```dockerfile
# Build production image
docker build -f Dockerfile.prod -t grocergenie-frontend .
```

Served via nginx with reverse proxy to the backend.

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| `npm run dev` fails | Run `npm install` first |
| TypeScript errors | Run `npm run typecheck` |
| API calls fail | Ensure backend is running on port 8000 |
| Voice not working | Check browser permissions for microphone |
| Audio distortion | Ensure sample rate is 16kHz, mono channel |
| WebSocket disconnects | Check network, verify backend health |
| CSS not applying | Run `npm run dev` to rebuild styles |