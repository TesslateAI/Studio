// Asset types for the Assets Panel

export type FileType = 'image' | 'video' | 'font' | 'document' | 'audio' | 'other';

export interface Asset {
  id: string;
  filename: string;
  directory: string;
  file_path: string;
  file_type: FileType;
  file_size: number;
  mime_type: string;
  width?: number;
  height?: number;
  created_at: string;
  url: string;
}

export interface AssetUploadParams {
  file: File;
  directory: string;
}

export interface AssetDirectory {
  path: string;
  name: string;
  asset_count?: number;
}

export interface AssetRenameParams {
  assetId: string;
  new_filename: string;
}

export interface AssetMoveParams {
  assetId: string;
  directory: string;
}

export interface CreateDirectoryParams {
  path: string;
}

// Framework-specific directory presets
export type FrameworkType = 'nextjs' | 'vite' | 'react' | 'fastapi' | 'generic';

export interface DirectoryPreset {
  framework: FrameworkType;
  directories: string[];
}

export const DIRECTORY_PRESETS: Record<FrameworkType, string[]> = {
  nextjs: ['/public', '/public/images', '/public/fonts', '/public/videos', '/assets'],
  vite: ['/public', '/src/assets', '/src/assets/images', '/src/assets/fonts'],
  react: ['/public', '/src/assets', '/src/images'],
  fastapi: ['/static', '/static/images', '/static/fonts', '/media'],
  generic: ['/assets', '/public', '/images', '/media'],
};

// File size formatter
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

// Get file icon based on type
export function getFileIcon(fileType: FileType): string {
  switch (fileType) {
    case 'image':
      return 'Image';
    case 'video':
      return 'Video';
    case 'font':
      return 'TextT';
    case 'document':
      return 'File';
    case 'audio':
      return 'MusicNote';
    default:
      return 'File';
  }
}

// Get file type badge color
export function getFileTypeBadgeColor(fileType: FileType): string {
  switch (fileType) {
    case 'image':
      return 'bg-blue-500/20 text-blue-400';
    case 'video':
      return 'bg-purple-500/20 text-purple-400';
    case 'font':
      return 'bg-green-500/20 text-green-400';
    case 'document':
      return 'bg-orange-500/20 text-orange-400';
    case 'audio':
      return 'bg-pink-500/20 text-pink-400';
    default:
      return 'bg-gray-500/20 text-gray-400';
  }
}

// Validate file before upload
export interface FileValidationResult {
  valid: boolean;
  error?: string;
}

export function validateFile(file: File): FileValidationResult {
  const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

  const ALLOWED_TYPES = [
    // Images
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/svg+xml', 'image/webp', 'image/bmp', 'image/ico', 'image/x-icon',
    // Videos
    'video/mp4', 'video/webm', 'video/ogg', 'video/quicktime', 'video/x-msvideo',
    // Fonts
    'font/woff', 'font/woff2', 'font/ttf', 'font/otf', 'application/font-woff', 'application/font-woff2', 'application/x-font-ttf', 'application/x-font-otf',
    // Documents
    'application/pdf',
    // Audio
    'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm',
  ];

  if (file.size > MAX_FILE_SIZE) {
    return {
      valid: false,
      error: `File size (${formatFileSize(file.size)}) exceeds maximum allowed size (20MB)`
    };
  }

  if (!ALLOWED_TYPES.includes(file.type)) {
    return {
      valid: false,
      error: `File type ${file.type} is not allowed. Only images, videos, fonts, PDFs, and audio files are supported.`
    };
  }

  return { valid: true };
}

// Detect framework from package.json or other indicators
export function detectFramework(packageJson?: any): FrameworkType {
  if (!packageJson) return 'generic';

  const dependencies = {
    ...packageJson.dependencies,
    ...packageJson.devDependencies
  };

  if (dependencies['next']) return 'nextjs';
  if (dependencies['vite']) return 'vite';
  if (dependencies['react']) return 'react';
  if (dependencies['fastapi']) return 'fastapi';

  return 'generic';
}

// Add auth token to asset URL for image loading
export function getAuthenticatedAssetUrl(url: string): string {
  const token = localStorage.getItem('token');
  if (!token) return url;

  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}auth_token=${token}`;
}
