import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: ['your-domain.com', 'localhost', 'host.docker.internal', '.localhost'],
    proxy: {
      '/api': {
        target: 'http://localhost:8005',
        changeOrigin: true,
        ws: true,
      },
    }
  }
})
