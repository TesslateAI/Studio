import { useState, useRef } from 'react';
import { Image, Upload, X } from '@phosphor-icons/react';
import toast from 'react-hot-toast';

interface ImageUploadProps {
  value?: string | null;
  onChange: (dataUrl: string | null) => void;
  maxSizeKB?: number;
  className?: string;
}

export function ImageUpload({
  value,
  onChange,
  maxSizeKB = 200, // 200KB default
  className = ''
}: ImageUploadProps) {
  const [preview, setPreview] = useState<string | null>(value || null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const optimizeImage = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();

      reader.onload = (e) => {
        const img = new window.Image();
        img.onload = () => {
          // Create canvas for optimization
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');

          if (!ctx) {
            reject(new Error('Failed to get canvas context'));
            return;
          }

          // Target size: 128x128 for avatars
          const targetSize = 128;
          canvas.width = targetSize;
          canvas.height = targetSize;

          // Draw image centered and cropped to square
          const size = Math.min(img.width, img.height);
          const x = (img.width - size) / 2;
          const y = (img.height - size) / 2;

          ctx.drawImage(
            img,
            x, y, size, size,  // Source rectangle (square crop from center)
            0, 0, targetSize, targetSize  // Destination rectangle
          );

          // Convert to base64 with compression
          let quality = 0.9;
          let dataUrl = canvas.toDataURL('image/jpeg', quality);

          // Reduce quality until size is acceptable
          while (dataUrl.length > maxSizeKB * 1024 * 1.37 && quality > 0.1) {
            quality -= 0.1;
            dataUrl = canvas.toDataURL('image/jpeg', quality);
          }

          const sizeKB = Math.round(dataUrl.length / 1024 / 1.37);
          console.log(`Optimized image: ${sizeKB}KB (quality: ${Math.round(quality * 100)}%)`);

          resolve(dataUrl);
        };

        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = e.target?.result as string;
      };

      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      toast.error('Please select an image file');
      return;
    }

    // Validate file size (10MB max before optimization)
    if (file.size > 10 * 1024 * 1024) {
      toast.error('Image file is too large (max 10MB)');
      return;
    }

    setUploading(true);

    try {
      const optimizedDataUrl = await optimizeImage(file);
      setPreview(optimizedDataUrl);
      onChange(optimizedDataUrl);
      toast.success('Logo uploaded successfully');
    } catch (error) {
      console.error('Image optimization failed:', error);
      toast.error('Failed to process image');
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = () => {
    setPreview(null);
    onChange(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    toast.success('Logo removed');
  };

  return (
    <div className={className}>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileSelect}
        className="hidden"
      />

      <div className="flex items-center gap-4">
        {/* Preview */}
        <div className="relative w-24 h-24 flex-shrink-0">
          {preview ? (
            <>
              <img
                src={preview}
                alt="Agent logo"
                className="w-full h-full rounded-xl object-cover border-2 border-[var(--text)]/10"
              />
              <button
                type="button"
                onClick={handleRemove}
                className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center transition-colors"
                title="Remove logo"
              >
                <X size={14} weight="bold" />
              </button>
            </>
          ) : (
            <div className="w-full h-full rounded-xl border-2 border-dashed border-[var(--text)]/20 flex items-center justify-center bg-[var(--text)]/5">
              <Image size={32} className="text-[var(--text)]/40" />
            </div>
          )}
        </div>

        {/* Upload Button */}
        <div className="flex-1">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 text-blue-400 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            <Upload size={16} />
            {uploading ? 'Processing...' : preview ? 'Change Logo' : 'Upload Logo'}
          </button>
          <p className="mt-2 text-xs text-[var(--text)]/40">
            Recommended: Square image, will be resized to 128x128px
          </p>
          <p className="text-xs text-[var(--text)]/40">
            Max size: {maxSizeKB}KB after optimization
          </p>
        </div>
      </div>
    </div>
  );
}
