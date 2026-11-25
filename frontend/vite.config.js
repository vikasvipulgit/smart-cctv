import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the dashboard runs on :5173 and forwards API calls to the backend on :8000.
const backend = process.env.BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // reachable from your phone on the same Wi-Fi
    proxy: {
      '/api': backend,
      '/media': backend,
      '/ws': { target: backend.replace('http', 'ws'), ws: true },
    },
  },
})
