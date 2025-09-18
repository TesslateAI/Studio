import React, { useState } from 'react';
import { Monitor, FileText } from 'lucide-react';
import Preview from './Preview';
import CodeEditor from './CodeEditor';

interface TabbedPreviewProps {
  projectId: number;
  userId: number;
  files: any[];
  onFileUpdate: (filePath: string, content: string) => void;
}

export default function TabbedPreview({ projectId, userId, files, onFileUpdate }: TabbedPreviewProps) {
  const [activeTab, setActiveTab] = useState<'preview' | 'files'>(() => {
    // Load saved tab preference from localStorage
    const saved = localStorage.getItem(`active_tab_${projectId}`);
    return (saved as 'preview' | 'files') || 'preview';
  });

  // Save active tab to localStorage whenever it changes
  const handleTabChange = (tab: 'preview' | 'files') => {
    setActiveTab(tab);
    localStorage.setItem(`active_tab_${projectId}`, tab);
  };

  return (
    <div className="h-full flex flex-col bg-gray-900 text-white">
      {/* Tab content */}
      <div className="flex-1 overflow-hidden bg-gray-900">
        {activeTab === 'preview' ? (
          <div id="preview-container" className="h-full"></div>
        ) : (
          <CodeEditor 
            projectId={projectId}
            files={files}
            onFileUpdate={onFileUpdate}
          />
        )}
      </div>

      {/* Initialize Preview component when preview tab is active */}
      {activeTab === 'preview' && (
        <Preview 
          projectId={projectId} 
          userId={userId} 
          activeTab={activeTab}
          setActiveTab={handleTabChange}
        />
      )}
    </div>
  );
}