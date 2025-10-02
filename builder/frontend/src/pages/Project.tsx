import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Monitor, FileText, RefreshCw, ExternalLink, RotateCcw } from 'lucide-react';
import Chat from '../components/Chat';
import Preview from '../components/Preview';
import CodeEditor from '../components/CodeEditor';
import { projectsApi } from '../lib/api';
import toast from 'react-hot-toast';

export default function Project() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [activeView, setActiveView] = useState<'preview' | 'files'>(() => {
    // Load saved tab preference from localStorage
    const saved = localStorage.getItem(`active_tab_${id}`);
    return (saved as 'preview' | 'files') || 'preview';
  });
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const projectId = parseInt(id!);
  
  // Debounced refresh for preview
  const refreshTimeoutRef = React.useRef<NodeJS.Timeout>();

  // Save active view to localStorage whenever it changes
  const handleViewChange = (view: 'preview' | 'files') => {
    setActiveView(view);
    localStorage.setItem(`active_tab_${id}`, view);
  };

  useEffect(() => {
    loadProject();
    loadDevServerUrl();
  }, [projectId]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
    };
  }, []);

  // Auto-stop container when user navigates away
  useEffect(() => {
    return () => {
      // Stop container when component unmounts (user navigates away)
      if (projectId && devServerUrl) {
        fetch(`/api/projects/${projectId}/stop-dev-container`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }).catch(err => console.log('Container stop cleanup:', err));
      }
    };
  }, [projectId, devServerUrl]);

  const loadProject = async () => {
    try {
      const [projectData, filesData] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.getFiles(projectId),
      ]);
      setProject(projectData);
      setFiles(filesData);
      
      console.log(`📂 Loaded project with ${filesData.length} files:`, filesData.map(f => f.file_path));
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

  const handleFileUpdate = async (filePath: string, content: string) => {
    console.log(`📝 File ready: ${filePath} (${content.length} chars)`);
    
    // Update frontend state
    setFiles(prev => {
      const existing = prev.find(f => f.file_path === filePath);
      if (existing) {
        return prev.map(f => 
          f.file_path === filePath ? { ...f, content } : f
        );
      }
      return [...prev, { file_path: filePath, content }];
    });
    
    // Save file to disk so container can see it
    try {
      await projectsApi.saveFile(projectId, filePath, content);
      console.log(`💾 File saved to disk: ${filePath}`);
    } catch (error) {
      console.error('Failed to save file to disk:', error);
      toast.error(`Failed to save ${filePath}`);
    }
    
    // Wait a moment then let Vite HMR handle the changes
    // No need to manually refresh the iframe if HMR is working properly
    if (filePath.match(/\.(jsx?|tsx?|css|html)$/i)) {
      console.log(`🔥 File change detected: ${filePath} - Vite HMR should handle this automatically`);
      
      // Clear any existing timeout
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
      
      // Only force refresh as a fallback if HMR doesn't work within 5 seconds
      refreshTimeoutRef.current = setTimeout(() => {
        console.log('⚠️ HMR fallback: Force refreshing preview iframe');
        const iframe = document.getElementById('preview-iframe') as HTMLIFrameElement;
        if (iframe) {
          try {
            const currentSrc = iframe.src;
            iframe.src = currentSrc + (currentSrc.includes('?') ? '&' : '?') + 'hmr_fallback=' + Date.now();
          } catch (error) {
            console.log('Preview refresh error:', error);
          }
        }
      }, 5000); // 5 second delay - only refresh if HMR didn't work
    }
  };

  const loadDevServerUrl = async () => {
    try {
      const response = await projectsApi.getDevServerUrl(projectId);
      setDevServerUrl(response.url);
      console.log('Dev server URL loaded:', response.url);
    } catch (error) {
      console.error('Failed to get dev server URL:', error);
      // Retry after 3 seconds if failed
      setTimeout(() => {
        console.log('Retrying dev server URL load...');
        loadDevServerUrl();
      }, 3000);
    }
  };

  const refreshPreview = () => {
    if (devServerUrl) {
      const iframe = document.getElementById('preview-iframe') as HTMLIFrameElement;
      if (iframe) {
        // Force a refresh by adding a timestamp parameter
        const currentSrc = iframe.src;
        const separator = currentSrc.includes('?') ? '&' : '?';
        iframe.src = currentSrc.split('?')[0] + separator + 't=' + Date.now();
      }
    }
  };

  const openInNewTab = () => {
    if (devServerUrl) {
      window.open(devServerUrl, '_blank');
    }
  };

  const restartServer = async () => {
    try {
      toast.loading('Restarting server...', { id: 'restart' });
      const response = await projectsApi.restartDevServer(projectId);
      setDevServerUrl(response.url);
      toast.success('Server restarted successfully', { id: 'restart' });
    } catch (error) {
      console.error('Failed to restart server:', error);
      toast.error('Failed to restart server', { id: 'restart' });
    }
  };

  // Get user ID from JWT token
  const token = localStorage.getItem('token');
  const userId = project ? project.owner_id : null;

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading project...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-orange-50 via-white to-orange-50/30">
      {/* Top navigation bar */}
      <div className="bg-white/80 backdrop-blur-lg border-b border-orange-200/30 p-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 px-3 py-2 text-orange-700 hover:text-orange-900 hover:bg-orange-100/50 rounded-lg transition-all duration-200 backdrop-blur-sm"
          >
            <ArrowLeft size={18} />
            <span className="text-sm font-medium">Back to Projects</span>
          </button>
          {project && (
            <div className="text-gray-600 text-sm">
              <span className="text-orange-400">•</span> {project.name}
            </div>
          )}
        </div>

        <div className="flex items-center gap-4">
          {/* Preview controls - only show when preview is active */}
          {activeView === 'preview' && devServerUrl && (
            <>
              <button
                onClick={refreshPreview}
                className="p-2 hover:bg-gray-600/50 rounded-lg transition-all duration-200 text-gray-300 hover:text-white"
                title="Refresh Preview"
              >
                <RefreshCw size={16} />
              </button>
              <button
                onClick={restartServer}
                className="p-2 hover:bg-orange-600/20 rounded-lg transition-all duration-200 text-orange-400 hover:text-orange-300 border border-orange-500/20"
                title="Restart Dev Server"
              >
                <RotateCcw size={16} />
              </button>
              <button
                onClick={openInNewTab}
                className="p-2 hover:bg-blue-600/20 rounded-lg transition-all duration-200 text-gray-300 hover:text-blue-300 border border-blue-500/20"
                title="Open in New Tab"
              >
                <ExternalLink size={16} />
              </button>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
                <span className="text-xs text-gray-300 font-medium px-2 py-1 bg-gray-700/50 rounded-full">{devServerUrl}</span>
              </div>
            </>
          )}

          {/* View toggle */}
          <div className="relative bg-gray-100 p-1 rounded-xl shadow-inner">
            <div className={`absolute top-1 bottom-1 bg-orange-500 rounded-lg shadow-lg transition-all duration-300 ease-in-out ${
              activeView === 'preview' ? 'left-1 right-[50%]' : 'left-[50%] right-1'
            }`}></div>
            
            <div className="relative flex">
              <button
                onClick={() => handleViewChange('preview')}
                className={`relative z-10 px-4 py-2 flex items-center gap-2 rounded-lg font-medium transition-all duration-300 text-sm flex-1 ${
                  activeView === 'preview' ? 'text-white' : 'text-gray-600 hover:text-gray-800'
                }`}
              >
                <Monitor size={14} />
                Preview
              </button>
              <button
                onClick={() => handleViewChange('files')}
                className={`relative z-10 px-4 py-2 flex items-center gap-2 rounded-lg font-medium transition-all duration-300 text-sm flex-1 ${
                  activeView === 'files' ? 'text-white' : 'text-gray-600 hover:text-gray-800'
                }`}
              >
                <FileText size={14} />
                Code
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-1 h-0">
        {/* Left panel - Chat (1/5 of screen) */}
        <div className="w-1/5 min-w-[300px] h-full overflow-hidden">
          <Chat projectId={projectId} onFileUpdate={handleFileUpdate} />
        </div>
        
        {/* Divider */}
        <div className="w-1 bg-orange-200/30 cursor-col-resize hover:bg-orange-400/50 transition-colors backdrop-blur-sm" />
        
        {/* Right panel - Content based on active view */}
        <div className="flex-1 bg-white/40 backdrop-blur-sm relative border-l border-orange-100/20">
          {/* Preview container - always rendered but hidden when not active */}
          <div 
            id="preview-container" 
            className={`absolute inset-0 flex flex-col ${activeView === 'preview' ? 'block' : 'hidden'}`}
          >
            {devServerUrl ? (
              <>
                {/* Browser-style URL bar */}
                <div className="bg-white/90 backdrop-blur-lg border-b border-orange-200/30 p-2 flex items-center gap-2 shadow-sm">
                  <div className="flex items-center gap-1 pl-2">
                    <div className="w-3 h-3 rounded-full bg-red-400"></div>
                    <div className="w-3 h-3 rounded-full bg-yellow-400"></div>
                    <div className="w-3 h-3 rounded-full bg-green-400"></div>
                  </div>
                  <div className="flex-1 mx-3">
                    <div className="bg-orange-50/80 backdrop-blur-sm rounded-lg px-4 py-2 text-sm text-gray-700 font-mono flex items-center border border-orange-200/30 shadow-sm">
                      <span className="text-orange-500 mr-2">🔒</span>
                      {devServerUrl}
                    </div>
                  </div>
                  <button
                    onClick={refreshPreview}
                    className="p-2 hover:bg-orange-100/60 rounded-lg transition-colors text-gray-600 hover:text-orange-700 backdrop-blur-sm"
                    title="Refresh"
                  >
                    <RefreshCw size={14} />
                  </button>
                </div>
                {/* Preview iframe */}
                <div className="flex-1 p-2 bg-gray-800/20">
                  <iframe
                    id="preview-iframe"
                    src={devServerUrl}
                    className="w-full h-full bg-white rounded-xl shadow-2xl border border-gray-700/30"
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                  ></iframe>
                </div>
              </>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-400">
                <div className="text-center">
                  <div className="animate-spin h-8 w-8 mx-auto mb-2 border-2 border-blue-500 border-t-transparent rounded-full"></div>
                  <p>Starting development server...</p>
                </div>
              </div>
            )}
          </div>

          {/* Code editor container - always rendered but hidden when not active */}
          <div className={`absolute inset-0 ${activeView === 'files' ? 'block' : 'hidden'}`}>
            <CodeEditor 
              projectId={projectId}
              files={files}
              onFileUpdate={handleFileUpdate}
            />
          </div>
        </div>
      </div>
    </div>
  );
}