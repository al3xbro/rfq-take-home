import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API runs separately (see ../server). Proxying in dev keeps the client
// origin-relative, so no CORS round-trips and the same fetch paths work in a
// production build served behind one host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ingest': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
