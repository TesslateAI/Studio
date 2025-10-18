import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Base path for the application
  // This will be preprocessed during project creation for Docker deployment
  // Kubernetes: Uses '/' since each project has its own hostname
  base: process.env.VITE_BASE_PATH || '/',
  server: {
    host: '0.0.0.0', // Allow external connections (required for Docker)
    port: 5173,
    strictPort: true,
    // Allow requests from any host (needed for production access)
    allowedHosts: ['.localhost', 'your-domain.com', 'studio-demo.tesslate.com'],
    hmr: {
      // Configure HMR WebSocket for proxy environments
      // Protocol: ws for HTTP, wss for HTTPS
      protocol: process.env.VITE_HMR_PROTOCOL || 'ws',
      // Host: Use current page hostname (undefined = same as page)
      host: process.env.VITE_HMR_HOST || undefined,
      // Port: 80 for HTTP, 443 for HTTPS (proxy port, not Vite's internal port)
      clientPort: process.env.VITE_HMR_PORT ? parseInt(process.env.VITE_HMR_PORT) : 80,
      // Path: Vite will automatically prepend the base path
      // e.g., if base="/preview/user1-project3/", HMR path becomes "/preview/user1-project3/@vite/client"
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
