import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './', // Use relative paths for assets - enables access through any base path
  server: {
    host: '0.0.0.0', // Allow external connections (required for Docker)
    port: 5173,
    strictPort: true,
    hmr: {
      // Use environment variables set by our container system
      host: process.env.VITE_HMR_HOST || 'localhost',
      port: process.env.VITE_HMR_PORT ? parseInt(process.env.VITE_HMR_PORT) : 5173,
    },
    watch: {
      // Use polling for reliable file watching in Docker containers
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      interval: process.env.CHOKIDAR_INTERVAL ? parseInt(process.env.CHOKIDAR_INTERVAL) : 1000,
    }
  },
  // Ensure dependencies are properly handled in Docker
  optimizeDeps: {
    include: ['react', 'react-dom']
  }
})
