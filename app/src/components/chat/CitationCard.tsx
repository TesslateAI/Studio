import { ArrowSquareOut } from '@phosphor-icons/react';

/**
 * Renders a single MCP tool-result citation.
 *
 * The MCP spec (2025-06-18+) lets tool results carry structured metadata
 * under ``_mcp_structured.citation`` — we forward it in `services/mcp/bridge.py`
 * so chat can render a link card instead of raw JSON.
 */
export interface CitationData {
  title?: string;
  url?: string;
  snippet?: string;
  source?: string;
}

export function CitationCard({ citation }: { citation: CitationData }) {
  const url = citation.url;
  const title = citation.title || url || 'Source';

  const body = (
    <div
      className="rounded-md border px-3 py-2"
      style={{ borderColor: 'var(--border)', background: 'var(--hover-bg, rgba(255,255,255,0.03))' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-[var(--text)] truncate">{title}</div>
          {citation.source && (
            <div className="text-[11px] text-[var(--text-muted)] mt-0.5">{citation.source}</div>
          )}
          {citation.snippet && (
            <div className="text-xs text-[var(--text-muted)] mt-1 line-clamp-3">
              {citation.snippet}
            </div>
          )}
        </div>
        {url && <ArrowSquareOut size={14} className="flex-shrink-0 mt-0.5 text-[var(--text-muted)]" />}
      </div>
    </div>
  );

  if (!url) return body;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="block no-underline">
      {body}
    </a>
  );
}

export function Citations({ value }: { value: unknown }) {
  if (!value) return null;
  const items: CitationData[] = Array.isArray(value)
    ? (value as CitationData[])
    : [value as CitationData];
  return (
    <>
      {items.map((c, i) => (
        <CitationCard key={i} citation={c} />
      ))}
    </>
  );
}
