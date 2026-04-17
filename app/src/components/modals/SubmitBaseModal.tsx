import { useState, useEffect } from 'react';
import { X, Globe, LockSimple } from '@phosphor-icons/react';
import { marketplaceApi } from '../../lib/api';
import toast from 'react-hot-toast';

interface LibraryBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  git_repo_url?: string | null;
  default_branch?: string | null;
  source_type?: 'git' | 'archive';
  category: string;
  icon: string;
  visibility: 'private' | 'public';
  tags?: string[];
  features?: string[];
  tech_stack?: string[];
  downloads: number;
  rating: number;
  created_at: string;
}

interface SubmitBaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  editBase?: LibraryBase | null;
}

const CATEGORIES = [
  { value: 'fullstack', label: 'Fullstack' },
  { value: 'frontend', label: 'Frontend' },
  { value: 'backend', label: 'Backend' },
  { value: 'mobile', label: 'Mobile' },
  { value: 'saas', label: 'SaaS' },
  { value: 'ai', label: 'AI / ML' },
  { value: 'admin', label: 'Admin' },
  { value: 'landing', label: 'Landing Page' },
  { value: 'cli', label: 'CLI' },
  { value: 'data', label: 'Data' },
  { value: 'devops', label: 'DevOps' },
];

export function SubmitBaseModal({ isOpen, onClose, onSuccess, editBase }: SubmitBaseModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [gitRepoUrl, setGitRepoUrl] = useState('');
  const [defaultBranch, setDefaultBranch] = useState('main');
  const [category, setCategory] = useState('fullstack');
  const [visibility, setVisibility] = useState<'private' | 'public'>('private');
  const [icon, setIcon] = useState('\u{1F4E6}');
  const [tags, setTags] = useState('');
  const [techStack, setTechStack] = useState('');
  const [features, setFeatures] = useState('');
  const [longDescription, setLongDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isEditMode = !!editBase;

  useEffect(() => {
    if (editBase) {
      setName(editBase.name);
      setDescription(editBase.description);
      setGitRepoUrl(editBase.git_repo_url || '');
      setDefaultBranch(editBase.default_branch || 'main');
      setCategory(editBase.category);
      setVisibility(editBase.visibility);
      setIcon(editBase.icon);
      setTags((editBase.tags || []).join(', '));
      setTechStack((editBase.tech_stack || []).join(', '));
      setFeatures((editBase.features || []).join(', '));
      setLongDescription(editBase.long_description || '');
    } else {
      setName('');
      setDescription('');
      setGitRepoUrl('');
      setDefaultBranch('main');
      setCategory('fullstack');
      setVisibility('private');
      setIcon('\u{1F4E6}');
      setTags('');
      setTechStack('');
      setFeatures('');
      setLongDescription('');
    }
  }, [editBase, isOpen]);

  if (!isOpen) return null;

  const parseCommaSeparated = (value: string): string[] => {
    return value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  };

  const isArchive = editBase?.source_type === 'archive';

  const handleSubmit = async () => {
    if (!name.trim() || !description.trim()) {
      toast.error('Name and description are required');
      return;
    }
    if (!isArchive && !gitRepoUrl.trim()) {
      toast.error('Git URL is required');
      return;
    }
    if (!isArchive && !gitRepoUrl.startsWith('https://')) {
      toast.error('Git URL must start with https://');
      return;
    }

    setIsSubmitting(true);
    try {
      const data: Record<string, unknown> = {
        name: name.trim(),
        description: description.trim(),
        category,
        visibility,
        icon: icon || '\u{1F4E6}',
        tags: parseCommaSeparated(tags),
        tech_stack: parseCommaSeparated(techStack),
        features: parseCommaSeparated(features),
        long_description: longDescription.trim() || undefined,
      };
      if (!isArchive) {
        data.git_repo_url = gitRepoUrl.trim();
        data.default_branch = defaultBranch.trim() || 'main';
      }

      if (isEditMode && editBase) {
        await marketplaceApi.updateBase(editBase.id, data);
        toast.success('Base updated successfully');
      } else {
        await marketplaceApi.submitBase(data as Parameters<typeof marketplaceApi.submitBase>[0]);
        toast.success('Base submitted successfully!');
      }
      onSuccess();
      onClose();
    } catch (error: unknown) {
      console.error('Failed to submit base:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to submit base');
    } finally {
      setIsSubmitting(false);
    }
  };

  const inputClass =
    'w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-[var(--text)] text-sm focus:outline-none focus:border-[var(--primary)]/50 transition-colors placeholder:text-[var(--text)]/30';
  const labelClass = 'block text-xs font-medium text-[var(--text)]/70 mb-1';

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-[var(--surface)] rounded-2xl w-full max-w-lg shadow-2xl border border-white/10 animate-in fade-in zoom-in-95 duration-200 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h2 className="font-heading text-lg font-bold text-[var(--text)]">
            {isEditMode ? 'Edit Base Template' : 'Submit Base Template'}
          </h2>
          <button
            onClick={onClose}
            className="text-[var(--text)]/40 hover:text-[var(--text)] transition-colors p-1"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Name */}
          <div>
            <label className={labelClass}>Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Awesome Template"
              className={inputClass}
            />
          </div>

          {/* Description */}
          <div>
            <label className={labelClass}>Description *</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of what this template does"
              rows={2}
              className={inputClass + ' resize-none'}
            />
          </div>

          {/* Git Repo URL - hidden for archive templates */}
          {!isArchive && (
            <div>
              <label className={labelClass}>Git Repository URL *</label>
              <input
                type="url"
                value={gitRepoUrl}
                onChange={(e) => setGitRepoUrl(e.target.value)}
                placeholder="https://github.com/user/repo"
                className={inputClass}
              />
            </div>
          )}

          {/* Row: Branch + Category */}
          <div className={isArchive ? '' : 'grid grid-cols-2 gap-3'}>
            {!isArchive && (
              <div>
                <label className={labelClass}>Default Branch</label>
                <input
                  type="text"
                  value={defaultBranch}
                  onChange={(e) => setDefaultBranch(e.target.value)}
                  placeholder="main"
                  className={inputClass}
                />
              </div>
            )}
            <div>
              <label className={labelClass}>Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className={inputClass}
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat.value} value={cat.value}>
                    {cat.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Visibility */}
          <div>
            <label className={labelClass}>Visibility</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setVisibility('public')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all border ${
                  visibility === 'public'
                    ? 'bg-green-500/20 border-green-500/50 text-green-400'
                    : 'bg-white/5 border-white/10 text-[var(--text)]/50 hover:bg-white/10'
                }`}
              >
                <Globe size={16} />
                Public
              </button>
              <button
                type="button"
                onClick={() => setVisibility('private')}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all border ${
                  visibility === 'private'
                    ? 'bg-gray-500/20 border-gray-500/50 text-gray-300'
                    : 'bg-white/5 border-white/10 text-[var(--text)]/50 hover:bg-white/10'
                }`}
              >
                <LockSimple size={16} />
                Private
              </button>
            </div>
            <p className="text-xs text-[var(--text)]/40 mt-1">
              {visibility === 'public'
                ? 'Visible on the marketplace for all users'
                : 'Only you can see and use this template'}
            </p>
          </div>

          {/* Icon */}
          <div>
            <label className={labelClass}>Icon</label>
            <input
              type="text"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="\u{1F4E6}"
              className={inputClass + ' w-20'}
            />
          </div>

          {/* Tags */}
          <div>
            <label className={labelClass}>Tags (comma-separated)</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="react, vite, typescript"
              className={inputClass}
            />
          </div>

          {/* Tech Stack */}
          <div>
            <label className={labelClass}>Tech Stack (comma-separated)</label>
            <input
              type="text"
              value={techStack}
              onChange={(e) => setTechStack(e.target.value)}
              placeholder="React, FastAPI, PostgreSQL"
              className={inputClass}
            />
          </div>

          {/* Features */}
          <div>
            <label className={labelClass}>Features (comma-separated)</label>
            <input
              type="text"
              value={features}
              onChange={(e) => setFeatures(e.target.value)}
              placeholder="Hot reload, API ready, Database setup"
              className={inputClass}
            />
          </div>

          {/* Long Description */}
          <div>
            <label className={labelClass}>Long Description</label>
            <textarea
              value={longDescription}
              onChange={(e) => setLongDescription(e.target.value)}
              placeholder="Detailed description of your template..."
              rows={3}
              className={inputClass + ' resize-none'}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 border-t border-white/10">
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-2.5 rounded-xl font-medium hover:bg-white/10 transition-all disabled:opacity-50 text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={
              isSubmitting ||
              !name.trim() ||
              !description.trim() ||
              (!isArchive && !gitRepoUrl.trim())
            }
            className="flex-1 bg-[var(--primary)] text-white py-2.5 rounded-xl font-medium hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
          >
            {isSubmitting ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
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
                {isEditMode ? 'Updating...' : 'Submitting...'}
              </span>
            ) : isEditMode ? (
              'Update Base'
            ) : (
              'Submit Base'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
