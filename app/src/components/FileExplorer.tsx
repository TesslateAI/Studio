import React, { useState, useEffect } from 'react';
import { File, Folder, ChevronRight, ChevronDown, FileText } from 'lucide-react';

interface FileNode {
  name: string;
  path: string;
  content?: string;
  isDirectory: boolean;
  children?: FileNode[];
}

interface FileExplorerProps {
  projectId: number;
  files: any[];
  onFileUpdate: (filePath: string, content: string) => void;
  streamingFiles: Set<string>;
}

export default function FileExplorer({ projectId, files, onFileUpdate, streamingFiles }: FileExplorerProps) {
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(['']));

  useEffect(() => {
    // Build file tree structure
    const tree: FileNode[] = [];
    const pathMap = new Map<string, FileNode>();

    // Sort files by path to ensure proper tree building
    const sortedFiles = [...files].sort((a, b) => a.file_path.localeCompare(b.file_path));

    sortedFiles.forEach(file => {
      const parts = file.file_path.split('/').filter(Boolean);
      let currentPath = '';

      parts.forEach((part: string, index: number) => {
        const fullPath = currentPath ? `${currentPath}/${part}` : part;
        const isFile = index === parts.length - 1;
        
        if (!pathMap.has(fullPath)) {
          const node: FileNode = {
            name: part,
            path: fullPath,
            isDirectory: !isFile,
            children: !isFile ? [] : undefined,
            content: isFile ? file.content : undefined
          };
          
          pathMap.set(fullPath, node);
          
          if (currentPath === '') {
            tree.push(node);
          } else {
            const parent = pathMap.get(currentPath);
            if (parent && parent.children) {
              parent.children.push(node);
            }
          }
        }
        
        currentPath = fullPath;
      });
    });

    setFileTree(tree);
  }, [files]);

  const toggleDirectory = (path: string) => {
    setExpandedDirs(prev => {
      const newSet = new Set(prev);
      if (newSet.has(path)) {
        newSet.delete(path);
      } else {
        newSet.add(path);
      }
      return newSet;
    });
  };

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    return nodes.map(node => (
      <div key={node.path} className="select-none">
        <div
          className={`flex items-center py-2 px-3 cursor-pointer rounded-md mx-1 mb-1 transition-all duration-150 ${
            selectedFile === node.path 
              ? 'bg-blue-600/30 text-blue-200 shadow-sm border border-blue-500/30' 
              : streamingFiles.has(node.path) 
                ? 'bg-blue-600/10 hover:bg-blue-600/20 border border-blue-500/20' 
                : 'hover:bg-gray-700/50'
          }`}
          style={{ paddingLeft: `${depth * 16 + 12}px` }}
          onClick={() => {
            if (node.isDirectory) {
              toggleDirectory(node.path);
            } else {
              setSelectedFile(node.path);
            }
          }}
        >
          {node.isDirectory ? (
            <>
              {expandedDirs.has(node.path) ? (
                <ChevronDown size={14} className="mr-2 text-gray-400" />
              ) : (
                <ChevronRight size={14} className="mr-2 text-gray-400" />
              )}
              <Folder size={14} className="mr-2 text-yellow-400" />
            </>
          ) : (
            <>
              <div className="w-4 mr-2"></div>
              <File size={14} className="mr-2 text-gray-400" />
            </>
          )}
          <span className={`text-sm flex-1 ${
            streamingFiles.has(node.path) 
              ? 'text-blue-300 font-medium' 
              : selectedFile === node.path 
                ? 'text-blue-200 font-medium'
                : 'text-gray-300'
          }`}>
            {node.name}
          </span>
          {streamingFiles.has(node.path) && (
            <div className="flex items-center ml-2">
              <div className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></div>
            </div>
          )}
        </div>
        
        {node.isDirectory && expandedDirs.has(node.path) && node.children && (
          renderFileTree(node.children, depth + 1)
        )}
      </div>
    ));
  };

  const selectedFileContent = files.find(f => f.file_path === selectedFile);

  return (
    <div className="h-full flex bg-gray-900">
      {/* File tree */}
      <div className="w-1/3 bg-gray-800 border-r border-gray-600 overflow-y-auto shadow-lg">
        <div className="p-4 border-b border-gray-600 bg-gradient-to-r from-gray-750 to-gray-800">
          <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wide">Project Files</h3>
        </div>
        <div className="p-3">
          {fileTree.length > 0 ? renderFileTree(fileTree) : (
            <div className="text-gray-400 text-sm p-4 text-center">
              <File size={24} className="mx-auto mb-2 opacity-50" />
              <p>No files created yet</p>
              <p className="text-xs text-gray-500 mt-1">Files will appear here as AI creates them</p>
            </div>
          )}
        </div>
      </div>

      {/* File content */}
      <div className="flex-1 bg-gray-900 overflow-hidden flex flex-col">
        {selectedFile && selectedFileContent ? (
          <>
            <div className="p-4 border-b border-gray-700 bg-gradient-to-r from-gray-800 to-gray-750 shadow-sm">
              <div className="flex items-center gap-2">
                <File size={16} className="text-blue-400" />
                <h4 className="text-sm font-medium text-gray-200">{selectedFile}</h4>
                {streamingFiles.has(selectedFile) && (
                  <span className="px-2 py-1 text-xs bg-blue-600/20 text-blue-300 rounded border border-blue-500/30 animate-pulse">
                    Updating...
                  </span>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed bg-gray-800/50 rounded-lg p-4 border border-gray-700">
                {selectedFileContent.content}
              </pre>
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <FileText size={48} className="mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium mb-2">
                {files.length > 0 ? 'Select a file to view its content' : 'No files created yet'}
              </p>
              <p className="text-sm text-gray-500">
                {files.length > 0 ? 'Choose a file from the tree on the left' : 'Start chatting to create your first file'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}