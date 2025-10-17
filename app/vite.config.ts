import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Parse allowed hosts from environment variable
// No hardcoded defaults - everything comes from environment
const allowedHostsEnv = process.env.VITE_ALLOWED_HOSTS || ''
const allowedHosts = allowedHostsEnv.split(',').map(host => host.trim()).filter(Boolean)

console.log('Vite allowed hosts:', allowedHosts)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: allowedHosts,
    watch: {
      usePolling: true,
      interval: 300,
    },
    hmr: {
      // Use domain from environment for HMR
      host: process.env.APP_DOMAIN || 'localhost',
      protocol: 'ws',
      port: parseInt(process.env.APP_PORT || '80'),
    },
    proxy: {
      '/api': {
        // In Docker, containers communicate via service names on internal network
        // This proxies all /api/* requests to the orchestrator service
        target: 'http://orchestrator:8000',
        changeOrigin: true,
        ws: true, // Enable WebSocket support for /api/chat/ws
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.log('proxy error', err);
          });
          proxy.on('proxyReq', (proxyReq, req, res) => {
            console.log('Proxying:', req.method, req.url, '→', options.target + req.url);
          });
          proxy.on('proxyReqWs', (proxyReq, req, socket, head) => {
            console.log('Proxying WebSocket:', req.url);
          });
        }
      },
      // Explicit WebSocket proxy for /ws path (if needed)
      '/ws': {
        target: 'http://orchestrator:8000',
        ws: true,
        changeOrigin: true,
      },
    }
  }
})
