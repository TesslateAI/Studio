import { useState } from 'react';
import { FilePlus, X } from '@phosphor-icons/react';

interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (projectName: string) => void;
  isLoading?: boolean;
}

export function CreateProjectModal({
  isOpen,
  onClose,
  onConfirm,
  isLoading = false
}: CreateProjectModalProps) {
  const [projectName, setProjectName] = useState('');

  if (!isOpen) return null;

  const handleConfirm = () => {
    if (!isLoading && projectName.trim()) {
      onConfirm(projectName.trim());
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      setProjectName('');
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && projectName.trim() && !isLoading) {
      handleConfirm();
    } else if (e.key === 'Escape' && !isLoading) {
      handleClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-6 sm:p-8 rounded-3xl w-full max-w-md shadow-2xl border border-white/10 animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-4 flex-1">
            <div className="w-12 h-12 bg-[rgba(var(--primary-rgb),0.2)] rounded-xl flex items-center justify-center flex-shrink-0">
              <FilePlus className="w-6 h-6 text-[var(--primary)]" weight="fill" />
            </div>
            <div className="flex-1">
              <h2 className="font-heading text-xl font-bold text-[var(--text)] mb-2">
                Create New Project
              </h2>
              <p className="text-sm text-gray-400 leading-relaxed">
                Enter a name for your new project
              </p>
            </div>
          </div>
          {!isLoading && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-1 ml-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Project Name Input */}
        <div className="mb-6">
          <label
            htmlFor="projectName"
            className="block text-sm font-medium text-[var(--text)] mb-2"
          >
            Project Name
          </label>
          <input
            id="projectName"
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="My Awesome Project"
            disabled={isLoading}
            autoFocus
            maxLength={100}
            className="
              w-full px-4 py-3 bg-[var(--bg)] border border-[var(--border-color)]
              text-[var(--text)] rounded-xl
              focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
              placeholder:text-[var(--text)]/40
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-all
            "
          />
          <p className="mt-2 text-xs text-gray-500">
            {projectName.length}/100 characters
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={isLoading || !projectName.trim()}
            className="flex-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <svg
                  className="w-4 h-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Creating...
              </span>
            ) : (
              'Create Project'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
