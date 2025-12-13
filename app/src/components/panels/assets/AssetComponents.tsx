import { useState } from 'react';
import { Image, Video, TextT, File, MusicNote, Copy, Trash, PencilSimple, FolderOpen } from '@phosphor-icons/react';
import type { Asset } from '../../../types/assets';
import { formatFileSize, getFileTypeBadgeColor, getAuthenticatedAssetUrl } from '../../../types/assets';
import toast from 'react-hot-toast';

interface AssetCardProps {
  asset: Asset;
  onRename: (assetId: string, newName: string) => void;
  onDelete: (assetId: string) => void;
  onMove: (assetId: string) => void;
  onPreview: (asset: Asset) => void;
}

export function AssetCard({
  asset,
  onRename,
  onDelete,
  onMove,
  onPreview,
}: AssetCardProps) {
  const [isHovered, setIsHovered] = useState(false);

  const getIcon = () => {
    switch (asset.file_type) {
      case 'image':
        return <Image size={24} weight="duotone" />;
      case 'video':
        return <Video size={24} weight="duotone" />;
      case 'font':
        return <TextT size={24} weight="duotone" />;
      case 'audio':
        return <MusicNote size={24} weight="duotone" />;
      default:
        return <File size={24} weight="duotone" />;
    }
  };

  const copyToClipboard = async (text: string, type: string) => {
    await navigator.clipboard.writeText(text);
    toast.success(`${type} copied to clipboard!`);
  };

  return (
    <div
      className="relative bg-[var(--surface)] rounded-xl border border-white/10 overflow-hidden group hover:border-white/20 transition-all"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Preview Area */}
      <div
        className="aspect-square bg-black/20 flex items-center justify-center cursor-pointer relative overflow-hidden"
        onClick={() => onPreview(asset)}
      >
        {asset.file_type === 'image' ? (
          <img
            src={getAuthenticatedAssetUrl(asset.url)}
            alt={asset.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="text-gray-400">{getIcon()}</div>
        )}

        {/* Hover Actions */}
        {isHovered && (
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                copyToClipboard(asset.file_path, 'Path');
              }}
              className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
              title="Copy path"
            >
              <Copy size={18} weight="bold" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onMove(asset.id);
              }}
              className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
              title="Move to directory"
            >
              <FolderOpen size={18} weight="bold" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRename(asset.id, asset.filename);
              }}
              className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
              title="Rename"
            >
              <PencilSimple size={18} weight="bold" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(asset.id);
              }}
              className="p-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg transition-colors"
              title="Delete"
            >
              <Trash size={18} weight="bold" />
            </button>
          </div>
        )}
      </div>

      {/* Info Area */}
      <div className="p-3">
        <p className="text-sm font-medium text-gray-200 truncate" title={asset.filename}>
          {asset.filename}
        </p>
        <div className="flex items-center justify-between mt-2">
          <span className={`text-xs px-2 py-1 rounded ${getFileTypeBadgeColor(asset.file_type)}`}>
            {asset.file_type}
          </span>
          <span className="text-xs text-gray-500">{formatFileSize(asset.file_size)}</span>
        </div>
        {asset.width && asset.height && (
          <p className="text-xs text-gray-500 mt-1">
            {asset.width} × {asset.height}
          </p>
        )}
      </div>
    </div>
  );
}

interface AssetListItemProps {
  asset: Asset;
  onRename: (assetId: string, newName: string) => void;
  onDelete: (assetId: string) => void;
  onMove: (assetId: string) => void;
  onPreview: (asset: Asset) => void;
}

export function AssetListItem({
  asset,
  onRename,
  onDelete,
  onMove,
  onPreview,
}: AssetListItemProps) {
  const getIcon = () => {
    switch (asset.file_type) {
      case 'image':
        return <Image size={20} weight="duotone" />;
      case 'video':
        return <Video size={20} weight="duotone" />;
      case 'font':
        return <TextT size={20} weight="duotone" />;
      case 'audio':
        return <MusicNote size={20} weight="duotone" />;
      default:
        return <File size={20} weight="duotone" />;
    }
  };

  const copyToClipboard = async (text: string, type: string) => {
    await navigator.clipboard.writeText(text);
    toast.success(`${type} copied to clipboard!`);
  };

  return (
    <div className="flex items-center gap-3 px-4 py-3 bg-[var(--surface)] rounded-lg border border-white/10 hover:border-white/20 transition-all group">
      {/* Thumbnail/Icon */}
      <div
        className="w-12 h-12 rounded-lg bg-black/20 flex items-center justify-center flex-shrink-0 cursor-pointer overflow-hidden"
        onClick={() => onPreview(asset)}
      >
        {asset.file_type === 'image' ? (
          <img
            src={getAuthenticatedAssetUrl(asset.url)}
            alt={asset.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="text-gray-400">{getIcon()}</div>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-200 truncate" title={asset.filename}>
          {asset.filename}
        </p>
        <div className="flex items-center gap-3 mt-1">
          <span className={`text-xs px-2 py-0.5 rounded ${getFileTypeBadgeColor(asset.file_type)}`}>
            {asset.file_type}
          </span>
          <span className="text-xs text-gray-500">{formatFileSize(asset.file_size)}</span>
          {asset.width && asset.height && (
            <span className="text-xs text-gray-500">
              {asset.width} × {asset.height}
            </span>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => copyToClipboard(asset.file_path, 'Path')}
          className="p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400 hover:text-gray-200"
          title="Copy path"
        >
          <Copy size={18} weight="bold" />
        </button>
        <button
          onClick={() => onMove(asset.id)}
          className="p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400 hover:text-gray-200"
          title="Move"
        >
          <FolderOpen size={18} weight="bold" />
        </button>
        <button
          onClick={() => onRename(asset.id, asset.filename)}
          className="p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400 hover:text-gray-200"
          title="Rename"
        >
          <PencilSimple size={18} weight="bold" />
        </button>
        <button
          onClick={() => onDelete(asset.id)}
          className="p-2 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors"
          title="Delete"
        >
          <Trash size={18} weight="bold" />
        </button>
      </div>
    </div>
  );
}
