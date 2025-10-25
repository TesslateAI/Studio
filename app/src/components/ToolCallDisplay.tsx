import React, { useState } from 'react';
import {
  Terminal,
  FileText,
  Code,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Search,
  Edit3,
  FolderOpen
} from 'lucide-react';
import { type ToolCallDetail } from '../types/agent';

interface ToolCallDisplayProps {
  toolCall: ToolCallDetail;
}

const getToolIcon = (toolName: string) => {
  const name = toolName.toLowerCase();

  if (name.includes('execute') || name.includes('command') || name.includes('bash')) {
    return <Terminal size={14} className="text-blue-500" />;
  } else if (name.includes('read') || name.includes('get')) {
    return <FileText size={14} className="text-green-500" />;
  } else if (name.includes('write') || name.includes('edit') || name.includes('update')) {
    return <Edit3 size={14} className="text-orange-500" />;
  } else if (name.includes('list') || name.includes('directory')) {
    return <FolderOpen size={14} className="text-purple-500" />;
  } else if (name.includes('search') || name.includes('find')) {
    return <Search size={14} className="text-yellow-500" />;
  } else {
    return <Code size={14} className="text-gray-500" />;
  }
};

const getToolLabel = (toolName: string): string => {
  // Convert snake_case to Title Case
  return toolName
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

const getToolColor = (toolName: string): string => {
  const name = toolName.toLowerCase();

  if (name.includes('execute') || name.includes('command') || name.includes('bash')) {
    return 'bg-blue-500/10 border-blue-500/20 text-blue-600 dark:text-blue-400';
  } else if (name.includes('read') || name.includes('get')) {
    return 'bg-green-500/10 border-green-500/20 text-green-600 dark:text-green-400';
  } else if (name.includes('write') || name.includes('edit') || name.includes('update')) {
    return 'bg-orange-500/10 border-orange-500/20 text-orange-600 dark:text-orange-400';
  } else if (name.includes('list') || name.includes('directory')) {
    return 'bg-purple-500/10 border-purple-500/20 text-purple-600 dark:text-purple-400';
  } else if (name.includes('search') || name.includes('find')) {
    return 'bg-yellow-500/10 border-yellow-500/20 text-yellow-600 dark:text-yellow-400';
  } else {
    return 'bg-gray-500/10 border-gray-500/20 text-gray-600 dark:text-gray-400';
  }
};

const formatParameterValue = (key: string, value: any): string => {
  if (typeof value === 'string') {
    return value;
  } else if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
};

const shouldTruncateOutput = (output: string): boolean => {
  return output.length > 500 || output.split('\n').length > 15;
};

export default function ToolCallDisplay({ toolCall }: ToolCallDisplayProps) {
  const [showFullOutput, setShowFullOutput] = useState(false);

  const { name, parameters, result } = toolCall;
  const hasResult = result !== undefined && result !== null;
  const success = result?.success ?? false;

  // Extract the main parameter to display (command, file_path, etc.)
  const mainParam = parameters.command || parameters.file_path || parameters.path || parameters.query || '';

  // Get primary output and additional details
  let output = '';
  let additionalOutput = '';
  let suggestion = '';
  let diffPreview = '';
  let technicalDetails: any = null;

  if (hasResult && result.result) {
    if (typeof result.result === 'object') {
      // PRIORITY 1: Show the message field (user-friendly summary)
      if (result.result.message) {
        output = result.result.message;
      }

      // PRIORITY 2: Show diff preview if available (for patch/edit operations)
      if (result.result.diff) {
        diffPreview = result.result.diff;
      }

      // PRIORITY 3: Show suggestion if available (for errors)
      if (result.result.suggestion) {
        suggestion = result.result.suggestion;
      }

      // PRIORITY 4: Show relevant data fields (stdout, content, output, preview, etc.)
      if (result.result.stdout) {
        additionalOutput = result.result.stdout;
      } else if (result.result.stderr) {
        additionalOutput = result.result.stderr;
      } else if (result.result.output) {
        additionalOutput = result.result.output;
      } else if (result.result.content !== undefined) {
        additionalOutput = result.result.content;
      } else if (result.result.preview) {
        additionalOutput = result.result.preview;
      } else if (result.result.files) {
        // Directory listing - handle both string arrays and object arrays
        if (Array.isArray(result.result.files)) {
          additionalOutput = result.result.files.map((file: any) => {
            if (typeof file === 'object' && file !== null) {
              const name = file.name || file.file_path || 'unknown';
              const type = file.type ? `[${file.type}]` : '';
              const size = file.size ? ` (${file.size} bytes)` : '';
              return `${type} ${name}${size}`.trim();
            }
            return String(file);
          }).join('\n');
        } else {
          additionalOutput = String(result.result.files);
        }
      }

      // PRIORITY 4: Collect technical details if available
      if (result.result.details) {
        technicalDetails = result.result.details;
      }

      // Fallback: If no message, show generic JSON (shouldn't happen with new format)
      if (!output && !additionalOutput) {
        output = JSON.stringify(result.result, null, 2);
      }
    } else {
      output = String(result.result);
    }
  } else if (hasResult && result.error) {
    output = result.error;
  }

  // Remove TASK_COMPLETE markers from output
  output = output.replace(/TASK_COMPLETE[^\n]*/gi, '').trim();
  additionalOutput = additionalOutput.replace(/TASK_COMPLETE[^\n]*/gi, '').trim();

  const shouldTruncate = shouldTruncateOutput(additionalOutput);
  const displayAdditionalOutput = shouldTruncate && !showFullOutput
    ? additionalOutput.slice(0, 500) + '...'
    : additionalOutput;

  const outputLines = displayAdditionalOutput.split('\n').length;
  const totalLines = additionalOutput.split('\n').length;

  return (
    <div className={`tool-call-display rounded-lg border ${getToolColor(name)} overflow-hidden`}>
      {/* Tool Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[var(--text)]/5">
        {getToolIcon(name)}
        <span className="text-xs font-semibold flex-1">{getToolLabel(name)}</span>
        {hasResult && (
          success ? (
            <CheckCircle size={14} className="text-green-500" />
          ) : (
            <XCircle size={14} className="text-red-500" />
          )
        )}
      </div>

      {/* Main Parameter */}
      {mainParam && (
        <div className="px-3 py-2 border-b border-current/10">
          <code className="text-xs font-mono break-all">{mainParam}</code>
        </div>
      )}

      {/* Additional Parameters */}
      {Object.keys(parameters).length > 1 && (
        <details className="group border-b border-current/10">
          <summary className="px-3 py-2 text-xs font-medium cursor-pointer hover:bg-[var(--text)]/5 flex items-center gap-2">
            <ChevronDown size={12} className="group-open:hidden" />
            <ChevronUp size={12} className="hidden group-open:block" />
            Parameters ({Object.keys(parameters).length})
          </summary>
          <div className="px-3 py-2 bg-[var(--text)]/5 space-y-1">
            {Object.entries(parameters).map(([key, value]) => (
              <div key={key} className="text-xs">
                <span className="font-medium opacity-70">{key}:</span>{' '}
                <span className="font-mono opacity-90">{formatParameterValue(key, value)}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Primary Message */}
      {output && (
        <div className="border-t border-current/10">
          <div className="px-3 py-2 bg-[var(--text)]/5">
            <div className={`text-sm ${success ? 'opacity-90' : 'text-red-600 dark:text-red-400 font-medium'}`}>
              {output}
            </div>
          </div>
        </div>
      )}

      {/* Diff Preview (for patch/edit operations) */}
      {diffPreview && (
        <div className="border-t border-current/10">
          <div className="px-3 py-2 bg-[var(--text)]/5">
            <div className="text-xs font-medium opacity-70 mb-1">Changes</div>
            <pre className="text-xs font-mono overflow-x-auto bg-gray-900 text-gray-100 dark:bg-gray-950 p-2 rounded">
              {diffPreview.split('\n').map((line, i) => {
                let lineClass = 'opacity-60'; // Context lines
                if (line.startsWith('+')) {
                  lineClass = 'text-green-400 bg-green-500/10';
                } else if (line.startsWith('-')) {
                  lineClass = 'text-red-400 bg-red-500/10';
                } else if (line.startsWith('@@')) {
                  lineClass = 'text-blue-400 opacity-70';
                }
                return (
                  <div key={i} className={lineClass}>
                    {line || '\u00A0'}
                  </div>
                );
              })}
            </pre>
          </div>
        </div>
      )}

      {/* Suggestion (for errors) */}
      {suggestion && !success && (
        <div className="border-t border-current/10">
          <div className="px-3 py-2 bg-yellow-500/10">
            <div className="text-xs font-medium text-yellow-700 dark:text-yellow-400 mb-1">
              💡 Suggestion
            </div>
            <div className="text-xs text-yellow-800 dark:text-yellow-300">
              {suggestion}
            </div>
          </div>
        </div>
      )}

      {/* Additional Output (stdout, content, preview, etc.) */}
      {additionalOutput && (
        <div className="border-t border-current/10">
          <div className="px-3 py-2 bg-[var(--text)]/5">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium opacity-70">
                {success ? 'Output' : 'Error Details'}
              </span>
              {shouldTruncate && (
                <button
                  onClick={() => setShowFullOutput(!showFullOutput)}
                  className="text-xs font-medium hover:underline flex items-center gap-1"
                >
                  {showFullOutput ? (
                    <>
                      <ChevronUp size={12} />
                      Show less
                    </>
                  ) : (
                    <>
                      <ChevronDown size={12} />
                      Show all ({totalLines} lines)
                    </>
                  )}
                </button>
              )}
            </div>
            <pre className={`text-xs font-mono overflow-x-auto ${success ? 'opacity-80' : 'text-red-600 dark:text-red-400'} ${shouldTruncate && !showFullOutput ? 'max-h-48' : 'max-h-96'} overflow-y-auto`}>
              {displayAdditionalOutput}
            </pre>
            {shouldTruncate && !showFullOutput && (
              <div className="text-xs opacity-50 mt-1">
                Showing {outputLines} of {totalLines} lines
              </div>
            )}
          </div>
        </div>
      )}

      {/* Technical Details (collapsible) */}
      {technicalDetails && Object.keys(technicalDetails).length > 0 && (
        <details className="group border-t border-current/10">
          <summary className="px-3 py-2 text-xs font-medium cursor-pointer hover:bg-[var(--text)]/5 flex items-center gap-2">
            <ChevronDown size={12} className="group-open:hidden" />
            <ChevronUp size={12} className="hidden group-open:block" />
            Technical Details
          </summary>
          <div className="px-3 py-2 bg-[var(--text)]/5 space-y-1">
            {Object.entries(technicalDetails).map(([key, value]) => (
              <div key={key} className="text-xs">
                <span className="font-medium opacity-70">{key}:</span>{' '}
                <span className="font-mono opacity-90">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
