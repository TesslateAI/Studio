import { Link } from 'react-router-dom';
import { Warning, ArrowRight } from '@phosphor-icons/react';

/**
 * Rendered when an MCP tool call returned ``_mcp_reauth_required`` — the
 * connector's tokens are missing or unrefreshable and the user must
 * reconnect via Settings → Connectors.
 */
export interface ReauthInfo {
  serverSlug?: string | null;
  serverUrl?: string | null;
  message?: string | null;
  configId?: string | null;
}

export function ReauthBanner({ info }: { info: ReauthInfo }) {
  const label = info.serverSlug || info.serverUrl || 'this connector';
  return (
    <div
      className="rounded-md border px-3 py-2 flex items-start gap-2"
      style={{
        borderColor: 'var(--color-warning, #d97706)',
        background: 'rgba(217, 119, 6, 0.08)',
      }}
    >
      <Warning size={16} weight="fill" className="mt-0.5 flex-shrink-0" color="var(--color-warning, #d97706)" />
      <div className="flex-1">
        <div className="text-sm font-medium text-[var(--text)]">
          Reconnect required for {label}
        </div>
        <div className="text-xs text-[var(--text-muted)] mt-0.5">
          {info.message || "Your OAuth tokens expired or were revoked."}
        </div>
      </div>
      <Link
        to="/settings/connectors"
        className="text-xs font-medium text-[var(--accent)] hover:underline flex items-center gap-0.5 whitespace-nowrap"
      >
        Reconnect <ArrowRight size={12} />
      </Link>
    </div>
  );
}
