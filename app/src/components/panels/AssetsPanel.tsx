import { useState, useEffect } from 'react';
import { UploadSimple, GridFour, ListBullets, MagnifyingGlass, Plus, X, FolderOpen, List } from '@phosphor-icons/react';
import { assetsApi } from '../../lib/api';
import type { Asset, FrameworkType } from '../../types/assets';
import { DIRECTORY_PRESETS, getAuthenticatedAssetUrl } from '../../types/assets';
import DirectoryTree from './assets/DirectoryTree';
import { AssetCard, AssetListItem } from './assets/AssetComponents';
import AssetUploadZone from './assets/AssetUploadZone';
import toast from 'react-hot-toast';
import { ConfirmDialog } from '../modals/ConfirmDialog';
import { fileEvents } from '../../utils/fileEvents';

interface AssetsPanelProps {
  projectSlug: string;  // Changed from projectId to projectSlug
}

export function AssetsPanel({ projectSlug }: AssetsPanelProps) {
  const [directories, setDirectories] = useState<string[]>([]);
  const [selectedDirectory, setSelectedDirectory] = useState<string | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [allAssets, setAllAssets] = useState<Asset[]>([]);  // All assets across all directories
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [searchQuery, setSearchQuery] = useState('');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showMoveModal, setShowMoveModal] = useState(false);
  const [showRenameModal, setShowRenameModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [previewAsset, setPreviewAsset] = useState<Asset | null>(null);
  const [loading, setLoading] = useState(true);
  const [newFilename, setNewFilename] = useState('');
  const [targetDirectory, setTargetDirectory] = useState('');
  const [showDirectorySidebar, setShowDirectorySidebar] = useState(false);
  const framework: FrameworkType = 'generic'; // Can be made dynamic later with framework detection

  // Compute asset counts per directory
  const assetCounts = allAssets.reduce((acc, asset) => {
    acc[asset.directory] = (acc[asset.directory] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  // Load directories on mount
  useEffect(() => {
    const init = async () => {
      await Promise.all([loadDirectories(), loadAllAssets()]);
      setLoading(false);
    };
    init();
  }, [projectSlug]);

  // Load assets when directory changes
  useEffect(() => {
    if (selectedDirectory) {
      loadAssets(selectedDirectory);
    } else {
      setAssets([]);
      setLoading(false);
    }
  }, [selectedDirectory]);

  const loadDirectories = async () => {
    try {
      const response = await assetsApi.listDirectories(projectSlug);
      const dirs = response.directories || [];
      setDirectories(dirs);

      // Auto-select first directory if available
      if (dirs.length > 0 && !selectedDirectory) {
        setSelectedDirectory(dirs[0]);
      }
    } catch (error) {
      console.error('Failed to load directories:', error);
      toast.error('Failed to load directories');
    }
  };

  const loadAllAssets = async () => {
    try {
      // Load all assets without directory filter to get counts
      const response = await assetsApi.listAssets(projectSlug);
      setAllAssets(response.assets || []);
    } catch (error) {
      console.error('Failed to load all assets:', error);
    }
  };

  const loadAssets = async (directory: string) => {
    try {
      setLoading(true);
      const response = await assetsApi.listAssets(projectSlug, directory.replace('/', ''));
      setAssets(response.assets || []);
      setLoading(false);
    } catch (error) {
      console.error('Failed to load assets:', error);
      toast.error('Failed to load assets');
      setLoading(false);
    }
  };

  const handleCreateDirectory = async (path: string) => {
    if (!path.trim()) {
      toast.error('Directory path cannot be empty');
      return;
    }

    try {
      await assetsApi.createDirectory(projectSlug, path.trim());
      toast.success(`Directory /${path} created successfully`);
      await loadDirectories();
      // Auto-select the newly created directory
      setSelectedDirectory(`/${path.trim()}`);
    } catch (error: any) {
      console.error('Failed to create directory:', error);
      toast.error(error.response?.data?.detail || 'Failed to create directory');
    }
  };

  const handleUpload = async (file: File, onProgress: (progress: number) => void) => {
    if (!selectedDirectory) {
      toast.error('Please select a directory first');
      throw new Error('No directory selected');
    }

    try {
      await assetsApi.uploadAsset(
        projectSlug,
        file,
        selectedDirectory.replace('/', ''),
        onProgress
      );
      toast.success(`${file.name} uploaded successfully`);
      loadAssets(selectedDirectory);
      loadAllAssets();  // Refresh counts

      // Notify other components about file change
      const filePath = `${selectedDirectory}/${file.name}`.replace('//', '/');
      fileEvents.emit('file-created', filePath);
    } catch (error: any) {
      console.error('Upload failed:', error);
      toast.error(error.response?.data?.detail || 'Upload failed');
      throw error;
    }
  };

  const handleRename = async () => {
    if (!selectedAsset || !newFilename.trim()) {
      toast.error('Filename cannot be empty');
      return;
    }

    try {
      await assetsApi.renameAsset(projectSlug, selectedAsset.id, newFilename.trim());
      toast.success('Asset renamed successfully');
      setShowRenameModal(false);
      setNewFilename('');
      setSelectedAsset(null);
      if (selectedDirectory) {
        loadAssets(selectedDirectory);
      }

      // Notify other components about file change
      fileEvents.emit('file-updated', selectedAsset.file_path);
    } catch (error: any) {
      console.error('Failed to rename asset:', error);
      toast.error(error.response?.data?.detail || 'Failed to rename asset');
    }
  };

  const handleDelete = async () => {
    if (!selectedAsset) return;

    const deletedFilePath = selectedAsset.file_path;

    try {
      await assetsApi.deleteAsset(projectSlug, selectedAsset.id);
      toast.success('Asset deleted successfully');
      setShowDeleteConfirm(false);
      setSelectedAsset(null);
      if (selectedDirectory) {
        loadAssets(selectedDirectory);
      }
      loadAllAssets();  // Refresh counts

      // Notify other components about file deletion
      fileEvents.emit('file-deleted', deletedFilePath);
    } catch (error: any) {
      console.error('Failed to delete asset:', error);
      toast.error(error.response?.data?.detail || 'Failed to delete asset');
    }
  };

  const handleMove = async () => {
    if (!selectedAsset || !targetDirectory.trim()) {
      toast.error('Please select a target directory');
      return;
    }

    try {
      await assetsApi.moveAsset(projectSlug, selectedAsset.id, targetDirectory.trim());
      toast.success('Asset moved successfully');
      setShowMoveModal(false);
      setTargetDirectory('');
      setSelectedAsset(null);
      if (selectedDirectory) {
        loadAssets(selectedDirectory);
      }
      loadAllAssets();  // Refresh counts

      // Notify other components about file change (moved files are like updates)
      fileEvents.emit('file-updated', selectedAsset.file_path);
    } catch (error: any) {
      console.error('Failed to move asset:', error);
      toast.error(error.response?.data?.detail || 'Failed to move asset');
    }
  };

  const filteredAssets = assets.filter((asset) =>
    asset.filename.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading && directories.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-gray-400">
          <div className="animate-spin w-8 h-8 border-2 border-orange-500 border-t-transparent rounded-full mx-auto mb-4"></div>
          <p>Loading assets...</p>
        </div>
      </div>
    );
  }

  // Empty state - no directories yet - Show minimal UI with directory tree
  if (directories.length === 0) {
    return (
      <div className="h-full flex flex-col bg-[var(--background)]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 md:px-6 py-3 md:py-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            {/* Mobile Directory Toggle */}
            <button
              onClick={() => setShowDirectorySidebar(!showDirectorySidebar)}
              className="md:hidden p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400"
              title="Toggle directories"
            >
              <List size={20} weight="bold" />
            </button>
            <h2 className="text-base md:text-lg font-bold text-white">Assets</h2>
          </div>
          <div className="text-xs md:text-sm text-gray-500">No directories yet</div>
        </div>

        <div className="flex-1 flex overflow-hidden relative">
          {/* Directory Tree Sidebar - Desktop always visible, Mobile toggleable */}
          <div
            className={`
              ${showDirectorySidebar ? 'absolute inset-y-0 left-0 z-10' : 'hidden'}
              md:relative md:block
              w-64 border-r border-white/10 overflow-y-auto
              bg-[var(--surface)] md:bg-transparent
            `}
          >
            {/* Mobile Close Button */}
            <div className="md:hidden flex items-center justify-between px-3 py-2 border-b border-white/10">
              <h3 className="text-sm font-semibold text-gray-300">Directories</h3>
              <button
                onClick={() => setShowDirectorySidebar(false)}
                className="p-1 rounded hover:bg-white/10 transition-colors text-gray-400"
              >
                <X size={18} weight="bold" />
              </button>
            </div>

            <DirectoryTree
              directories={directories}
              selectedDirectory={selectedDirectory}
              onDirectorySelect={(dir) => {
                setSelectedDirectory(dir);
                setShowDirectorySidebar(false);
              }}
              onCreateDirectory={handleCreateDirectory}
              assetCounts={assetCounts}
            />
          </div>

          {/* Overlay for mobile when sidebar is open */}
          {showDirectorySidebar && (
            <div
              className="md:hidden absolute inset-0 bg-black/60 z-[9]"
              onClick={() => setShowDirectorySidebar(false)}
            />
          )}

          {/* Empty State */}
          <div className="flex-1 flex items-center justify-center p-4 md:p-8">
            <div className="text-center max-w-md">
              <div className="mb-6 flex justify-center">
                <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-orange-500/20 to-blue-500/20 flex items-center justify-center backdrop-blur-sm border border-white/15">
                  <FolderOpen size={48} weight="duotone" className="text-orange-500" />
                </div>
              </div>
              <h3 className="text-2xl font-bold text-white mb-3">Create Your First Directory</h3>
              <p className="text-gray-400 leading-relaxed mb-6">
                Click the <Plus size={16} weight="bold" className="inline mx-1" /> button in the sidebar to create a directory, or choose a common preset below.
              </p>

              {/* Framework Presets */}
              <div className="mb-6">
                <p className="text-sm text-gray-500 mb-3">Quick start:</p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {DIRECTORY_PRESETS[framework].map((dir) => (
                    <button
                      key={dir}
                      onClick={() => handleCreateDirectory(dir.replace('/', ''))}
                      className="px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-lg text-sm text-gray-300 border border-white/10 hover:border-orange-500/50 transition-all"
                    >
                      {dir}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[var(--background)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 md:px-6 py-3 md:py-4 border-b border-white/10">
        <div className="flex items-center gap-2 md:gap-4 flex-1">
          {/* Mobile Directory Toggle */}
          <button
            onClick={() => setShowDirectorySidebar(!showDirectorySidebar)}
            className="md:hidden p-2 hover:bg-white/10 rounded-lg transition-colors text-gray-400"
            title="Toggle directories"
          >
            <List size={20} weight="bold" />
          </button>

          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass
              size={18}
              weight="bold"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
            />
            <input
              type="text"
              placeholder="Search assets..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-orange-500/50"
            />
          </div>

          {/* View Toggle - Hidden on small mobile */}
          <div className="hidden sm:flex items-center gap-1 bg-white/5 rounded-lg p-1">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 rounded transition-colors ${
                viewMode === 'grid'
                  ? 'bg-orange-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <GridFour size={18} weight="bold" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 rounded transition-colors ${
                viewMode === 'list'
                  ? 'bg-orange-500 text-white'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <ListBullets size={18} weight="bold" />
            </button>
          </div>
        </div>

        {/* Upload Button */}
        <button
          onClick={() => {
            if (!selectedDirectory) {
              toast.error('Please select a directory first');
              return;
            }
            setShowUploadModal(true);
          }}
          className="px-3 md:px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-medium transition-colors flex items-center gap-2 text-sm md:text-base"
        >
          <UploadSimple size={18} className="md:w-5 md:h-5" weight="bold" />
          <span className="hidden sm:inline">Upload</span>
        </button>
      </div>

      {/* Main Content - Three Panel Layout */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Directory Tree (Left Sidebar) - Desktop always visible, Mobile toggleable */}
        <div
          className={`
            ${showDirectorySidebar ? 'absolute inset-y-0 left-0 z-10' : 'hidden'}
            md:relative md:block
            w-64 md:w-64 border-r border-white/10 overflow-y-auto
            bg-[var(--surface)] md:bg-transparent
          `}
        >
          {/* Mobile Close Button */}
          <div className="md:hidden flex items-center justify-between px-3 py-2 border-b border-white/10">
            <h3 className="text-sm font-semibold text-gray-300">Directories</h3>
            <button
              onClick={() => setShowDirectorySidebar(false)}
              className="p-1 rounded hover:bg-white/10 transition-colors text-gray-400"
            >
              <X size={18} weight="bold" />
            </button>
          </div>

          <DirectoryTree
            directories={directories}
            selectedDirectory={selectedDirectory}
            onDirectorySelect={(dir) => {
              setSelectedDirectory(dir);
              setShowDirectorySidebar(false); // Close sidebar on mobile after selection
            }}
            onCreateDirectory={handleCreateDirectory}
            assetCounts={assetCounts}
          />
        </div>

        {/* Overlay for mobile when sidebar is open */}
        {showDirectorySidebar && (
          <div
            className="md:hidden absolute inset-0 bg-black/60 z-[9]"
            onClick={() => setShowDirectorySidebar(false)}
          />
        )}

        {/* Assets Grid/List (Main Area) */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6">
          {selectedDirectory ? (
            <>
              {/* Directory Header */}
              <div className="mb-4">
                <h2 className="text-lg font-semibold text-white">{selectedDirectory}</h2>
                <p className="text-sm text-gray-500">
                  {filteredAssets.length} {filteredAssets.length === 1 ? 'asset' : 'assets'}
                </p>
              </div>

              {/* Assets Grid/List */}
              {filteredAssets.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-center">
                  <div>
                    <div className="mb-4 flex justify-center">
                      <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-orange-500/10 to-blue-500/10 flex items-center justify-center border border-white/10">
                        <UploadSimple size={40} weight="duotone" className="text-gray-500" />
                      </div>
                    </div>
                    <h4 className="text-lg font-semibold text-white mb-2">
                      {searchQuery ? 'No assets match your search' : `Ready to add assets to ${selectedDirectory}`}
                    </h4>
                    <p className="text-gray-500 mb-4 text-sm">
                      {searchQuery
                        ? 'Try a different search term'
                        : 'Upload images, videos, fonts, or other files (max 20MB each)'}
                    </p>
                    {!searchQuery && (
                      <button
                        onClick={() => setShowUploadModal(true)}
                        className="px-6 py-2.5 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-medium transition-colors inline-flex items-center gap-2"
                      >
                        <UploadSimple size={20} weight="bold" />
                        Upload Assets
                      </button>
                    )}
                  </div>
                </div>
              ) : viewMode === 'grid' ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                  {filteredAssets.map((asset) => (
                    <AssetCard
                      key={asset.id}
                      asset={asset}
                      onRename={(_id, name) => {
                        setSelectedAsset(asset);
                        setNewFilename(name);
                        setShowRenameModal(true);
                      }}
                      onDelete={() => {
                        setSelectedAsset(asset);
                        setShowDeleteConfirm(true);
                      }}
                      onMove={() => {
                        setSelectedAsset(asset);
                        setShowMoveModal(true);
                      }}
                      onPreview={(asset) => setPreviewAsset(asset)}
                    />
                  ))}
                </div>
              ) : (
                <div className="space-y-2">
                  {filteredAssets.map((asset) => (
                    <AssetListItem
                      key={asset.id}
                      asset={asset}
                      onRename={(_id, name) => {
                        setSelectedAsset(asset);
                        setNewFilename(name);
                        setShowRenameModal(true);
                      }}
                      onDelete={() => {
                        setSelectedAsset(asset);
                        setShowDeleteConfirm(true);
                      }}
                      onMove={() => {
                        setSelectedAsset(asset);
                        setShowMoveModal(true);
                      }}
                      onPreview={(asset) => setPreviewAsset(asset)}
                    />
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              <p>Select a directory to view assets</p>
            </div>
          )}
        </div>
      </div>

      {/* Upload Modal */}
      {showUploadModal && selectedDirectory && (
        <AssetUploadZone
          onUpload={handleUpload}
          onClose={() => setShowUploadModal(false)}
        />
      )}

      {/* Rename Modal */}
      {showRenameModal && selectedAsset && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--surface)] rounded-2xl border border-white/10 max-w-md w-full p-6">
            <h2 className="text-xl font-bold text-white mb-4">Rename Asset</h2>
            <input
              type="text"
              value={newFilename}
              onChange={(e) => setNewFilename(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-gray-200 focus:outline-none focus:border-orange-500/50 mb-4"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename();
              }}
            />
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowRenameModal(false);
                  setNewFilename('');
                  setSelectedAsset(null);
                }}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleRename}
                className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg transition-colors"
              >
                Rename
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move Modal */}
      {showMoveModal && selectedAsset && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--surface)] rounded-2xl border border-white/10 max-w-md w-full p-6">
            <h2 className="text-xl font-bold text-white mb-4">Move Asset</h2>
            <p className="text-gray-400 text-sm mb-4">Select target directory:</p>
            <select
              value={targetDirectory}
              onChange={(e) => setTargetDirectory(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-gray-200 focus:outline-none focus:border-orange-500/50 mb-4"
            >
              <option value="">-- Select Directory --</option>
              {directories
                .filter((dir) => dir !== selectedAsset.directory)
                .map((dir) => (
                  <option key={dir} value={dir.replace('/', '')}>
                    {dir}
                  </option>
                ))}
            </select>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowMoveModal(false);
                  setTargetDirectory('');
                  setSelectedAsset(null);
                }}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleMove}
                className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg transition-colors"
              >
                Move
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      <ConfirmDialog
        isOpen={showDeleteConfirm && !!selectedAsset}
        title="Delete Asset"
        message={`Are you sure you want to delete "${selectedAsset?.filename}"? This action cannot be undone.`}
        variant="danger"
        confirmText="Delete"
        onConfirm={handleDelete}
        onClose={() => {
          setShowDeleteConfirm(false);
          setSelectedAsset(null);
        }}
      />

      {/* Image Preview Modal */}
      {previewAsset && previewAsset.file_type === 'image' && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setPreviewAsset(null)}
        >
          <div className="relative max-w-5xl max-h-[90vh]">
            <button
              onClick={() => setPreviewAsset(null)}
              className="absolute -top-12 right-0 p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white"
            >
              <X size={24} weight="bold" />
            </button>
            <img
              src={getAuthenticatedAssetUrl(previewAsset.url)}
              alt={previewAsset.filename}
              className="max-w-full max-h-[90vh] rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
            <div className="mt-4 text-center text-white">
              <p className="font-medium">{previewAsset.filename}</p>
              {previewAsset.width && previewAsset.height && (
                <p className="text-sm text-gray-400 mt-1">
                  {previewAsset.width} × {previewAsset.height}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
