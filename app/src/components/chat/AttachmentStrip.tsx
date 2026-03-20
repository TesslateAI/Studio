import type { ChatAttachment, SerializedAttachment } from '../../types/agent';
import { AttachmentChip } from './AttachmentChip';

interface AttachmentStripProps {
  attachments: (ChatAttachment | SerializedAttachment)[];
  onRemove?: (id: string) => void;
}

export function AttachmentStrip({ attachments, onRemove }: AttachmentStripProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-b border-[var(--border)]">
      {attachments.map((att) => {
        const key = 'id' in att ? att.id : `${att.type}-${att.file_path || att.label || Math.random()}`;
        return (
          <AttachmentChip
            key={key}
            attachment={att}
            onRemove={onRemove && 'id' in att ? () => onRemove(att.id) : undefined}
          />
        );
      })}
    </div>
  );
}
