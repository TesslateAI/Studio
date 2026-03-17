import { createElement } from 'react';
import { Terminal, FileText, Code, Search, Edit3, FolderOpen, Plug } from 'lucide-react';

export const getToolIcon = (toolName: string) => {
  const name = toolName.toLowerCase();

  if (name.startsWith('mcp__')) {
    return createElement(Plug, { size: 14, className: 'text-purple-500' });
  }

  if (name.includes('execute') || name.includes('command') || name.includes('bash')) {
    return createElement(Terminal, { size: 14, className: 'text-blue-500' });
  } else if (name.includes('read') || name.includes('get')) {
    return createElement(FileText, { size: 14, className: 'text-green-500' });
  } else if (name.includes('write') || name.includes('edit') || name.includes('update')) {
    return createElement(Edit3, { size: 14, className: 'text-orange-500' });
  } else if (name.includes('list') || name.includes('directory')) {
    return createElement(FolderOpen, { size: 14, className: 'text-purple-500' });
  } else if (name.includes('search') || name.includes('find')) {
    return createElement(Search, { size: 14, className: 'text-yellow-500' });
  } else {
    return createElement(Code, { size: 14, className: 'text-gray-500' });
  }
};

export const getToolLabel = (toolName: string): string => {
  if (toolName.startsWith('mcp__')) {
    const parts = toolName.split('__');
    const serverSlug = parts[1] || '';
    const toolPart = parts.slice(2).join('__');
    const cleanSlug = serverSlug.replace(/^mcp-/, '');
    const serverLabel = cleanSlug.charAt(0).toUpperCase() + cleanSlug.slice(1);
    const toolLabel = toolPart.split(/[-_]/).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    return `[${serverLabel}] ${toolLabel}`;
  }

  // Convert snake_case to Title Case
  return toolName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};
