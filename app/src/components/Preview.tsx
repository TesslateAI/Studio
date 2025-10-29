import React, { useEffect, useRef, useState } from 'react';
import { RefreshCw, ExternalLink, Loader, Monitor, FileText } from 'lucide-react';
import { projectsApi } from '../lib/api';
import { LoadingSpinner } from './PulsingGridSpinner';
import toast from 'react-hot-toast';

interface PreviewProps {
  projectId: number;
  userId: number;
  activeTab?: 'preview' | 'files';
  setActiveTab?: (tab: 'preview' | 'files') => void;
}

export default function Preview({ projectId, userId, activeTab = 'preview', setActiveTab }: PreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPath, setCurrentPath] = useState<string>('/');

  useEffect(() => {
    startDevServer();
  }, [projectId]);

  const startDevServer = async (retryCount = 0) => {
    const maxRetries = 5;
    try {
      setLoading(true);
      const response = await projectsApi.getDevServerUrl(projectId);

      // Check if server is still starting
      if (response.status === 'starting' && retryCount < maxRetries) {
        console.log(`[Preview] Server starting, retry ${retryCount + 1}/${maxRetries} in 2s...`);
        toast.loading('Preview server is starting...', { id: 'dev-server-starting' });
        setTimeout(() => startDevServer(retryCount + 1), 2000);
        return;
      }

      // Server ready or max retries reached
      if (!response.url) {
        throw new Error('No URL returned from server');
      }

      toast.dismiss('dev-server-starting');

      // Add JWT token to URL for NGINX auth-url verification
      // The NGINX ingress controller will extract the Authorization header
      // and forward it to the auth-url endpoint
      const token = localStorage.getItem('token');
      const authenticatedUrl = response.url;

      if (token) {
        // Store token in sessionStorage for iframe to use
        // The iframe will be loaded with credentials to pass cookies/headers
        sessionStorage.setItem(`preview_token_${projectId}`, token);
      }

      setDevServerUrl(authenticatedUrl);
    } catch (error) {
      console.error('Failed to start dev server:', error);
      toast.dismiss('dev-server-starting');
      toast.error('Failed to start preview server');
    } finally {
      setLoading(false);
    }
  };

  const refresh = () => {
    if (iframeRef.current && devServerUrl) {
      iframeRef.current.src = devServerUrl;
    }
  };

  const openInNewTab = () => {
    if (devServerUrl) {
      window.open(devServerUrl, '_blank');
    }
  };

  const restartServer = async () => {
    try {
      setLoading(true);
      toast.loading('Restarting server...', { id: 'restart' });
      const response = await projectsApi.restartDevServer(projectId);
      setDevServerUrl(response.url);
      toast.success('Server restarted successfully', { id: 'restart' });
    } catch (error) {
      console.error('Failed to restart server:', error);
      toast.error('Failed to restart server', { id: 'restart' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const container = document.getElementById('preview-container');
    if (!container || !devServerUrl) return;

    // Auth token handling based on deployment mode:
    // - Kubernetes: NGINX Ingress uses auth-url with query parameter for iframe authentication
    // - Docker: Traefik proxies requests, authentication happens at backend API level (no token needed)
    const token = localStorage.getItem('token');
    const deploymentMode = import.meta.env.DEPLOYMENT_MODE || 'docker';
    console.log('[DEBUG] Deployment mode:', deploymentMode, 'All env:', import.meta.env);
    const authenticatedUrl = token && deploymentMode === 'kubernetes'
      ? `${devServerUrl}?auth_token=${encodeURIComponent(token)}`
      : devServerUrl;

    // Track iframe load errors and implement retry logic
    let loadErrorCount = 0;
    const maxRetries = 3;

    container.innerHTML = `
      <div class="h-full flex flex-col rounded-t-3xl overflow-hidden bg-gray-900/50 backdrop-blur-sm">
        <div class="bg-gradient-to-r from-gray-800/80 to-gray-700/60 border-b border-gray-700/30 p-4 flex items-center justify-between rounded-t-3xl shadow-lg">
          <div class="flex items-center gap-3 flex-1">
            <!-- Navigation Controls -->
            <button id="back-btn" class="p-2.5 hover:bg-gray-600/50 rounded-xl transition-all duration-200 text-gray-300 hover:text-white hover:scale-105" title="Go Back">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 18 9 12 15 6"></polyline>
              </svg>
            </button>
            <button id="forward-btn" class="p-2.5 hover:bg-gray-600/50 rounded-xl transition-all duration-200 text-gray-300 hover:text-white hover:scale-105" title="Go Forward">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </button>
            <button id="refresh-btn" class="p-2.5 hover:bg-gray-600/50 rounded-xl transition-all duration-200 text-gray-300 hover:text-white hover:scale-105" title="Refresh Preview">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"></polyline>
                <polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>

            <!-- URL Bar -->
            <div class="flex-1 flex items-center gap-2 bg-gray-800/50 rounded-xl px-4 py-2 border border-gray-600/30">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
              <span id="url-display" class="text-sm text-gray-300 font-mono truncate">${devServerUrl}${currentPath}</span>
            </div>

            <button id="restart-btn" class="p-2.5 hover:bg-orange-600/20 rounded-xl transition-all duration-200 text-orange-400 hover:text-orange-300 hover:scale-105 border border-orange-500/20" title="Restart Dev Server">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/>
              </svg>
            </button>
            <button id="external-btn" class="p-2.5 hover:bg-blue-600/20 rounded-xl transition-all duration-200 text-gray-300 hover:text-blue-300 hover:scale-105 border border-blue-500/20" title="Open in New Tab">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                <polyline points="15 3 21 3 21 9"></polyline>
                <line x1="10" y1="14" x2="21" y2="3"></line>
              </svg>
            </button>
          </div>

          <div class="flex items-center gap-4 ml-4">
            <!-- Sliding Toggle -->
            <div class="relative bg-gray-700/50 backdrop-blur-sm p-1 rounded-2xl border border-gray-600/30 shadow-inner">
              <div class="absolute top-1 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl shadow-lg transition-all duration-300 ease-in-out ${
                activeTab === 'preview' ? 'left-1 w-20' : 'left-[85px] w-16'
              }"></div>

              <div class="relative flex">
                <button id="tab-preview" class="relative z-10 px-4 py-2 flex items-center gap-2 rounded-xl font-medium transition-all duration-300 text-sm ${
                  activeTab === 'preview' ? 'text-white' : 'text-gray-400 hover:text-gray-200'
                }">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                    <line x1="8" y1="21" x2="16" y2="21"/>
                    <line x1="12" y1="17" x2="12" y2="21"/>
                  </svg>
                  Preview
                </button>
                <button id="tab-code" class="relative z-10 px-4 py-2 flex items-center gap-2 rounded-xl font-medium transition-all duration-300 text-sm ${
                  activeTab === 'files' ? 'text-white' : 'text-gray-400 hover:text-gray-200'
                }">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <line x1="16" y1="13" x2="8" y2="13"/>
                    <line x1="16" y1="17" x2="8" y2="17"/>
                    <polyline points="10 9 9 9 8 9"/>
                  </svg>
                  Code
                </button>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <div id="live-status-dot" class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
              <span id="live-status-text" class="text-sm text-gray-300 font-medium px-3 py-1 bg-gray-800/50 rounded-full border border-gray-600/30">Live</span>
            </div>
          </div>
        </div>
        <div class="flex-1 p-2 bg-gray-800/20">
          <iframe
            id="preview-iframe"
            src="${authenticatedUrl}"
            class="w-full h-full bg-white rounded-2xl shadow-2xl border border-gray-700/30"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
          ></iframe>
        </div>
      </div>
    `;

    const backBtn = document.getElementById('back-btn');
    const forwardBtn = document.getElementById('forward-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const restartBtn = document.getElementById('restart-btn');
    const externalBtn = document.getElementById('external-btn');
    const tabPreview = document.getElementById('tab-preview');
    const tabCode = document.getElementById('tab-code');
    const iframe = document.getElementById('preview-iframe') as HTMLIFrameElement;
    const urlDisplay = document.getElementById('url-display');
    const liveStatusDot = document.getElementById('live-status-dot');
    const liveStatusText = document.getElementById('live-status-text');

    // Handle iframe load errors with retry logic
    const handleIframeError = () => {
      loadErrorCount++;
      console.log(`[Preview] Iframe load attempt ${loadErrorCount} failed`);

      if (loadErrorCount <= maxRetries) {
        // Update status indicator
        if (liveStatusDot) liveStatusDot.className = 'w-2 h-2 bg-yellow-400 rounded-full animate-pulse';
        if (liveStatusText) liveStatusText.textContent = 'Starting...';

        // Retry after a delay
        const retryDelay = Math.min(2000 * loadErrorCount, 6000); // 2s, 4s, 6s
        console.log(`[Preview] Retrying in ${retryDelay}ms...`);
        setTimeout(() => {
          console.log(`[Preview] Retry attempt ${loadErrorCount}/${maxRetries}`);
          iframe.src = authenticatedUrl;
        }, retryDelay);
      } else {
        // Max retries reached
        console.error('[Preview] Max retries reached, preview failed to load');
        if (liveStatusDot) liveStatusDot.className = 'w-2 h-2 bg-red-400 rounded-full';
        if (liveStatusText) liveStatusText.textContent = 'Error';
        toast.error('Preview failed to load. Try restarting the server.');
      }
    };

    const handleIframeLoad = () => {
      // Reset error count on successful load
      loadErrorCount = 0;
      console.log('[Preview] Iframe loaded successfully');
      if (liveStatusDot) liveStatusDot.className = 'w-2 h-2 bg-green-400 rounded-full animate-pulse';
      if (liveStatusText) liveStatusText.textContent = 'Live';
    };

    // Attach load/error handlers
    iframe.addEventListener('load', handleIframeLoad);
    iframe.addEventListener('error', handleIframeError);

    // Navigation handlers
    if (backBtn) {
      backBtn.onclick = () => {
        iframe.contentWindow?.postMessage({ type: 'navigate', direction: 'back' }, '*');
      };
    }

    if (forwardBtn) {
      forwardBtn.onclick = () => {
        iframe.contentWindow?.postMessage({ type: 'navigate', direction: 'forward' }, '*');
      };
    }

    if (refreshBtn) {
      refreshBtn.onclick = () => {
        iframe.src = iframe.src;
      };
    }

    if (restartBtn) {
      restartBtn.onclick = () => {
        restartServer();
      };
    }

    if (externalBtn) {
      externalBtn.onclick = () => {
        window.open(devServerUrl, '_blank');
      };
    }

    if (tabPreview && setActiveTab) {
      tabPreview.onclick = () => {
        setActiveTab('preview');
      };
    }

    if (tabCode && setActiveTab) {
      tabCode.onclick = () => {
        setActiveTab('files');
      };
    }

    // Listen for URL changes from iframe
    const handleMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === 'url-change') {
        // Extract pathname from the full URL
        try {
          const url = new URL(event.data.url);
          const newPath = url.pathname + url.search + url.hash;
          setCurrentPath(newPath);
          // Query for the element each time to avoid stale references
          const urlDisplayElement = document.getElementById('url-display');
          if (urlDisplayElement) {
            urlDisplayElement.textContent = `${devServerUrl}${newPath}`;
          }
        } catch (e) {
          // Fallback if URL parsing fails
          const newPath = event.data.url || '/';
          setCurrentPath(newPath);
          const urlDisplayElement = document.getElementById('url-display');
          if (urlDisplayElement) {
            urlDisplayElement.textContent = `${devServerUrl}${newPath}`;
          }
        }
      }
    };

    window.addEventListener('message', handleMessage);

    iframeRef.current = iframe;

    // Cleanup listener
    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [devServerUrl, activeTab, setActiveTab, currentPath]);

  useEffect(() => {
    const container = document.getElementById('preview-container');
    if (!container || loading) return;

    if (!devServerUrl) {
      container.innerHTML = `
        <div class="h-full flex items-center justify-center bg-gray-800">
          <div class="text-center text-gray-400">
            <p class="mb-2">Failed to start preview server</p>
            <button 
              id="restart-error-btn"
              class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Restart Server
            </button>
          </div>
        </div>
      `;
      
      const restartErrorBtn = document.getElementById('restart-error-btn');
      if (restartErrorBtn) {
        restartErrorBtn.onclick = () => {
          restartServer();
        };
      }
    }
  }, [loading, devServerUrl]);

  useEffect(() => {
    const container = document.getElementById('preview-container');
    if (!container) return;

    if (loading) {
      container.innerHTML = `
        <div class="h-full flex items-center justify-center bg-gray-800">
          <div class="text-center text-gray-400">
            <canvas id="pulsing-grid-spinner" width="80" height="80" class="mx-auto mb-2"></canvas>
            <p>Starting development server...</p>
          </div>
        </div>
      `;

      // Initialize the pulsing grid animation
      const canvas = document.getElementById('pulsing-grid-spinner') as HTMLCanvasElement;
      if (!canvas) return;

      const context = canvas.getContext('2d');
      if (!context) return;

      // Store as non-nullable for use in nested function
      const ctx: CanvasRenderingContext2D = context;

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      let time = 0;
      let lastTime = 0;
      let animationId: number;

      const gridSize = 5;
      const spacing = 6;
      const breathingSpeed = 0.5;
      const colorPulseSpeed = 1.0;

      const middleEight = [
        { row: 1, col: 2 }, { row: 2, col: 1 }, { row: 2, col: 3 }, { row: 3, col: 2 },
        { row: 1, col: 1 }, { row: 1, col: 3 }, { row: 3, col: 1 }, { row: 3, col: 3 }
      ];

      const isMiddleEight = (row: number, col: number) => {
        return middleEight.some(pos => pos.row === row && pos.col === col);
      };

      function animate(timestamp: number) {
        if (!lastTime) lastTime = timestamp;
        const deltaTime = timestamp - lastTime;
        lastTime = timestamp;
        time += deltaTime * 0.001;

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const breathingFactor = Math.sin(time * breathingSpeed) * 0.2 + 1.0;

        // Draw center dot (orange)
        ctx.beginPath();
        ctx.arc(centerX, centerY, 2, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255, 107, 0, 0.9)";
        ctx.fill();

        // Draw grid
        for (let row = 0; row < gridSize; row++) {
          for (let col = 0; col < gridSize; col++) {
            if (row === Math.floor(gridSize / 2) && col === Math.floor(gridSize / 2)) continue;

            const baseX = (col - (gridSize - 1) / 2) * spacing;
            const baseY = (row - (gridSize - 1) / 2) * spacing;
            const distance = Math.sqrt(baseX * baseX + baseY * baseY);
            const maxDistance = (spacing * Math.sqrt(2) * (gridSize - 1)) / 2;
            const normalizedDistance = distance / maxDistance;
            const angle = Math.atan2(baseY, baseX);

            const radialPhase = (time - normalizedDistance) % 1;
            const radialWave = Math.sin(radialPhase * Math.PI * 2) * 3;
            const breathingX = baseX * breathingFactor;
            const breathingY = baseY * breathingFactor;

            const waveX = centerX + breathingX + Math.cos(angle) * radialWave;
            const waveY = centerY + breathingY + Math.sin(angle) * radialWave;

            const baseSize = 1.2 + (1 - normalizedDistance) * 1;
            const pulseFactor = Math.sin(time * 2 + normalizedDistance * 5) * 0.6 + 1;
            const dotSize = baseSize * pulseFactor;

            const isMiddle = isMiddleEight(row, col);
            let r, g, b;
            if (isMiddle) {
              const orangePulse = Math.sin(time * colorPulseSpeed + normalizedDistance * 3) * 0.2 + 0.8;
              r = 255;
              g = Math.floor(107 * orangePulse);
              b = 0;
            } else {
              const blueAmount = Math.sin(time * colorPulseSpeed + normalizedDistance * 3) * 0.3 + 0.3;
              const whiteness = 1 - blueAmount;
              r = Math.floor(255 * whiteness + 200 * blueAmount);
              g = Math.floor(255 * whiteness + 220 * blueAmount);
              b = 255;
            }

            const opacity = 0.5 + Math.sin(time * 1.5 + angle * 3) * 0.2 + normalizedDistance * 0.3;
            ctx.beginPath();
            ctx.arc(waveX, waveY, dotSize, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + r + ', ' + g + ', ' + b + ', ' + opacity + ')';
            ctx.fill();
          }
        }
        animationId = requestAnimationFrame(animate);
      }
      animationId = requestAnimationFrame(animate);

      // Store animation ID for cleanup
      (container as any).__animationId = animationId;
    }
    // Cleanup function
    return () => {
      if ((container as any).__animationId) {
        cancelAnimationFrame((container as any).__animationId);
        delete (container as any).__animationId;
      }
    };
  }, [loading]);

  return null;
}