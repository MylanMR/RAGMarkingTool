import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy API routes to the FastAPI backend during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ingest': 'http://localhost:8000',
      '/query': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
});
