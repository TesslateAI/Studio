import { UploadCloud } from 'lucide-react';

interface AssetsPanelProps {
  projectId: number;
  onLockToggle?: (locked: boolean) => void;
}

export function AssetsPanel({ projectId, onLockToggle }: AssetsPanelProps) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="mb-6 flex justify-center">
          <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-[var(--primary)]/20 to-blue-500/20 flex items-center justify-center backdrop-blur-sm border border-[var(--text)]/15">
            <UploadCloud className="w-12 h-12 text-[var(--primary)]" />
          </div>
        </div>
        <h3 className="text-2xl font-bold text-[var(--text)] mb-3">
          Coming Soon
        </h3>
        <p className="text-gray-400 leading-relaxed">
          Upload and manage images, videos, fonts, and other assets for your project.
          Drag and drop support, asset optimization, and CDN integration coming soon.
        </p>
        <div className="mt-8 pt-8 border-t border-[var(--text)]/15">
          <p className="text-sm text-gray-500">
            Stay tuned for updates!
          </p>
        </div>
      </div>
    </div>
  );
}
