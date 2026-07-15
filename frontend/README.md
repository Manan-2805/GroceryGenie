# GroceryGenie - Frontend Client

This is the React + TypeScript frontend client for the GroceryGenie voice-first shopping assistant.

*   **Main documentation**: Refer to the main [root README](file:///d:/Project/GrocerGo/README.md).
*   **FastAPI server**: Refer to the [Backend README](file:///d:/Project/GrocerGo/backend/README.md).

## Features
*   **Vite React**: High-performance development and production bundles.
*   **Tailwind CSS v3**: Sleek, modern styling with CSS variables and data-theme attributes for system-wide light/dark themes.
*   **Chat Bubble Overlay**: Sliding bubble interface supporting:
    *   *Text Mode*: Server-Sent Events (SSE) streaming with navigation intents and permission gates.
    *   *Voice Mode*: Persistent WebSocket stream, capturing 16kHz PCM audio, downsampling, and playing synthesized speech with audio queues and barge-in.
*   **Zustand & TanStack Query**: Clean client-side state management and typed API cache bindings.

## Getting Started

### 1. Requirements
*   Node.js >= 18
*   npm

### 2. Install Dependencies
Run from the `frontend/` directory:
```bash
npm install
```

### 3. Run Development Server
```bash
npm run dev
```
Open `http://localhost:5173` to browse the app.

### 4. Build Production Bundle
To compile and test production assets:
```bash
npm run build
```
The compiled output will be generated inside the `dist/` directory.
