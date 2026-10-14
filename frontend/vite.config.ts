import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = { '/api': 'http://127.0.0.1:8000' }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: backend },
  preview: { proxy: backend },
  // MapLibre GL alone is ~1 MB; it loads lazily in its own chunk after the planner
  build: { chunkSizeWarningLimit: 1100 },
})
