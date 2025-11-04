import React, { useState, useEffect, useRef } from 'react';
import { File, Folder, ChevronRight, ChevronDown, FileText, Code, PanelLeftClose, PanelLeft } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { useTheme } from '../theme/ThemeContext';

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
  const { theme } = useTheme();
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(['']));
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const editorRef = useRef<any>(null);

  const getLanguage = (fileName: string): string => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js': return 'javascript';
      case 'jsx': return 'javascript';
      case 'ts': return 'typescript';
      case 'tsx': return 'typescript';
      case 'html': return 'html';
      case 'css': return 'css';
      case 'json': return 'json';
      case 'md': return 'markdown';
      case 'py': return 'python';
      case 'yml':
      case 'yaml': return 'yaml';
      default: return 'plaintext';
    }
  };

  const handleEditorDidMount = (editor: any) => {
    editorRef.current = editor;
  };

  const handleEditorChange = (value: string | undefined) => {
    if (selectedFile && value !== undefined) {
      onFileUpdate(selectedFile, value);
    }
  };

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

    // Auto-select the first file if none selected
    if (!selectedFile && files.length > 0) {
      setSelectedFile(files[0].file_path);
    }
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
          className={`flex items-center py-2 px-3 cursor-pointer rounded-lg mb-0.5 transition-all duration-150 ${
            selectedFile === node.path
              ? 'bg-orange-500/20 text-orange-300 border-l-2 border-orange-500'
              : 'hover:bg-[var(--surface)]/70 text-[var(--text)]/80 hover:text-[var(--text)]'
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
                <ChevronDown size={14} className="mr-2 text-[var(--text)]/50" />
              ) : (
                <ChevronRight size={14} className="mr-2 text-[var(--text)]/50" />
              )}
              <Folder size={14} className="mr-2 text-blue-400" />
            </>
          ) : (
            <>
              <div className="w-4 mr-2"></div>
              {getFileIcon(node.name)}
              <div className="mr-2"></div>
            </>
          )}
          <span className={`text-sm flex-1 font-medium truncate ${
            selectedFile === node.path
              ? 'text-orange-200'
              : ''
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
    <div className="h-full flex bg-[var(--surface)] overflow-hidden">
      {/* File tree sidebar */}
      <div className={`bg-[var(--background)] border-r border-[var(--border-color)] overflow-y-auto flex flex-col transition-all duration-300 ${
        isSidebarCollapsed ? 'w-0 border-0' : 'w-72'
      }`}>
        <div className="px-4 h-12 border-b border-[var(--border-color)] bg-[var(--surface)]/50 backdrop-blur-sm flex items-center">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-orange-500 to-pink-600 rounded-lg flex items-center justify-center shadow-lg">
              <FileText size={16} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Explorer</h3>
              <p className="text-xs text-[var(--text)]/60">
                {files.length} {files.length === 1 ? 'file' : 'files'}
              </p>
            </div>
          </div>
        </div>
        
        <div className="flex-1 p-2 overflow-y-auto" key={files.length}>
          {fileTree.length > 0 ? renderFileTree(fileTree) : (
            <div className="text-[var(--text)]/60 text-sm p-6 text-center rounded-xl bg-[var(--surface)]/50">
              <Code size={32} className="mx-auto mb-3 opacity-50" />
              <p className="font-medium mb-1 text-[var(--text)]">No files yet</p>
              <p className="text-xs text-[var(--text)]/40">Files will appear here as you build</p>
            </div>
          )}
        </div>
      </div>

      {/* Code editor area */}
      <div className="flex-1 bg-[var(--background)] overflow-hidden flex flex-col">
        {selectedFile && selectedFileContent ? (
          <>
            {/* File header */}
            <div className="px-4 h-12 border-b border-[var(--border-color)] bg-[var(--surface)]/50 backdrop-blur-sm flex items-center">
              <div className="flex items-center gap-3">
                {/* Toggle sidebar button */}
                <button
                  onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                  className="p-1.5 hover:bg-[var(--text)]/10 active:bg-[var(--text)]/20 rounded transition-colors"
                  title={isSidebarCollapsed ? "Show file explorer" : "Hide file explorer"}
                >
                  {isSidebarCollapsed ? (
                    <PanelLeft size={16} className="text-[var(--text)]/60" />
                  ) : (
                    <PanelLeftClose size={16} className="text-[var(--text)]/60" />
                  )}
                </button>
                {getFileIcon(selectedFile.split('/').pop() || '')}
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-[var(--text)]">{selectedFile}</h4>
                  <p className="text-xs text-[var(--text)]/50">
                    {selectedFileContent.content.split('\n').length} lines • {selectedFileContent.content.length} characters
                  </p>
                </div>
              </div>
            </div>
            
            {/* Monaco Editor */}
            <div className="flex-1 overflow-hidden">
              <Editor
                key={selectedFile}
                height="100%"
                language={getLanguage(selectedFile)}
                value={selectedFileContent.content}
                onChange={handleEditorChange}
                onMount={handleEditorDidMount}
                theme={theme === 'dark' ? 'vs-dark' : 'vs'}
                options={{
                  fontSize: 14,
                  fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                  lineNumbers: 'on',
                  minimap: { enabled: true },
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  tabSize: 2,
                  wordWrap: 'on',
                  padding: { top: 16, bottom: 16 },
                  smoothScrolling: true,
                  cursorBlinking: 'smooth',
                  cursorSmoothCaretAnimation: 'on',
                  renderLineHighlight: 'all',
                  bracketPairColorization: { enabled: true },
                  guides: {
                    bracketPairs: true,
                    indentation: true,
                  },
                  suggestOnTriggerCharacters: true,
                  quickSuggestions: true,
                  formatOnPaste: true,
                  formatOnType: true,
                }}
              />
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-[var(--text)]/60">
            <div className="text-center p-8">
              <div className="w-20 h-20 bg-gradient-to-br from-orange-500/20 to-pink-600/20 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg">
                <Code size={40} className="opacity-60 text-orange-500" />
              </div>
              <h3 className="text-lg font-semibold mb-2 text-[var(--text)]">
                {files.length > 0 ? 'Select a file to edit' : 'No files yet'}
              </h3>
              <p className="text-sm text-[var(--text)]/50 max-w-sm">
                {files.length > 0
                  ? 'Choose a file from the explorer to start editing'
                  : 'Chat with your AI agent to generate code'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}