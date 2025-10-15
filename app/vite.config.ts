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
    proxy: {
      '/api': {
        // In Docker, containers communicate via service names on internal network
        // This proxies all /api/* requests to the orchestrator service
        target: 'http://orchestrator:8000',
        changeOrigin: true,
        ws: true,
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.log('proxy error', err);
          });
          proxy.on('proxyReq', (proxyReq, req, res) => {
            console.log('Proxying:', req.method, req.url, '→', options.target + req.url);
          });
        }
      },
    }
  }
})
