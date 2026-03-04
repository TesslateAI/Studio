import React, { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import { LoadingSpinner } from '../PulsingGridSpinner';
import toast from 'react-hot-toast';
import { getAuthHeaders } from '../../lib/api';

// ============================================================================
// Interfaces
// ============================================================================

interface BaseItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  icon: string;
  source_type: string;
  pricing_type: string;
  price: number;
  downloads: number;
  is_featured: boolean;
  is_active: boolean;
  created_at: string;
  created_by_tesslate: boolean;
  created_by_username: string | null;
  can_edit: boolean;
}

interface BaseDetailed extends BaseItem {
  long_description: string | null;
  git_repo_url: string | null;
  default_branch: string;
  preview_image: string | null;
  tech_stack: string[];
  features: string[];
  tags: string[];
  visibility: string;
  rating: number;
  reviews_count: number;
  updated_at: string | null;
}

// ============================================================================
// BaseManagement Component
// ============================================================================

export default function BaseManagement() {
  const [bases, setBases] = useState<BaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedBase, setSelectedBase] = useState<BaseDetailed | null>(null);
  const [filter, setFilter] = useState({
    category: '',
    pricing_type: '',
    is_active: '',
    source_type: '',
  });

  useEffect(() => {
    loadBases();
  }, [filter]);

  const loadBases = async () => {
    try {
      setLoading(true);

      const params = new URLSearchParams();
      if (filter.category) params.append('category', filter.category);
      if (filter.pricing_type) params.append('pricing_type', filter.pricing_type);
      if (filter.is_active) params.append('is_active', filter.is_active);
      if (filter.source_type) params.append('source_type', filter.source_type);

      const response = await fetch(`/api/admin/bases?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load bases');

      const data = await response.json();
      setBases(data.bases || []);
    } catch (error) {
      console.error('Failed to load bases:', error);
      toast.error('Failed to load bases');
    } finally {
      setLoading(false);
    }
  };

  const loadBaseDetails = async (baseId: string) => {
    try {
      const response = await fetch(`/api/admin/bases/${baseId}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load base details');

      const data = await response.json();
      setSelectedBase(data);
      setShowEditModal(true);
    } catch (error) {
      console.error('Failed to load base details:', error);
      toast.error('Failed to load base details');
    }
  };

  const handleDelete = async (base: BaseItem) => {
    if (!base.can_edit) {
      toast.error('Cannot delete this base');
      return;
    }

    if (!confirm(`Are you sure you want to delete "${base.name}"? This cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`/api/admin/bases/${base.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete base');
      }

      toast.success('Base deleted successfully');
      loadBases();
    } catch (error: unknown) {
      console.error('Failed to delete base:', error);
      const err = error as { message?: string };
      toast.error(err.message || 'Failed to delete base');
    }
  };

  const handleToggleFeatured = async (base: BaseItem) => {
    try {
      const response = await fetch(
        `/api/admin/bases/${base.id}/feature?is_featured=${!base.is_featured}`,
        {
          method: 'PATCH',
          headers: getAuthHeaders(),
          credentials: 'include',
        }
      );

      if (!response.ok) throw new Error('Failed to toggle featured');

      toast.success(`Base ${!base.is_featured ? 'featured' : 'unfeatured'}`);
      loadBases();
    } catch (error) {
      console.error('Failed to toggle featured:', error);
      toast.error('Failed to toggle featured status');
    }
  };

  const handleRemoveFromMarketplace = async (base: BaseItem) => {
    if (!confirm(`Remove "${base.name}" from the marketplace?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/admin/bases/${base.id}/remove-from-marketplace`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to remove base');

      toast.success('Base removed from marketplace');
      loadBases();
    } catch (error) {
      console.error('Failed to remove base:', error);
      toast.error('Failed to remove base');
    }
  };

  const handleRestoreToMarketplace = async (base: BaseItem) => {
    if (!confirm(`Restore "${base.name}" to the marketplace?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/admin/bases/${base.id}/restore-to-marketplace`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to restore base');

      toast.success('Base restored to marketplace');
      loadBases();
    } catch (error) {
      console.error('Failed to restore base:', error);
      toast.error('Failed to restore base');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner message="Loading bases..." size={60} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white">Base Management</h2>
        <button
          onClick={() => setShowCreateModal(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center space-x-2"
        >
          <span>+ Create Base</span>
        </button>
      </div>

      {/* Filters */}
      <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <select
            value={filter.category}
            onChange={(e) => setFilter({ ...filter, category: e.target.value })}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Categories</option>
            <option value="fullstack">Fullstack</option>
            <option value="frontend">Frontend</option>
            <option value="backend">Backend</option>
            <option value="mobile">Mobile</option>
            <option value="data">Data</option>
            <option value="devops">DevOps</option>
          </select>

          <select
            value={filter.source_type}
            onChange={(e) => setFilter({ ...filter, source_type: e.target.value })}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Source Types</option>
            <option value="git">Git</option>
            <option value="archive">Archive</option>
          </select>

          <select
            value={filter.pricing_type}
            onChange={(e) => setFilter({ ...filter, pricing_type: e.target.value })}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Pricing Types</option>
            <option value="free">Free</option>
            <option value="one_time">One Time</option>
            <option value="monthly">Monthly</option>
          </select>

          <select
            value={filter.is_active}
            onChange={(e) => setFilter({ ...filter, is_active: e.target.value })}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700 [&>option]:text-white"
          >
            <option value="">All Status</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </div>
      </div>

      {/* Bases List */}
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-750 border-b border-[var(--text)]/15">
            <tr>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Base</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Category</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Source Type</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Pricing</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Downloads</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Status</th>
              <th className="text-right px-6 py-3 text-gray-400 font-medium text-sm">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {bases.map((base) => (
              <tr key={base.id} className="hover:bg-gray-700/50 transition-colors">
                <td className="px-6 py-4">
                  <div className="flex items-center space-x-3">
                    <span className="text-2xl">{base.icon}</span>
                    <div>
                      <div className="text-white font-medium">{base.name}</div>
                      <div className="text-gray-400 text-sm">/{base.slug}</div>
                      {!base.can_edit && (
                        <div className="text-yellow-500 text-xs mt-1">
                          {base.created_by_username
                            ? `By ${base.created_by_username}`
                            : 'User-created'}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-gray-300 capitalize">{base.category}</span>
                </td>
                <td className="px-6 py-4">
                  <span
                    className={`px-2 py-1 rounded text-xs ${base.source_type === 'git' ? 'bg-green-500/20 text-green-400' : 'bg-blue-500/20 text-blue-400'}`}
                  >
                    {base.source_type}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div>
                    <span className="text-gray-300 capitalize">{base.pricing_type}</span>
                    {(base.pricing_type === 'one_time' || base.pricing_type === 'monthly') && (
                      <div className="text-gray-400 text-sm">
                        ${(base.price / 100).toFixed(2)}
                        {base.pricing_type === 'monthly' ? '/mo' : ''}
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-gray-300">{base.downloads}</span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-col space-y-1">
                    <span
                      className={`px-2 py-1 rounded text-xs w-fit ${base.is_active ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}
                    >
                      {base.is_active ? 'Active' : 'Inactive'}
                    </span>
                    {base.is_featured && (
                      <span className="px-2 py-1 rounded text-xs w-fit bg-yellow-500/20 text-yellow-400">
                        Featured
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center justify-end space-x-2">
                    <button
                      onClick={() => loadBaseDetails(base.id)}
                      className="text-blue-400 hover:text-blue-300 text-sm"
                      title={base.can_edit ? 'Edit base' : 'View base'}
                    >
                      {base.can_edit ? 'Edit' : 'View'}
                    </button>
                    <button
                      onClick={() => handleToggleFeatured(base)}
                      className="text-yellow-400 hover:text-yellow-300 text-sm"
                      title={base.is_featured ? 'Unfeature' : 'Feature'}
                    >
                      {base.is_featured ? '\u2605' : '\u2606'}
                    </button>
                    {base.is_active ? (
                      <button
                        onClick={() => handleRemoveFromMarketplace(base)}
                        className="text-[var(--primary)] hover:text-[var(--primary-hover)] text-sm"
                        title="Remove from marketplace"
                      >
                        Hide
                      </button>
                    ) : (
                      <button
                        onClick={() => handleRestoreToMarketplace(base)}
                        className="text-green-400 hover:text-green-300 text-sm"
                        title="Restore to marketplace"
                      >
                        Show
                      </button>
                    )}
                    {base.can_edit && (
                      <button
                        onClick={() => handleDelete(base)}
                        className="text-red-400 hover:text-red-300 text-sm"
                        title="Delete base"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {bases.length === 0 && (
          <div className="text-center py-12 text-gray-400">No bases found</div>
        )}
      </div>

      {/* Create/Edit Modals */}
      {showCreateModal && (
        <BaseFormModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            loadBases();
          }}
        />
      )}

      {showEditModal && selectedBase && (
        <BaseFormModal
          base={selectedBase}
          onClose={() => {
            setShowEditModal(false);
            setSelectedBase(null);
          }}
          onSuccess={() => {
            setShowEditModal(false);
            setSelectedBase(null);
            loadBases();
          }}
        />
      )}
    </div>
  );
}

// ============================================================================
// Base Form Modal Component
// ============================================================================

interface BaseFormModalProps {
  base?: BaseDetailed;
  onClose: () => void;
  onSuccess: () => void;
}

function BaseFormModal({ base, onClose, onSuccess }: BaseFormModalProps) {
  const isEdit = !!base;
  const canEdit = !base || base.can_edit;

  const [formData, setFormData] = useState({
    name: base?.name || '',
    description: base?.description || '',
    long_description: base?.long_description || '',
    git_repo_url: base?.git_repo_url || '',
    default_branch: base?.default_branch || 'main',
    source_type: base?.source_type || 'git',
    category: base?.category || 'fullstack',
    icon: base?.icon || '\uD83D\uDCE6',
    preview_image: base?.preview_image || '',
    pricing_type: base?.pricing_type || 'free',
    price: base?.price ? base.price / 100 : 0,
    visibility: base?.visibility || 'public',
    features: base?.features?.join(', ') || '',
    tech_stack: base?.tech_stack?.join(', ') || '',
    tags: base?.tags?.join(', ') || '',
    is_featured: base?.is_featured || false,
    is_active: base?.is_active !== undefined ? base.is_active : true,
  });

  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!canEdit) {
      toast.error('Cannot edit this base');
      return;
    }

    setSaving(true);

    try {
      const payload = {
        ...formData,
        price:
          formData.pricing_type === 'one_time' || formData.pricing_type === 'monthly'
            ? Math.round(formData.price * 100)
            : 0,
        features: formData.features
          .split(',')
          .map((f) => f.trim())
          .filter((f) => f),
        tech_stack: formData.tech_stack
          .split(',')
          .map((t) => t.trim())
          .filter((t) => t),
        tags: formData.tags
          .split(',')
          .map((t) => t.trim())
          .filter((t) => t),
      };

      const url = isEdit ? `/api/admin/bases/${base.id}` : '/api/admin/bases';
      const method = isEdit ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save base');
      }

      toast.success(`Base ${isEdit ? 'updated' : 'created'} successfully`);
      onSuccess();
    } catch (error: unknown) {
      console.error('Failed to save base:', error);
      const err = error as { message?: string };
      toast.error(err.message || 'Failed to save base');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-4xl w-full my-8">
        <div className="p-6 border-b border-[var(--text)]/15">
          <h2 className="text-2xl font-bold text-white">
            {isEdit ? (canEdit ? 'Edit Base' : 'View Base') : 'Create New Base'}
          </h2>
          {isEdit && !canEdit && (
            <p className="text-yellow-500 text-sm mt-2">
              This is a user-created base. You can only view it, not edit it.
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Basic Info */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Name *</label>
              <input
                type="text"
                required
                disabled={!canEdit}
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Icon</label>
              <input
                type="text"
                disabled={!canEdit}
                value={formData.icon}
                onChange={(e) => setFormData({ ...formData, icon: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                placeholder="\uD83D\uDCE6"
              />
            </div>
          </div>

          {/* Preview Image */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Preview Image</label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.preview_image}
              onChange={(e) => setFormData({ ...formData, preview_image: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="https://example.com/preview.png"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Description *</label>
            <input
              type="text"
              required
              disabled={!canEdit}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              maxLength={500}
            />
          </div>

          {/* Long Description */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Long Description</label>
            <textarea
              disabled={!canEdit}
              value={formData.long_description}
              onChange={(e) => setFormData({ ...formData, long_description: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              rows={3}
            />
          </div>

          {/* Git Source */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Git Repo URL</label>
              <input
                type="text"
                disabled={!canEdit}
                value={formData.git_repo_url}
                onChange={(e) => setFormData({ ...formData, git_repo_url: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                placeholder="https://github.com/user/repo"
              />
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Default Branch</label>
              <input
                type="text"
                disabled={!canEdit}
                value={formData.default_branch}
                onChange={(e) => setFormData({ ...formData, default_branch: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                placeholder="main"
              />
            </div>
          </div>

          {/* Classification */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Category *</label>
              <select
                required
                disabled={!canEdit}
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                <option value="fullstack">Fullstack</option>
                <option value="frontend">Frontend</option>
                <option value="backend">Backend</option>
                <option value="mobile">Mobile</option>
                <option value="data">Data</option>
                <option value="devops">DevOps</option>
              </select>
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Source Type *</label>
              <select
                required
                disabled={!canEdit}
                value={formData.source_type}
                onChange={(e) => setFormData({ ...formData, source_type: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                <option value="git">Git</option>
                <option value="archive">Archive</option>
              </select>
            </div>
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">Visibility *</label>
              <select
                required
                disabled={!canEdit}
                value={formData.visibility}
                onChange={(e) => setFormData({ ...formData, visibility: e.target.value })}
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
              >
                <option value="public">Public</option>
                <option value="private">Private</option>
              </select>
            </div>
          </div>

          {/* Pricing */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">Pricing Type *</label>
            <select
              required
              disabled={!canEdit}
              value={formData.pricing_type}
              onChange={(e) => setFormData({ ...formData, pricing_type: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50 [&>option]:bg-gray-700 [&>option]:text-white"
            >
              <option value="free">Free</option>
              <option value="one_time">One-Time Purchase</option>
              <option value="monthly">Monthly Subscription</option>
            </select>
          </div>

          {(formData.pricing_type === 'one_time' || formData.pricing_type === 'monthly') && (
            <div>
              <label className="block text-gray-300 text-sm font-medium mb-2">
                Price ($) {formData.pricing_type === 'monthly' ? '/ month' : ''}
              </label>
              <input
                type="number"
                step="0.01"
                disabled={!canEdit}
                value={formData.price}
                onChange={(e) =>
                  setFormData({ ...formData, price: parseFloat(e.target.value) || 0 })
                }
                className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
                min="0"
                placeholder="e.g., 9.99"
              />
            </div>
          )}

          {/* Lists */}
          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">
              Features (comma-separated)
            </label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.features}
              onChange={(e) => setFormData({ ...formData, features: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="Hot reloading, TypeScript support"
            />
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">
              Tech Stack (comma-separated)
            </label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.tech_stack}
              onChange={(e) => setFormData({ ...formData, tech_stack: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="React, TypeScript, Vite"
            />
          </div>

          <div>
            <label className="block text-gray-300 text-sm font-medium mb-2">
              Tags (comma-separated)
            </label>
            <input
              type="text"
              disabled={!canEdit}
              value={formData.tags}
              onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
              className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20 disabled:opacity-50"
              placeholder="react, typescript, starter"
            />
          </div>

          {/* Flags */}
          <div className="grid grid-cols-2 gap-4">
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.is_featured}
                onChange={(e) => setFormData({ ...formData, is_featured: e.target.checked })}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">Featured</span>
            </label>

            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                disabled={!canEdit}
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="w-5 h-5 rounded border-[var(--text)]/20 bg-gray-700 text-blue-600 disabled:opacity-50"
              />
              <span className="text-gray-300">Active</span>
            </label>
          </div>
        </form>

        <div className="p-6 border-t border-[var(--text)]/15 flex items-center justify-end space-x-4">
          <button
            type="button"
            onClick={onClose}
            className="px-6 py-2 rounded-lg bg-gray-700 text-white hover:bg-gray-600"
          >
            {canEdit ? 'Cancel' : 'Close'}
          </button>
          {canEdit && (
            <button
              type="submit"
              disabled={saving}
              onClick={handleSubmit}
              className="px-6 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center space-x-2"
            >
              {saving ? (
                <>
                  <RefreshCw size={16} className="animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <span>{isEdit ? 'Update Base' : 'Create Base'}</span>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
