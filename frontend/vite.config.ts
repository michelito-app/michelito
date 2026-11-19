import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

// La API vive en el servidor de FastAPI; en desarrollo se le delega /api.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  build: { outDir: '../src/finanzas/web/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8502' } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
