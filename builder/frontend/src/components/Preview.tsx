import React, { useEffect, useRef, useState } from 'react';
import { RefreshCw, ExternalLink, Loader, Monitor, FileText } from 'lucide-react';
import { projectsApi } from '../lib/api';
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

  useEffect(() => {
    startDevServer();
  }, [projectId]);

  const startDevServer = async () => {
    try {
      setLoading(true);
      const response = await projectsApi.getDevServerUrl(projectId);
      setDevServerUrl(response.url);
    } catch (error) {
      console.error('Failed to start dev server:', error);
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

    container.innerHTML = `
      <div class="h-full flex flex-col rounded-t-3xl overflow-hidden bg-gray-900/50 backdrop-blur-sm">
        <div class="bg-gradient-to-r from-gray-800/80 to-gray-700/60 border-b border-gray-700/30 p-4 flex items-center justify-between rounded-t-3xl shadow-lg">
          <div class="flex items-center gap-3">
            <button id="refresh-btn" class="p-2.5 hover:bg-gray-600/50 rounded-xl transition-all duration-200 text-gray-300 hover:text-white hover:scale-105" title="Refresh Preview">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"></polyline>
                <polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
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

          <div class="flex items-center gap-4">
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
              <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
              <span class="text-sm text-gray-300 font-medium px-3 py-1 bg-gray-800/50 rounded-full border border-gray-600/30">${devServerUrl}</span>
            </div>
          </div>
        </div>
        <div class="flex-1 p-2 bg-gray-800/20">
          <iframe
            id="preview-iframe"
            src="${devServerUrl}"
            class="w-full h-full bg-white rounded-2xl shadow-2xl border border-gray-700/30"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
          ></iframe>
        </div>
      </div>
    `;

    const refreshBtn = document.getElementById('refresh-btn');
    const restartBtn = document.getElementById('restart-btn');
    const externalBtn = document.getElementById('external-btn');
    const tabPreview = document.getElementById('tab-preview');
    const tabCode = document.getElementById('tab-code');
    const iframe = document.getElementById('preview-iframe') as HTMLIFrameElement;

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

    iframeRef.current = iframe;
  }, [devServerUrl, activeTab, setActiveTab]);

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
            <svg class="animate-spin h-8 w-8 mx-auto mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p>Starting development server...</p>
          </div>
        </div>
      `;
    }
  }, [loading]);

  return null;
}