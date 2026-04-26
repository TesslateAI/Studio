import { useState } from 'react';
import { automationsApi } from '../../../lib/api';
import type { AutomationRunArtifactOut } from '../../../types/automations';

interface Props {
  automationId: string;
  runId: string;
  artifact: AutomationRunArtifactOut;
}

/**
 * Phase 1 artifact preview. Renders inline-storage content (markdown/json/text)
 * directly; everything else collapses to a download link.
 */
export function ArtifactPreview({ automationId, runId, artifact }: Props) {
  const [open, setOpen] = useState(false);
  const downloadUrl = automationsApi.artifactDownloadUrl(
    automationId,
    runId,
    artifact.id
  );

  const isInline = artifact.storage_mode === 'inline' || artifact.storage_mode === 'cas';
  const previewable =
    isInline &&
    (artifact.kind === 'text' ||
      artifact.kind === 'markdown' ||
      artifact.kind === 'json' ||
      artifact.kind === 'log' ||
      artifact.preview_text != null);

  return (
    <div className="rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="flex items-baseline gap-2 min-w-0 flex-1">
          <span className="text-xs font-medium text-[var(--text)] truncate">
            {artifact.name || '(unnamed)'}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
            {artifact.kind}
          </span>
          {artifact.size_bytes != null && (
            <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
              {formatBytes(artifact.size_bytes)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {previewable && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="btn btn-sm"
            >
              {open ? 'Hide' : 'Preview'}
            </button>
          )}
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-sm"
          >
            Download
          </a>
        </div>
      </div>

      {open && previewable && (
        <pre className="border-t border-[var(--border)] m-0 max-h-72 overflow-auto bg-[var(--bg)] px-3 py-2 text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap break-words">
          {artifact.preview_text ?? '(no preview text)'}
        </pre>
      )}
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
