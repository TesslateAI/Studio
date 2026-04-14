import { useState } from 'react';
import { X, Plus, CaretDown, CaretRight } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { marketplaceApi } from '../../lib/api';
import { runOAuthPopup } from './ConnectorOAuthPopup';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  scopeLevel: 'team' | 'user' | 'project';
  teamId?: string;
  projectId?: string;
}

export function AddCustomConnectorModal({
  open,
  onClose,
  onSuccess,
  scopeLevel,
  teamId,
  projectId,
}: Props) {
  const [name, setName] = useState('');
  const [serverUrl, setServerUrl] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [scope, setScope] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const canSubmit = !!serverUrl.trim();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || submitting) return;

    const hasClient = !!clientId.trim();
    const registrationMethod = hasClient ? ('byo' as const) : ('dcr' as const);

    setSubmitting(true);
    try {
      const { authorize_url, flow_id } = await marketplaceApi.startMcpOAuth({
        server_url: serverUrl.trim(),
        registration_method: registrationMethod,
        scope_level: scopeLevel,
        team_id: teamId,
        project_id: projectId,
        byo_client_id: hasClient ? clientId.trim() : undefined,
        byo_client_secret: clientSecret.trim() || undefined,
        scope: scope.trim() || undefined,
      });

      const result = await runOAuthPopup(
        authorize_url,
        flow_id,
        marketplaceApi.getMcpOAuthStatus,
      );
      if (result.status === 'success') {
        toast.success(`Connected ${name || 'connector'}`);
        onSuccess();
        onClose();
        setName('');
        setServerUrl('');
        setClientId('');
        setClientSecret('');
        setScope('');
      } else {
        toast.error(result.message || 'Connection failed');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start OAuth flow';
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border"
        style={{
          background: 'var(--bg)',
          borderColor: 'var(--border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <h2 className="font-semibold text-[var(--text)]">Add custom connector</h2>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)]"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
              Name (optional)
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My MCP server"
              className="w-full px-3 py-2 text-sm rounded border bg-transparent"
              style={{ borderColor: 'var(--border)' }}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
              Server URL
            </label>
            <input
              type="url"
              required
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              placeholder="https://mcp.example.com/mcp"
              className="w-full px-3 py-2 text-sm rounded border bg-transparent"
              style={{ borderColor: 'var(--border)' }}
            />
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              The MCP server's streamable-http endpoint. We'll discover OAuth metadata and
              dynamically register a client unless you provide one below.
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              className="flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              {advancedOpen ? <CaretDown size={14} /> : <CaretRight size={14} />}
              Advanced (bring your own OAuth client)
            </button>
            {advancedOpen && (
              <div className="mt-3 space-y-3 pl-5 border-l-2" style={{ borderColor: 'var(--border)' }}>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    OAuth Client ID
                  </label>
                  <input
                    type="text"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded border bg-transparent"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    OAuth Client Secret
                  </label>
                  <input
                    type="password"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded border bg-transparent"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    Scope (optional)
                  </label>
                  <input
                    type="text"
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    placeholder="read write"
                    className="w-full px-3 py-2 text-sm rounded border bg-transparent"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="text-sm px-3 py-1.5 rounded text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit || submitting}
              className="btn btn-primary text-sm px-3 py-1.5 rounded flex items-center gap-1 disabled:opacity-50"
            >
              <Plus size={14} />
              {submitting ? 'Connecting...' : 'Connect'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
