import { useState, useEffect } from 'react';
import { GitBranch, Sparkle, RefreshCw } from 'lucide-react';
import { diagramApi, projectsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import mermaid from 'mermaid';

interface ArchitecturePanelProps {
  projectId: number;
}

export function ArchitecturePanel({ projectId }: ArchitecturePanelProps) {
  const [diagram, setDiagram] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [modelUsed, setModelUsed] = useState<string>('');
  const [diagramSvg, setDiagramSvg] = useState<string>('');

  useEffect(() => {
    // Initialize Mermaid
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        primaryColor: '#f97316',
        primaryTextColor: '#fff',
        primaryBorderColor: '#fb923c',
        lineColor: '#fb923c',
        secondaryColor: '#7c3aed',
        tertiaryColor: '#06b6d4',
        background: '#1a1a1a',
        mainBkg: '#262626',
        secondBkg: '#171717',
        border1: '#404040',
        border2: '#525252',
      },
    });

    // Load saved diagram on mount
    loadSavedDiagram();
  }, [projectId]);

  useEffect(() => {
    // Render diagram when it changes
    if (diagram) {
      renderDiagram();
    }
  }, [diagram]);

  const loadSavedDiagram = async () => {
    try {
      const data = await projectsApi.getSettings(projectId);
      if (data.architecture_diagram) {
        setDiagram(data.architecture_diagram);
      }
    } catch (error) {
      console.error('Failed to load saved diagram:', error);
    } finally {
      setLoadingInitial(false);
    }
  };

  const renderDiagram = async () => {
    try {
      const { svg } = await mermaid.render('mermaid-diagram', diagram);
      setDiagramSvg(svg);
    } catch (error) {
      console.error('Failed to render Mermaid diagram:', error);
      toast.error('Failed to render diagram');
    }
  };

  const handleGenerateDiagram = async () => {
    setLoading(true);
    try {
      const response = await diagramApi.generateDiagram(projectId);
      setDiagram(response.diagram);
      setModelUsed(response.model_used);
      toast.success('Architecture diagram generated successfully!');
    } catch (error: any) {
      console.error('Failed to generate diagram:', error);
      const errorMsg = error.response?.data?.detail || 'Failed to generate diagram';
      toast.error(errorMsg);

      // Show helpful message if no model selected
      if (errorMsg.includes('No diagram generation model selected')) {
        toast.error('Please select a model in Library → Model Management', { duration: 5000 });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="panel-section p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-500/20 rounded-lg">
              <GitBranch size={20} className="text-orange-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[var(--text)]">Architecture Diagram</h2>
              <p className="text-xs text-[var(--text)]/60">
                AI-generated visualization of your project
              </p>
            </div>
          </div>
          <button
            onClick={handleGenerateDiagram}
            disabled={loading}
            className="px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50 rounded-lg text-white transition-colors flex items-center gap-2 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <RefreshCw size={16} className="animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Sparkle size={16} />
                Generate Diagram
              </>
            )}
          </button>
        </div>

        {/* Diagram Display */}
        {diagram ? (
          <div className="space-y-4">
            <div className="bg-white/5 border border-white/10 rounded-lg p-6 overflow-x-auto">
              <div
                className="mermaid-container flex items-center justify-center"
                dangerouslySetInnerHTML={{ __html: diagramSvg }}
              />
            </div>
            {modelUsed && (
              <div className="flex items-center justify-between text-xs text-[var(--text)]/60">
                <span>Generated with {modelUsed}</span>
                <button
                  onClick={handleGenerateDiagram}
                  className="flex items-center gap-1 hover:text-orange-400 transition-colors"
                >
                  <RefreshCw size={12} />
                  Regenerate
                </button>
              </div>
            )}
          </div>
        ) : loadingInitial ? (
          <div className="bg-white/5 border border-white/10 rounded-lg p-8 text-center">
            <RefreshCw size={48} className="mx-auto mb-4 text-[var(--text)]/20 animate-spin" />
            <p className="text-[var(--text)]/60">Loading diagram...</p>
          </div>
        ) : (
          <div className="bg-white/5 border border-white/10 rounded-lg p-8 text-center">
            <GitBranch size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
            <p className="text-[var(--text)]/60 mb-4">
              No diagram generated yet
            </p>
            <p className="text-xs text-[var(--text)]/40 mb-6">
              Click "Generate Diagram" to create an AI-powered visualization of your project's architecture
            </p>
            <button
              onClick={handleGenerateDiagram}
              disabled={loading}
              className="px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50 rounded-lg text-white transition-colors inline-flex items-center gap-2 disabled:cursor-not-allowed"
            >
              {loading ? (
                <>
                  <RefreshCw size={18} className="animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Sparkle size={18} />
                  Generate Diagram
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
