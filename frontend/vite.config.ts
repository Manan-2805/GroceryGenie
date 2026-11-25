import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
const backend = process.env.GROCERY_VITE_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/uploads': backend,
      '/api': {
        target: backend,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
