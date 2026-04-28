import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Play, Terminal } from '@phosphor-icons/react';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { chatApi } from '../../lib/api';

interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  category: string;
}

interface ExecutionResult {
  success: boolean;
  tool: string;
  result?: unknown;
  error?: string;
}

interface ToolDebugModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number;
}

function buildParameterSkeleton(parameters: Record<string, unknown>): Record<string, unknown> {
  const properties = (parameters?.properties ?? {}) as Record<
    string,
    { type?: string; default?: unknown }
  >;
  const skeleton: Record<string, unknown> = {};

  for (const [key, schema] of Object.entries(properties)) {
    if (schema.default !== undefined) {
      skeleton[key] = schema.default;
      continue;
    }
    switch (schema.type) {
      case 'string':
        skeleton[key] = '';
        break;
      case 'number':
      case 'integer':
        skeleton[key] = 0;
        break;
      case 'boolean':
        skeleton[key] = false;
        break;
      case 'array':
        skeleton[key] = [];
        break;
      case 'object':
        skeleton[key] = {};
        break;
      default:
        skeleton[key] = null;
    }
  }

  return skeleton;
}

export function ToolDebugModal({ isOpen, onClose, projectId }: ToolDebugModalProps) {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [selectedTool, setSelectedTool] = useState<ToolInfo | null>(null);
  const [params, setParams] = useState('{}');
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTools = useCallback(async () => {
    try {
      setError(null);
      const data = await chatApi.debugListTools();
      setTools(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch tools';
      setError(message);
      toast.error(message);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchTools();
      setSelectedTool(null);
      setParams('{}');
      setResult(null);
      setError(null);
    }
  }, [isOpen, fetchTools]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleToolSelect = (toolName: string) => {
    const tool = tools.find((t) => t.name === toolName) ?? null;
    setSelectedTool(tool);
    setResult(null);
    if (tool) {
      const skeleton = buildParameterSkeleton(tool.parameters);
      setParams(JSON.stringify(skeleton, null, 2));
    } else {
      setParams('{}');
    }
  };

  const handleExecute = async () => {
    if (!selectedTool) return;

    let parsedParams: Record<string, unknown>;
    try {
      parsedParams = JSON.parse(params);
    } catch {
      toast.error('Invalid JSON in parameters');
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const data = await chatApi.debugExecuteTool(projectId, selectedTool.name, parsedParams);
      setResult(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Execution failed';
      setResult({ success: false, tool: selectedTool.name, error: message });
    } finally {
      setLoading(false);
    }
  };

  const categories = [...new Set(tools.map((t) => t.category))];

  return createPortal(
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-[var(--surface)] rounded-[var(--radius-medium)] w-full max-w-4xl max-h-[85vh] flex flex-col border border-[var(--border)] shadow-2xl animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-[var(--primary)]/20 rounded-[var(--radius)] flex items-center justify-center">
              <Terminal className="w-5 h-5 text-[var(--primary)]" weight="bold" />
            </div>
            <div>
              <h2 className="font-heading text-lg font-bold text-[var(--text)]">
                Tool Debug Console
              </h2>
              <p className="text-xs text-[var(--text-muted)]">
                {tools.length} tools available
                {categories.length > 0 && ` across ${categories.length} categories`}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="btn btn-icon btn-sm">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
          {/* Left: Tool selector + params */}
          <div className="flex-1 flex flex-col p-6 border-b lg:border-b-0 lg:border-r border-[var(--border)] overflow-y-auto">
            {error ? <div className="text-red-400 text-sm mb-4">{error}</div> : null}

            {/* Tool Selector */}
            <label className="text-sm font-medium text-[var(--text-muted)] mb-2">Tool</label>
            <select
              value={selectedTool?.name ?? ''}
              onChange={(e) => handleToolSelect(e.target.value)}
              className="w-full px-3 py-2 rounded-[var(--radius)] bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-sm mb-4 focus:outline-none focus:border-[var(--border-hover)]"
            >
              <option value="">Select a tool...</option>
              {categories.map((cat) => (
                <optgroup key={cat} label={cat}>
                  {tools
                    .filter((t) => t.category === cat)
                    .map((t) => (
                      <option key={t.name} value={t.name}>
                        {t.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>

            {/* Tool Description */}
            {selectedTool && (
              <div className="mb-4">
                <p className="text-sm text-[var(--text-muted)] leading-relaxed">
                  {selectedTool.description}
                </p>
                <span className="inline-block mt-1 text-xs px-2 py-0.5 rounded-full bg-[var(--primary)]/10 text-[var(--primary)]">
                  {selectedTool.category}
                </span>
              </div>
            )}

            {/* Parameter Editor */}
            <label className="text-sm font-medium text-[var(--text-muted)] mb-2">
              Parameters (JSON)
            </label>
            <textarea
              value={params}
              onChange={(e) => setParams(e.target.value)}
              spellCheck={false}
              className="flex-1 min-h-[200px] w-full px-3 py-2 rounded-[var(--radius)] bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-sm font-mono resize-none focus:outline-none focus:border-[var(--border-hover)]"
            />

            {/* Execute Button */}
            <button
              onClick={handleExecute}
              disabled={!selectedTool || loading}
              className="btn btn-primary mt-4 flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Executing...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" weight="fill" />
                  Execute
                </>
              )}
            </button>
          </div>

          {/* Right: Result */}
          <div className="flex-1 flex flex-col p-6 overflow-y-auto">
            <label className="text-sm font-medium text-[var(--text-muted)] mb-2">Result</label>

            {!result && !loading && (
              <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-sm">
                Execute a tool to see results
              </div>
            )}

            {loading && (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="w-6 h-6 animate-spin text-[var(--primary)]" />
              </div>
            )}

            {result && !loading && (
              <div className="flex-1 flex flex-col gap-3">
                {/* Status Badge */}
                <div className="flex items-center gap-2">
                  {result.success ? (
                    <span className="inline-flex items-center gap-1.5 text-sm font-medium text-green-400">
                      <CheckCircle2 className="w-4 h-4" />
                      Success
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-sm font-medium text-red-400">
                      <XCircle className="w-4 h-4" />
                      Error
                    </span>
                  )}
                  <span className="text-xs text-[var(--text-muted)]">{result.tool}</span>
                </div>

                {/* Result Data */}
                <pre className="flex-1 min-h-[200px] p-3 rounded-[var(--radius)] bg-[var(--bg)] border border-[var(--border)] text-sm font-mono text-[var(--text)] overflow-auto whitespace-pre-wrap">
                  {result.error ? result.error : JSON.stringify(result.result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
