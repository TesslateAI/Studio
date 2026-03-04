import { createElement } from 'react';
import { Terminal, FileText, Code, Search, Edit3, FolderOpen } from 'lucide-react';

export const getToolIcon = (toolName: string) => {
  const name = toolName.toLowerCase();

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
  // Convert snake_case to Title Case
  return toolName
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};
