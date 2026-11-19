import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

// The API lives in the FastAPI server; in development /api is proxied to it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  build: { outDir: '../src/michelito/web/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8502' } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
