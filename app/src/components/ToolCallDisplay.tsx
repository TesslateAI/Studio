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

  // Get output from result
  let output = '';
  if (hasResult && result.result) {
    if (typeof result.result === 'object') {
      // Handle different result types
      if (result.result.stdout || result.result.stderr) {
        // Command execution result
        output = result.result.stdout || result.result.stderr || '';
      } else if (result.result.content !== undefined) {
        // File read result
        output = result.result.content;
      } else if (result.result.files) {
        // Directory listing
        output = result.result.files.join('\n');
      } else {
        // Generic object result
        output = JSON.stringify(result.result, null, 2);
      }
    } else {
      output = String(result.result);
    }
  } else if (hasResult && result.error) {
    output = result.error;
  }

  const shouldTruncate = shouldTruncateOutput(output);
  const displayOutput = shouldTruncate && !showFullOutput
    ? output.slice(0, 500) + '...'
    : output;

  const outputLines = displayOutput.split('\n').length;
  const totalLines = output.split('\n').length;

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

      {/* Output */}
      {output && (
        <div className="border-t border-current/10">
          <div className="px-3 py-2 bg-[var(--text)]/5">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium opacity-70">
                {success ? 'Output' : 'Error'}
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
              {displayOutput}
            </pre>
            {shouldTruncate && !showFullOutput && (
              <div className="text-xs opacity-50 mt-1">
                Showing {outputLines} of {totalLines} lines
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
