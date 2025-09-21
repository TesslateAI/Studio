import React, { useState, useEffect } from 'react';
import { File, Folder, ChevronRight, ChevronDown, FileText, Code } from 'lucide-react';

interface FileNode {
  name: string;
  path: string;
  content?: string;
  isDirectory: boolean;
  children?: FileNode[];
}

interface CodeEditorProps {
  projectId: number;
  files: any[];
  onFileUpdate: (filePath: string, content: string) => void;
}

export default function CodeEditor({ projectId, files, onFileUpdate }: CodeEditorProps) {
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
      
      parts.forEach((part, index) => {
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

    // Auto-select the first file if none selected
    if (!selectedFile && files.length > 0) {
      setSelectedFile(files[0].file_path);
    }
  }, [files, selectedFile]);


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

  const getFileIcon = (fileName: string) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js':
      case 'jsx':
      case 'ts':
      case 'tsx':
        return <Code size={14} className="text-yellow-400" />;
      case 'html':
        return <File size={14} className="text-orange-400" />;
      case 'css':
        return <File size={14} className="text-blue-400" />;
      case 'json':
        return <File size={14} className="text-green-400" />;
      default:
        return <File size={14} className="text-gray-400" />;
    }
  };

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    return nodes.map(node => (
      <div key={node.path} className="select-none">
        <div
          className={`flex items-center py-2 px-3 cursor-pointer rounded-xl mx-2 mb-1 transition-all duration-200 ${
            selectedFile === node.path 
              ? 'bg-gradient-to-r from-blue-600/30 to-purple-600/20 text-blue-200 shadow-lg border border-blue-500/30' 
              : 'hover:bg-gray-700/50 hover:rounded-xl'
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
              {getFileIcon(node.name)}
              <div className="mr-2"></div>
            </>
          )}
          <span className={`text-sm flex-1 font-medium ${
            selectedFile === node.path 
              ? 'text-blue-200'
              : 'text-gray-300'
          }`}>
            {node.name}
          </span>
        </div>
        
        {node.isDirectory && expandedDirs.has(node.path) && node.children && (
          renderFileTree(node.children, depth + 1)
        )}
      </div>
    ));
  };

  const selectedFileContent = files.find(f => f.file_path === selectedFile);

  return (
    <div className="h-full flex bg-gray-900 rounded-t-3xl overflow-hidden">
      {/* File tree sidebar */}
      <div className="w-80 bg-gray-800/50 backdrop-blur-sm border-r border-gray-600/30 overflow-y-auto rounded-tl-3xl">
        <div className="p-4 border-b border-gray-600/30 bg-gradient-to-r from-gray-750/50 to-gray-800/50 rounded-tl-3xl">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-r from-purple-500 to-pink-600 rounded-lg flex items-center justify-center">
              <FileText size={16} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-200">Project Files</h3>
              <p className="text-xs text-gray-400">
                {files.length} files
              </p>
            </div>
          </div>
        </div>
        
        <div className="p-3">
          {fileTree.length > 0 ? renderFileTree(fileTree) : (
            <div className="text-gray-400 text-sm p-6 text-center rounded-xl bg-gray-800/30">
              <Code size={32} className="mx-auto mb-3 opacity-50" />
              <p className="font-medium mb-1">No files yet</p>
              <p className="text-xs text-gray-500">Files will appear here as AI creates them</p>
            </div>
          )}
        </div>
      </div>

      {/* Code editor area */}
      <div className="flex-1 bg-gray-900/50 backdrop-blur-sm overflow-hidden flex flex-col rounded-tr-3xl">
        {selectedFile && selectedFileContent ? (
          <>
            {/* File header */}
            <div className="p-4 border-b border-gray-700/50 bg-gradient-to-r from-gray-800/50 to-gray-750/50 shadow-sm rounded-tr-3xl">
              <div className="flex items-center gap-3">
                {getFileIcon(selectedFile.split('/').pop() || '')}
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-gray-200">{selectedFile}</h4>
                  <p className="text-xs text-gray-400">
                    {selectedFileContent.content.split('\n').length} lines • {selectedFileContent.content.length} chars
                  </p>
                </div>
              </div>
            </div>
            
            {/* Code content */}
            <div className="flex-1 overflow-y-auto p-4 bg-gray-900/30">
              <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl border border-gray-700/30 shadow-lg overflow-hidden">
                <div className="p-4 bg-gradient-to-r from-gray-800/80 to-gray-700/60 border-b border-gray-700/30">
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    <div className="w-3 h-3 bg-red-500 rounded-full"></div>
                    <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
                    <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                    <span className="ml-2">{selectedFile}</span>
                  </div>
                </div>
                <div className="p-6 max-h-[600px] overflow-y-auto">
                  <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                    <code>{selectedFileContent.content}</code>
                  </pre>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400 rounded-tr-3xl">
            <div className="text-center p-8">
              <div className="w-16 h-16 bg-gradient-to-r from-blue-500/20 to-purple-600/20 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Code size={32} className="opacity-60" />
              </div>
              <h3 className="text-lg font-semibold mb-2 text-gray-300">
                {files.length > 0 ? 'Select a file to view' : 'No files created yet'}
              </h3>
              <p className="text-sm text-gray-500 max-w-sm">
                {files.length > 0 
                  ? 'Choose a file from the sidebar to view its code' 
                  : 'Start chatting with the AI to create your first file'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}