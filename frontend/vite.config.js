import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies API routes to the FastAPI backend.
const api = 'http://localhost:8000';
const routes = ['/auth', '/users', '/policy', '/models', '/products', '/governance',
  '/ingest', '/query', '/audit', '/health'];

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: Object.fromEntries(routes.map((r) => [r, api])) },
});
