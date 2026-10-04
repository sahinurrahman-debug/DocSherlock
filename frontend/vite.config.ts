import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: the Vite server proxies API calls to FastAPI on :8000. Prod: the same origin serves both (see backend/app/main.py).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, open: true,proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } },
  build: { sourcemap: false, chunkSizeWarningLimit: 700 },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts', css: false },
})
