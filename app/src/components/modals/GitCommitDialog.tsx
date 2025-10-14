import { useState } from 'react';
import { GitCommit, X, Check } from '@phosphor-icons/react';
import { gitApi } from '../../lib/git-api';
import type { GitFileChange } from '../../types/git';
import toast from 'react-hot-toast';

interface GitCommitDialogProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number;
  changes: GitFileChange[];
  onSuccess: () => void;
}

const COMMIT_PREFIXES = [
  { value: 'feat', label: 'feat', description: 'New feature', color: 'text-green-400' },
  { value: 'fix', label: 'fix', description: 'Bug fix', color: 'text-red-400' },
  { value: 'docs', label: 'docs', description: 'Documentation', color: 'text-blue-400' },
  { value: 'style', label: 'style', description: 'Formatting', color: 'text-purple-400' },
  { value: 'refactor', label: 'refactor', description: 'Code refactoring', color: 'text-yellow-400' },
  { value: 'test', label: 'test', description: 'Tests', color: 'text-cyan-400' },
  { value: 'chore', label: 'chore', description: 'Maintenance', color: 'text-gray-400' },
];

export function GitCommitDialog({ isOpen, onClose, projectId, changes, onSuccess }: GitCommitDialogProps) {
  const [message, setMessage] = useState('');
  const [selectedPrefix, setSelectedPrefix] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<string[]>(changes.map(c => c.file_path));
  const [isCommitting, setIsCommitting] = useState(false);

  if (!isOpen) return null;

  const handleCommit = async () => {
    if (!message.trim()) {
      toast.error('Please enter a commit message');
      return;
    }

    if (selectedFiles.length === 0) {
      toast.error('Please select at least one file to commit');
      return;
    }

    const finalMessage = selectedPrefix ? `${selectedPrefix}: ${message}` : message;

    setIsCommitting(true);
    const loadingToast = toast.loading('Creating commit...');

    try {
      const result = await gitApi.commit(projectId, finalMessage, selectedFiles);
      toast.success(`Committed ${result.sha.substring(0, 7)}`, { id: loadingToast });
      setMessage('');
      setSelectedPrefix(null);
      onSuccess();
      onClose();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to create commit';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsCommitting(false);
    }
  };

  const handleClose = () => {
    if (!isCommitting) {
      setMessage('');
      setSelectedPrefix(null);
      onClose();
    }
  };

  const toggleFile = (filePath: string) => {
    setSelectedFiles(prev =>
      prev.includes(filePath)
        ? prev.filter(f => f !== filePath)
        : [...prev, filePath]
    );
  };

  const selectAll = () => {
    setSelectedFiles(changes.map(c => c.file_path));
  };

  const deselectAll = () => {
    setSelectedFiles([]);
  };

  const getFileStatusIcon = (status: string) => {
    switch (status) {
      case 'M': return <span className="text-yellow-400">M</span>;
      case 'A': return <span className="text-green-400">A</span>;
      case 'D': return <span className="text-red-400">D</span>;
      case 'R': return <span className="text-blue-400">R</span>;
      case '??': return <span className="text-gray-400">?</span>;
      default: return <span className="text-gray-400">{status}</span>;
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-green-500/20 rounded-xl flex items-center justify-center">
              <GitCommit className="w-6 h-6 text-green-400" weight="fill" />
            </div>
            <div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)]">Commit Changes</h2>
              <p className="text-sm text-gray-500">{changes.length} file(s) changed</p>
            </div>
          </div>
          {!isCommitting && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto space-y-4">
          {/* Commit Type Selector */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Commit Type (Optional)
            </label>
            <div className="grid grid-cols-4 gap-2">
              {COMMIT_PREFIXES.map((prefix) => (
                <button
                  key={prefix.value}
                  onClick={() => setSelectedPrefix(prev => prev === prefix.value ? null : prefix.value)}
                  disabled={isCommitting}
                  className={`p-2 rounded-lg text-sm font-medium transition-all ${
                    selectedPrefix === prefix.value
                      ? 'bg-white/20 border border-white/30'
                      : 'bg-white/5 border border-white/10 hover:bg-white/10'
                  }`}
                  title={prefix.description}
                >
                  <span className={prefix.color}>{prefix.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Commit Message */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Commit Message
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-green-500 placeholder-gray-500 resize-none"
              rows={3}
              placeholder={selectedPrefix ? `${selectedPrefix}: add your message here` : 'add your message here'}
              disabled={isCommitting}
              autoFocus
            />
            <p className="text-xs text-gray-500 mt-1">
              {message.length}/500 characters
            </p>
          </div>

          {/* File Selection */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-[var(--text)]">
                Files to Commit ({selectedFiles.length}/{changes.length})
              </label>
              <div className="flex gap-2">
                <button
                  onClick={selectAll}
                  disabled={isCommitting}
                  className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                >
                  Select All
                </button>
                <span className="text-gray-600">|</span>
                <button
                  onClick={deselectAll}
                  disabled={isCommitting}
                  className="text-xs text-gray-400 hover:text-gray-300 transition-colors"
                >
                  Deselect All
                </button>
              </div>
            </div>
            <div className="space-y-1 max-h-60 overflow-y-auto bg-white/5 rounded-xl p-3 border border-white/10">
              {changes.map((change) => (
                <button
                  key={change.file_path}
                  onClick={() => toggleFile(change.file_path)}
                  disabled={isCommitting}
                  className={`w-full text-left p-2 rounded-lg transition-all flex items-center gap-3 ${
                    selectedFiles.includes(change.file_path)
                      ? 'bg-white/10 border border-white/20'
                      : 'hover:bg-white/5'
                  }`}
                >
                  <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all ${
                    selectedFiles.includes(change.file_path)
                      ? 'bg-green-500 border-green-500'
                      : 'border-white/30'
                  }`}>
                    {selectedFiles.includes(change.file_path) && (
                      <Check className="w-3 h-3 text-white" weight="bold" />
                    )}
                  </div>
                  <span className="font-mono text-sm font-semibold">
                    {getFileStatusIcon(change.status)}
                  </span>
                  <span className="text-sm text-[var(--text)] truncate">{change.file_path}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-6 mt-6 border-t border-white/10">
          <button
            onClick={handleCommit}
            disabled={isCommitting || !message.trim() || selectedFiles.length === 0}
            className="flex-1 bg-green-500 hover:bg-green-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
          >
            {isCommitting ? 'Committing...' : 'Create Commit'}
          </button>
          <button
            onClick={handleClose}
            disabled={isCommitting}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
