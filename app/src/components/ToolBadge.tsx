import React from 'react';
import { FileText, FolderOpen, Code, Play, Wrench } from 'lucide-react';

interface ToolBadgeProps {
  tool: string;
}

const getToolIcon = (tool: string) => {
  const toolName = tool.toLowerCase();

  if (toolName.includes('read') || toolName.includes('file')) {
    return <FileText size={12} />;
  } else if (toolName.includes('list') || toolName.includes('directory')) {
    return <FolderOpen size={12} />;
  } else if (toolName.includes('write') || toolName.includes('edit')) {
    return <Code size={12} />;
  } else if (toolName.includes('execute') || toolName.includes('run')) {
    return <Play size={12} />;
  } else {
    return <Wrench size={12} />;
  }
};

const formatToolName = (tool: string) => {
  // Extract tool name from format like "read_file(path.js)"
  const match = tool.match(/^([^(]+)/);
  return match ? match[1].replace(/_/g, ' ') : tool;
};

export default function ToolBadge({ tool }: ToolBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-[rgba(0,217,255,0.1)] text-[var(--accent)] rounded-md text-xs font-medium border border-[rgba(0,217,255,0.2)]">
      {getToolIcon(tool)}
      <span className="opacity-80">{formatToolName(tool)}</span>
    </span>
  );
}
