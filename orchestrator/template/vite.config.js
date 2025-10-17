import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Base path is set via command line when needed (--base flag)
  // This allows dynamic configuration without rebuilding
  // In Tesslate Studio, this should match the preview URL path
  base: process.env.VITE_BASE_PATH || '/',
  server: {
    host: '0.0.0.0', // Allow external connections (required for Docker)
    port: 5173,
    strictPort: true,
    // Allow requests from any host (needed for production access)
    allowedHosts: ['.localhost', 'your-domain.com', 'studio-demo.tesslate.com'],
    hmr: {
      // CRITICAL: Configure HMR to work through Traefik proxy
      // The WebSocket connects to the same host as the page URL
      protocol: process.env.VITE_HMR_PROTOCOL || 'ws',
      // Use the page's hostname for WebSocket connection
      host: process.env.VITE_HMR_HOST || undefined,
      // Use port from environment (80 for HTTP, 443 for HTTPS)
      clientPort: process.env.VITE_HMR_PORT ? parseInt(process.env.VITE_HMR_PORT) : 80,
      // Vite automatically uses the base path for WebSocket, no need to duplicate it
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
