import { useState, useEffect } from 'react';
import { Server, Pencil, Trash2, X } from 'lucide-react';
import { secretsApi } from '../../lib/api';
import toast from 'react-hot-toast';

export interface CustomProvider {
  id: string;
  name: string;
  slug: string;
  base_url: string;
  api_type: string;
  default_headers?: Record<string, string>;
  available_models: string[];
  created_at?: string;
}

// ─── Custom Provider Card ────────────────────────────────────────────────────

export function CustomProviderCard({
  provider,
  onEdit,
  onDelete,
}: {
  provider: CustomProvider;
  onEdit: () => void;
  onDelete: (id: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const modelCount = provider.available_models?.length || 0;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2.5 bg-[rgba(var(--primary-rgb),0.1)] rounded-lg flex-shrink-0">
            <Server className="w-5 h-5 text-[var(--primary)]" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-[var(--text)]">{provider.name}</div>
            <div className="text-xs text-[var(--text-subtle)] font-mono mt-0.5">
              {provider.base_url}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-muted)]">
                {provider.slug}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-muted)]">
                {provider.api_type}
              </span>
              <span className="text-[10px] text-[var(--text-subtle)]">
                {modelCount} model{modelCount !== 1 ? 's' : ''}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={onEdit}
            className="p-1.5 hover:bg-[var(--surface-hover)] rounded-lg text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors"
          >
            <Pencil className="w-4 h-4" />
          </button>
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => onDelete(provider.id)}
                className="px-2 py-1 text-xs bg-[var(--status-error)]/20 text-[var(--status-error)] rounded hover:bg-[var(--status-error)]/30 transition-colors"
              >
                Delete
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-2 py-1 text-xs bg-[var(--surface-hover)] text-[var(--text-muted)] rounded hover:bg-[var(--surface-hover)] transition-colors"
              >
                No
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="p-1.5 hover:bg-[var(--status-error)]/10 rounded-lg text-[var(--text-subtle)] hover:text-[var(--status-error)] transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      {modelCount > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--text)]/5 flex flex-wrap gap-1.5">
          {provider.available_models.map((model) => (
            <span
              key={model}
              className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--surface-hover)] text-[var(--text-muted)] font-mono"
            >
              {model}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Custom Provider Modal (Create + Edit) ───────────────────────────────────

export function CustomProviderModal({
  existing,
  onClose,
  onSuccess,
}: {
  existing: CustomProvider | null;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const isEdit = existing !== null;
  const [name, setName] = useState(existing?.name || '');
  const [slug, setSlug] = useState(existing?.slug || '');
  const [baseUrl, setBaseUrl] = useState(existing?.base_url || '');
  const [apiType, setApiType] = useState(existing?.api_type || 'openai');
  const [models, setModels] = useState<string[]>(existing?.available_models || []);
  const [modelInput, setModelInput] = useState('');
  const [loading, setLoading] = useState(false);

  // Auto-generate slug from name (only on create)
  useEffect(() => {
    if (!isEdit && name) {
      setSlug(
        name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '')
      );
    }
  }, [name, isEdit]);

  const addModel = () => {
    const trimmed = modelInput.trim();
    if (trimmed && !models.includes(trimmed)) {
      setModels([...models, trimmed]);
      setModelInput('');
    }
  };

  const removeModel = (model: string) => {
    setModels(models.filter((m) => m !== model));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (isEdit) {
        await secretsApi.updateCustomProvider(existing.id, {
          name,
          base_url: baseUrl,
          api_type: apiType,
          available_models: models,
        });
        toast.success('Provider updated');
      } else {
        await secretsApi.createCustomProvider({
          name,
          slug,
          base_url: baseUrl,
          api_type: apiType,
          available_models: models,
        });
        toast.success('Provider created');
      }
      onSuccess();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(
        err.response?.data?.detail || `Failed to ${isEdit ? 'update' : 'create'} provider`
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-[var(--text)]">
            {isEdit ? 'Edit Provider' : 'Add Custom Provider'}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--surface-hover)] rounded-lg transition-colors text-[var(--text-muted)] text-sm"
          >
            Cancel
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Provider Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 text-sm"
              placeholder="My Ollama Server"
              required
            />
          </div>

          {/* Slug (readonly on edit) */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Slug</label>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, ''))}
              className="w-full px-4 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm disabled:opacity-50"
              placeholder="my-ollama"
              required
              disabled={isEdit}
            />
            <p className="mt-1 text-xs text-[var(--text-subtle)]">
              Used as model prefix: <span className="font-mono">{slug || 'slug'}/model-name</span>
            </p>
          </div>

          {/* Base URL */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Base URL</label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full px-4 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
              placeholder="http://localhost:11434/v1"
              required
            />
          </div>

          {/* API Type */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">API Type</label>
            <select
              value={apiType}
              onChange={(e) => setApiType(e.target.value)}
              className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
            >
              <option value="openai">OpenAI Compatible</option>
              <option value="anthropic">Anthropic Compatible</option>
            </select>
          </div>

          {/* Available Models */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Available Models
            </label>
            <p className="text-xs text-[var(--text-subtle)] mb-3">
              Add the model IDs available on this provider. These will appear in the model selector.
            </p>

            {models.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {models.map((model) => (
                  <span
                    key={model}
                    className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-[var(--surface-hover)] border border-[var(--border)] text-[var(--text-muted)] font-mono"
                  >
                    {model}
                    <button
                      type="button"
                      onClick={() => removeModel(model)}
                      className="p-0.5 hover:bg-[var(--status-error)]/20 rounded-full text-[var(--text-subtle)] hover:text-[var(--status-error)] transition-colors"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <input
                type="text"
                value={modelInput}
                onChange={(e) => setModelInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addModel();
                  }
                }}
                className="flex-1 px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
                placeholder="llama3.1:70b"
              />
              <button
                type="button"
                onClick={addModel}
                disabled={!modelInput.trim()}
                className="px-3 py-2 bg-[var(--surface-hover)] hover:bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-[var(--text-muted)] text-sm transition-colors disabled:opacity-30"
              >
                Add
              </button>
            </div>
            <p className="mt-1 text-xs text-[var(--text-subtle)]">
              Press Enter to add. Model IDs should match what the API expects.
            </p>
          </div>

          {/* Submit */}
          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--border)]">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-[var(--surface-hover)] hover:bg-[var(--surface-hover)] rounded-lg text-[var(--text-muted)] text-sm transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading || !name || !slug || !baseUrl}
            >
              {loading
                ? isEdit
                  ? 'Saving...'
                  : 'Creating...'
                : isEdit
                  ? 'Save Changes'
                  : 'Create Provider'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
