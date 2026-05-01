import { useState } from 'react';
import { X } from '@phosphor-icons/react';
import type { ChatAttachment, SerializedAttachment } from '../../types/agent';

interface AttachmentChipProps {
  attachment: ChatAttachment | SerializedAttachment;
  onRemove?: () => void;
}

function isLiveAttachment(att: ChatAttachment | SerializedAttachment): att is ChatAttachment {
  return 'id' in att;
}

export function AttachmentChip({ attachment, onRemove }: AttachmentChipProps) {
  const [showPreview, setShowPreview] = useState(false);
  const isLive = isLiveAttachment(attachment);

  if (attachment.type === 'image') {
    const src = isLive
      ? attachment.previewUrl
      : attachment.content
        ? `data:${attachment.mime_type || 'image/png'};base64,${attachment.content}`
        : undefined;
    return (
      <div className="relative group inline-flex items-center gap-1">
        {src && (
          <button
            type="button"
            onClick={() => setShowPreview(!showPreview)}
            className="w-7 h-7 rounded-md overflow-hidden border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors flex-shrink-0"
          >
            <img src={src} alt="attachment" className="w-full h-full object-cover" />
          </button>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500/20 hover:border-red-500/40"
          >
            <X size={8} weight="bold" className="text-[var(--text-muted)]" />
          </button>
        )}
        {showPreview && src && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
            onClick={() => setShowPreview(false)}
          >
            <img
              src={src}
              alt="preview"
              className="max-w-[80vw] max-h-[80vh] rounded-lg shadow-2xl"
            />
          </div>
        )}
      </div>
    );
  }

  if (attachment.type === 'pasted_text') {
    const lineCount = isLive ? attachment.lineCount : attachment.content?.split('\n').length || 0;
    const fullText = isLive ? attachment.text : attachment.content;
    return (
      <div className="relative group inline-flex items-center">
        <button
          type="button"
          onClick={() => setShowPreview(!showPreview)}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium bg-[var(--surface-hover)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--border-hover)] transition-colors"
        >
          <span>Pasted text +{lineCount} lines</span>
        </button>
        {onRemove && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500/20 hover:border-red-500/40"
          >
            <X size={8} weight="bold" className="text-[var(--text-muted)]" />
          </button>
        )}
        {showPreview && fullText && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8"
            onClick={() => setShowPreview(false)}
          >
            <div
              className="bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-2xl max-w-2xl max-h-[70vh] overflow-auto p-4"
              onClick={(e) => e.stopPropagation()}
            >
              <pre className="text-xs text-[var(--text)] font-mono whitespace-pre-wrap">
                {fullText}
              </pre>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (attachment.type === 'file_reference') {
    const fileName = isLive ? attachment.fileName : attachment.label;
    return (
      <div className="relative group inline-flex items-center">
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium bg-[var(--primary)]/10 border border-[var(--primary)]/30 text-[var(--primary)]">
          <span className="opacity-70">@</span>
          <span>{fileName}</span>
        </span>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500/20 hover:border-red-500/40"
          >
            <X size={8} weight="bold" className="text-[var(--text-muted)]" />
          </button>
        )}
      </div>
    );
  }

  return null;
}
