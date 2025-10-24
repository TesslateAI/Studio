import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Always root - subdomain routing handles the rest!
  base: '/',
  server: {
    host: '0.0.0.0', // Allow external connections (required for Docker)
    port: 5173,
    strictPort: true,
    // Allow wildcard subdomains for preview containers
    allowedHosts: process.env.VITE_ALLOWED_HOSTS ? [process.env.VITE_ALLOWED_HOSTS] : 'all',
    // HMR works out of the box with subdomain routing
    // Browser auto-detects protocol and port from URL
    hmr: {
      // No configuration needed!
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
