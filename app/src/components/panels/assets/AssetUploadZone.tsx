import { useState, useRef } from 'react';
import type { DragEvent } from 'react';
import { UploadSimple, X, CheckCircle, WarningCircle } from '@phosphor-icons/react';
import { validateFile, formatFileSize } from '../../../types/assets';

interface FileWithPreview {
  file: File;
  preview?: string;
  valid: boolean;
  error?: string;
  progress: number;
  uploaded: boolean;
}

interface AssetUploadZoneProps {
  onUpload: (file: File, onProgress: (progress: number) => void) => Promise<void>;
  onClose: () => void;
}

export default function AssetUploadZone({ onUpload, onClose }: AssetUploadZoneProps) {
  const [files, setFiles] = useState<FileWithPreview[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList) return;

    const newFiles: FileWithPreview[] = Array.from(fileList).map((file) => {
      const validation = validateFile(file);
      let preview: string | undefined;

      // Create preview for images
      if (file.type.startsWith('image/')) {
        preview = URL.createObjectURL(file);
      }

      return {
        file,
        preview,
        valid: validation.valid,
        error: validation.error,
        progress: 0,
        uploaded: false,
      };
    });

    setFiles((prev) => [...prev, ...newFiles]);
  };

  const handleDragEnter = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const newFiles = [...prev];
      if (newFiles[index].preview) {
        URL.revokeObjectURL(newFiles[index].preview!);
      }
      newFiles.splice(index, 1);
      return newFiles;
    });
  };

  const uploadFiles = async () => {
    const validFiles = files.filter((f) => f.valid && !f.uploaded);

    for (let i = 0; i < files.length; i++) {
      const fileWithPreview = files[i];
      if (!fileWithPreview.valid || fileWithPreview.uploaded) continue;

      try {
        await onUpload(fileWithPreview.file, (progress) => {
          setFiles((prev) => {
            const newFiles = [...prev];
            newFiles[i].progress = progress;
            return newFiles;
          });
        });

        // Mark as uploaded
        setFiles((prev) => {
          const newFiles = [...prev];
          newFiles[i].uploaded = true;
          newFiles[i].progress = 100;
          return newFiles;
        });
      } catch (error) {
        // Mark as error
        setFiles((prev) => {
          const newFiles = [...prev];
          newFiles[i].valid = false;
          newFiles[i].error = error instanceof Error ? error.message : 'Upload failed';
          return newFiles;
        });
      }
    }

    // Close modal after all uploads complete
    if (validFiles.length > 0) {
      setTimeout(() => {
        onClose();
      }, 1000);
    }
  };

  const allUploaded = files.length > 0 && files.every((f) => f.uploaded || !f.valid);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] rounded-2xl border border-white/10 max-w-2xl w-full max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/10">
          <h2 className="text-xl font-bold text-white">Upload Assets</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400"
          >
            <X size={24} weight="bold" />
          </button>
        </div>

        {/* Drop Zone */}
        <div className="p-6 flex-1 overflow-y-auto">
          {files.length === 0 ? (
            <div
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`
                border-2 border-dashed rounded-xl p-12 text-center transition-all
                ${
                  isDragging
                    ? 'border-orange-500 bg-orange-500/10'
                    : 'border-white/20 hover:border-white/30'
                }
              `}
            >
              <UploadSimple size={48} weight="duotone" className="mx-auto mb-4 text-gray-400" />
              <h3 className="text-lg font-semibold text-gray-200 mb-2">
                Drop files here or click to browse
              </h3>
              <p className="text-sm text-gray-500 mb-4">
                Support for images, videos, fonts, PDFs, and audio files (max 20MB each)
              </p>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-6 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-medium transition-colors"
              >
                Browse Files
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,video/*,font/*,.pdf,audio/*,.woff,.woff2,.ttf,.otf"
                onChange={(e) => handleFiles(e.target.files)}
                className="hidden"
              />
            </div>
          ) : (
            <div className="space-y-3">
              {files.map((fileWithPreview, index) => (
                <div
                  key={index}
                  className="flex items-center gap-3 p-3 bg-black/20 rounded-lg border border-white/10"
                >
                  {/* Preview/Icon */}
                  {fileWithPreview.preview ? (
                    <img
                      src={fileWithPreview.preview}
                      alt={fileWithPreview.file.name}
                      className="w-12 h-12 rounded object-cover"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded bg-black/30 flex items-center justify-center">
                      <UploadSimple size={24} weight="duotone" className="text-gray-400" />
                    </div>
                  )}

                  {/* File Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-200 truncate">
                      {fileWithPreview.file.name}
                    </p>
                    <p className="text-xs text-gray-500">
                      {formatFileSize(fileWithPreview.file.size)}
                    </p>

                    {/* Error Message */}
                    {!fileWithPreview.valid && (
                      <p className="text-xs text-red-400 mt-1">{fileWithPreview.error}</p>
                    )}

                    {/* Progress Bar */}
                    {fileWithPreview.valid && fileWithPreview.progress > 0 && !fileWithPreview.uploaded && (
                      <div className="mt-2 w-full bg-black/30 rounded-full h-1.5 overflow-hidden">
                        <div
                          className="bg-orange-500 h-full transition-all"
                          style={{ width: `${fileWithPreview.progress}%` }}
                        />
                      </div>
                    )}
                  </div>

                  {/* Status Icon */}
                  {fileWithPreview.uploaded ? (
                    <CheckCircle size={24} weight="fill" className="text-green-500" />
                  ) : !fileWithPreview.valid ? (
                    <WarningCircle size={24} weight="fill" className="text-red-500" />
                  ) : (
                    <button
                      onClick={() => removeFile(index)}
                      className="p-1 hover:bg-white/10 rounded transition-colors text-gray-400"
                    >
                      <X size={20} weight="bold" />
                    </button>
                  )}
                </div>
              ))}

              {/* Add More Button */}
              <button
                onClick={() => fileInputRef.current?.click()}
                className="w-full py-3 border-2 border-dashed border-white/20 hover:border-white/30 rounded-lg text-gray-400 hover:text-gray-300 transition-colors text-sm font-medium"
              >
                + Add More Files
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,video/*,font/*,.pdf,audio/*,.woff,.woff2,.ttf,.otf"
                onChange={(e) => handleFiles(e.target.files)}
                className="hidden"
              />
            </div>
          )}
        </div>

        {/* Footer */}
        {files.length > 0 && (
          <div className="flex items-center justify-between p-6 border-t border-white/10">
            <p className="text-sm text-gray-400">
              {files.filter((f) => f.valid).length} of {files.length} files valid
            </p>
            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="px-6 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={uploadFiles}
                disabled={files.filter((f) => f.valid && !f.uploaded).length === 0 || allUploaded}
                className="px-6 py-2 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
              >
                {allUploaded ? 'Done' : 'Upload'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
