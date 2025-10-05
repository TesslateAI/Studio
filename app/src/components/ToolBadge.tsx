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
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-medium border border-purple-200">
      {getToolIcon(tool)}
      {formatToolName(tool)}
    </span>
  );
}
