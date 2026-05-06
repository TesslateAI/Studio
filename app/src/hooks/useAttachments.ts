import { useState, useCallback, useRef, useEffect } from 'react';
import type { ChatAttachment, SerializedAttachment } from '../types/agent';

export function useAttachments() {
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const objectUrlsRef = useRef<string[]>([]);

  const addImage = useCallback((file: File) => {
    const previewUrl = URL.createObjectURL(file);
    objectUrlsRef.current.push(previewUrl);
    const attachment: ChatAttachment = {
      id: crypto.randomUUID(),
      type: 'image',
      file,
      previewUrl,
      mimeType: file.type,
    };
    setAttachments((prev) => (prev.length >= 10 ? prev : [...prev, attachment]));
  }, []);

  const addPastedText = useCallback((text: string) => {
    const lineCount = text.split('\n').length;
    const attachment: ChatAttachment = {
      id: crypto.randomUUID(),
      type: 'pasted_text',
      text,
      lineCount,
    };
    setAttachments((prev) => (prev.length >= 10 ? prev : [...prev, attachment]));
  }, []);

  const addFileReference = useCallback(
    (
      filePath: string,
      fileName: string,
      opts?: { attachmentId?: string; mimeType?: string; sizeBytes?: number }
    ) => {
      setAttachments((prev) => {
        if (prev.length >= 10) return prev;
        // Don't add duplicate file references
        if (prev.some((a) => a.type === 'file_reference' && a.filePath === filePath)) return prev;
        const attachment: ChatAttachment = {
          id: crypto.randomUUID(),
          type: 'file_reference',
          filePath,
          fileName,
          attachmentId: opts?.attachmentId,
          mimeType: opts?.mimeType,
          sizeBytes: opts?.sizeBytes,
        };
        return [...prev, attachment];
      });
    },
    []
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const removed = prev.find((a) => a.id === id);
      if (removed?.previewUrl) {
        URL.revokeObjectURL(removed.previewUrl);
        objectUrlsRef.current = objectUrlsRef.current.filter((u) => u !== removed.previewUrl);
      }
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  const clearAttachments = useCallback(() => {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    objectUrlsRef.current = [];
    setAttachments([]);
  }, []);

  // Revoke any remaining object URLs on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  const serializeForSend = useCallback(async (): Promise<SerializedAttachment[]> => {
    const results: SerializedAttachment[] = [];
    for (const att of attachments) {
      if (att.type === 'image' && att.file) {
        const base64 = await fileToBase64(att.file);
        results.push({
          type: 'image',
          content: base64,
          mime_type: att.mimeType,
          label: att.file.name,
        });
      } else if (att.type === 'pasted_text' && att.text) {
        results.push({
          type: 'pasted_text',
          content: att.text,
          label: `Pasted text (${att.lineCount} lines)`,
        });
      } else if (att.type === 'file_reference' && att.filePath) {
        results.push({
          type: 'file_reference',
          file_path: att.filePath,
          label: att.fileName,
          mime_type: att.mimeType,
          attachment_id: att.attachmentId,
        });
      }
    }
    return results;
  }, [attachments]);

  return {
    attachments,
    addImage,
    addPastedText,
    addFileReference,
    removeAttachment,
    clearAttachments,
    serializeForSend,
  };
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip the data:...;base64, prefix
      const base64 = result.split(',')[1] || result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
