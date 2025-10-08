import { useState } from 'react';
import { UploadCloud, Image as ImageIcon, Lock, LockOpen } from 'lucide-react';

interface AssetsPanelProps {
  projectId: number;
  onLockToggle?: (locked: boolean) => void;
}

export function AssetsPanel({ projectId, onLockToggle }: AssetsPanelProps) {
  const [locked, setLocked] = useState(false);

  const handleLockToggle = () => {
    const newLocked = !locked;
    setLocked(newLocked);
    onLockToggle?.(newLocked);
  };

  const handleUpload = () => {
    alert('Upload assets feature coming soon!');
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* Upload Button */}
      <div className="panel-section p-6 border-b border-white/5">
        <button
          onClick={handleUpload}
          className="w-full py-3 bg-[var(--primary)] hover:bg-[#ff8533] rounded-lg font-semibold transition-all flex items-center justify-center gap-2 text-white"
        >
          <UploadCloud className="w-5 h-5" />
          Upload Assets
        </button>
      </div>

      {/* Asset Grid */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">IMAGES</h3>
        <div className="asset-grid grid grid-cols-3 gap-3">
          <div className="asset-item aspect-square bg-white/5 border border-white/10 rounded-xl cursor-pointer transition-all hover:bg-white/8 hover:border-[var(--primary)] hover:scale-105 flex items-center justify-center text-gray-600">
            <ImageIcon className="w-8 h-8" />
          </div>
          <div className="asset-item aspect-square bg-white/5 border border-white/10 rounded-xl cursor-pointer transition-all hover:bg-white/8 hover:border-[var(--primary)] hover:scale-105 flex items-center justify-center text-gray-600">
            <ImageIcon className="w-8 h-8" />
          </div>
        </div>
      </div>

      {/* Lock Button */}
      <div className="panel-section p-6">
        <button
          onClick={handleLockToggle}
          className="w-full py-3 bg-white/5 hover:bg-white/8 border border-white/10 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          {locked ? <Lock className="w-4 h-4" /> : <LockOpen className="w-4 h-4" />}
          {locked ? 'Panel Locked' : 'Lock Panel'}
        </button>
      </div>
    </div>
  );
}
