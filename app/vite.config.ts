import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Parse allowed hosts from environment variable
// Defaults to common development and production hosts
const defaultAllowedHosts = 'your-domain.com,studio-test.tesslate.com,studio-demo.tesslate.com,localhost,host.docker.internal,.localhost'
const allowedHostsEnv = process.env.VITE_ALLOWED_HOSTS || defaultAllowedHosts
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
      host: 'localhost',
      protocol: 'ws',
    },
    proxy: {
      '/api': {
        // Use orchestrator service name in Docker, localhost for native development
        target: process.env.VITE_API_URL || 'http://orchestrator:8000',
        changeOrigin: true,
        ws: true,
      },
    }
  }
})
