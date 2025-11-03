import { useState, useEffect } from 'react';
import { GitBranch, Sparkle, RefreshCw, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { diagramApi, projectsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import mermaid from 'mermaid';
import { useTheme } from '../../theme/ThemeContext';

interface ArchitecturePanelProps {
  projectSlug: string;
}

export function ArchitecturePanel({ projectSlug }: ArchitecturePanelProps) {
  const { theme } = useTheme();
  const [diagram, setDiagram] = useState<string>('');
  const [diagramType, setDiagramType] = useState<'mermaid' | 'c4_plantuml'>('mermaid');
  const [loading, setLoading] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [modelUsed, setModelUsed] = useState<string>('');
  const [diagramSvg, setDiagramSvg] = useState<string>('');
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    // Initialize Mermaid with theme-aware colors
    const isDark = theme === 'dark';
    mermaid.initialize({
      startOnLoad: false,
      theme: isDark ? 'dark' : 'default',
      flowchart: {
        useMaxWidth: false,
        htmlLabels: true,
        curve: 'basis',
        padding: 40,
        nodeSpacing: 100,
        rankSpacing: 100,
      },
      themeVariables: isDark ? {
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
        textColor: '#e2e2e2',
        fontSize: '24px',
        fontFamily: 'DM Sans, sans-serif',
      } : {
        primaryColor: '#f97316',
        primaryTextColor: '#1a1a1a',
        primaryBorderColor: '#fb923c',
        lineColor: '#fb923c',
        secondaryColor: '#7c3aed',
        tertiaryColor: '#06b6d4',
        background: '#ffffff',
        mainBkg: '#f8f9fa',
        secondBkg: '#ffffff',
        border1: '#e5e7eb',
        border2: '#d1d5db',
        textColor: '#1a1a1a',
        fontSize: '24px',
        fontFamily: 'DM Sans, sans-serif',
      },
    });

    // Re-render diagram when theme or diagram changes (but not during initial load)
    if (diagram && !loadingInitial) {
      renderDiagram();
    }
  }, [theme, diagram, diagramType, loadingInitial]);

  useEffect(() => {
    // Load saved diagram on mount
    loadSavedDiagram();
  }, [projectSlug]);

  const loadSavedDiagram = async () => {
    try {
      const data = await projectsApi.getSettings(projectSlug);
      if (data.architecture_diagram) {
        setDiagram(data.architecture_diagram);
      }
      // Load diagram type (defaults to mermaid for backwards compatibility)
      if (data.diagram_type) {
        setDiagramType(data.diagram_type);
      }
    } catch (error) {
      console.error('Failed to load saved diagram:', error);
    } finally {
      setLoadingInitial(false);
    }
  };

  const sanitizeDiagram = (diagramCode: string): string => {
    // Client-side sanitization for Mermaid syntax
    let sanitized = diagramCode;

    // Remove double quotes from node labels: ["text"] -> [text]
    sanitized = sanitized.replace(/\["([^"]+)"\]/g, '[$1]');
    sanitized = sanitized.replace(/\("([^"]+)"\)/g, '($1)');
    sanitized = sanitized.replace(/\{"([^"]+)"\}/g, '{$1}');

    // Replace @ symbol which causes parsing issues
    sanitized = sanitized.replace(/@/g, 'at-');

    // Remove stray quotes from node/edge definitions
    const lines = sanitized.split('\n');
    const cleanedLines = lines.map(line => {
      // Skip directive lines
      if (line.trim().startsWith('graph') ||
          line.trim().startsWith('flowchart') ||
          line.trim().startsWith('%%') ||
          line.trim().startsWith('classDef') ||
          line.trim().startsWith('class ') ||
          line.trim().startsWith('style ')) {
        return line;
      }
      // Remove stray quotes from other lines
      return line.replace(/"/g, '');
    });

    return cleanedLines.join('\n');
  };

  const renderDiagram = async () => {
    if (!diagram) {
      setDiagramSvg('');
      return;
    }

    try {
      if (diagramType === 'c4_plantuml') {
        // For PlantUML, use Kroki API to render the diagram
        const krokiUrl = 'https://kroki.io/c4plantuml/svg';

        const response = await fetch(krokiUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'text/plain',
          },
          body: diagram
        });

        if (!response.ok) {
          throw new Error('Failed to render PlantUML diagram via Kroki');
        }

        const svgText = await response.text();
        setDiagramSvg(svgText);
      } else {
        // Mermaid rendering (using local mermaid library for better control)
        const sanitized = sanitizeDiagram(diagram);
        const uniqueId = `mermaid-diagram-${Date.now()}`;
        const { svg } = await mermaid.render(uniqueId, sanitized);
        setDiagramSvg(svg);
      }
    } catch (error) {
      console.error('Failed to render diagram:', error);
      // Clear the broken diagram SVG
      setDiagramSvg('');
      // Only show error once, not on every render
      if (diagram) {
        toast.error('Failed to render diagram. Please regenerate it.', { id: 'diagram-error' });
      }
    }
  };

  const handleGenerateDiagram = async (type?: 'mermaid' | 'c4_plantuml') => {
    setLoading(true);
    const requestedType = type || diagramType;
    try {
      const response = await diagramApi.generateDiagram(projectSlug, requestedType);
      setDiagram(response.diagram);
      setDiagramType(response.diagram_type);
      setModelUsed(response.model_used);
      toast.success(`${requestedType === 'c4_plantuml' ? 'C4 PlantUML' : 'Mermaid'} diagram generated successfully!`);
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
    <div className="h-full flex flex-col">
      <div className="panel-section p-6 flex-1 flex flex-col overflow-hidden">
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
          <div className="flex items-center gap-3">
            {/* Zoom Controls - In header */}
            {diagram && (
              <div className="flex gap-2">
                <button
                  onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}
                  className="p-2 bg-[var(--surface)] border border-[var(--text)]/20 rounded-lg hover:bg-orange-500/10 hover:border-orange-500/50 transition-colors"
                  title="Zoom Out"
                >
                  <ZoomOut size={16} className="text-[var(--text)]" />
                </button>
                <button
                  onClick={() => setZoom(1)}
                  className="p-2 bg-[var(--surface)] border border-[var(--text)]/20 rounded-lg hover:bg-orange-500/10 hover:border-orange-500/50 transition-colors"
                  title="Reset Zoom"
                >
                  <Maximize2 size={16} className="text-[var(--text)]" />
                </button>
                <button
                  onClick={() => setZoom(Math.min(3, zoom + 0.25))}
                  className="p-2 bg-[var(--surface)] border border-[var(--text)]/20 rounded-lg hover:bg-orange-500/10 hover:border-orange-500/50 transition-colors"
                  title="Zoom In"
                >
                  <ZoomIn size={16} className="text-[var(--text)]" />
                </button>
                <div className="px-3 py-2 bg-[var(--surface)] border border-[var(--text)]/20 rounded-lg text-xs text-[var(--text)]">
                  {Math.round(zoom * 100)}%
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => handleGenerateDiagram('mermaid')}
                disabled={loading}
                className={`px-4 py-2 rounded-lg text-white transition-colors flex items-center gap-2 disabled:cursor-not-allowed ${
                  diagramType === 'mermaid'
                    ? 'bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50'
                    : 'bg-[var(--surface)] border border-[var(--text)]/20 text-[var(--text)] hover:bg-orange-500/10 hover:border-orange-500/50'
                }`}
              >
                {loading && diagramType === 'mermaid' ? (
                  <>
                    <RefreshCw size={16} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkle size={16} />
                    Mermaid
                  </>
                )}
              </button>
              <button
                onClick={() => handleGenerateDiagram('c4_plantuml')}
                disabled={loading}
                className={`px-4 py-2 rounded-lg text-white transition-colors flex items-center gap-2 disabled:cursor-not-allowed ${
                  diagramType === 'c4_plantuml'
                    ? 'bg-orange-500 hover:bg-orange-600 disabled:bg-orange-500/50'
                    : 'bg-[var(--surface)] border border-[var(--text)]/20 text-[var(--text)] hover:bg-orange-500/10 hover:border-orange-500/50'
                }`}
              >
                {loading && diagramType === 'c4_plantuml' ? (
                  <>
                    <RefreshCw size={16} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkle size={16} />
                    C4 PlantUML
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Diagram Display */}
        {diagram ? (
          <div className="flex-1 flex flex-col min-h-0 space-y-4">
            {/* Scrollable Diagram Container */}
            <div className="diagram-scroll-container bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg flex-1 overflow-auto p-4">
              <div
                className="mermaid-container"
                style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
                dangerouslySetInnerHTML={{ __html: diagramSvg }}
              />
            </div>

            {modelUsed && (
              <div className="flex items-center justify-between text-xs text-[var(--text)]/60">
                <span>Generated with {modelUsed} ({diagramType === 'c4_plantuml' ? 'C4 PlantUML' : 'Mermaid'})</span>
                <button
                  onClick={() => handleGenerateDiagram()}
                  className="flex items-center gap-1 hover:text-orange-400 transition-colors"
                >
                  <RefreshCw size={12} />
                  Regenerate
                </button>
              </div>
            )}
          </div>
        ) : loadingInitial ? (
          <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-8 text-center flex-1 flex items-center justify-center">
            <div>
              <RefreshCw size={48} className="mx-auto mb-4 text-[var(--text)]/20 animate-spin" />
              <p className="text-[var(--text)]/60">Loading diagram...</p>
            </div>
          </div>
        ) : (
          <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-8 text-center flex-1 flex items-center justify-center">
            <div>
            <GitBranch size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
            <p className="text-[var(--text)]/60 mb-4">
              No diagram generated yet
            </p>
            <p className="text-xs text-[var(--text)]/40 mb-6">
              Choose a diagram type to create an AI-powered visualization of your project's architecture
            </p>
            <div className="flex gap-3 justify-center">
              <button
                onClick={() => handleGenerateDiagram('mermaid')}
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
                    Generate Mermaid
                  </>
                )}
              </button>
              <button
                onClick={() => handleGenerateDiagram('c4_plantuml')}
                disabled={loading}
                className="px-6 py-3 bg-purple-500 hover:bg-purple-600 disabled:bg-purple-500/50 rounded-lg text-white transition-colors inline-flex items-center gap-2 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <>
                    <RefreshCw size={18} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkle size={18} />
                    Generate C4 PlantUML
                  </>
                )}
              </button>
            </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
