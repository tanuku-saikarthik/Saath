import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// `npm run dev` proxies /api to the FastAPI backend on :8000.
// `npm run build:single` inlines everything into one HTML file (used for the shareable demo preview).
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'single' ? [viteSingleFile()] : [])],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
}))
