import { useState, useEffect } from 'react';
import { Settings, Monitor, Check, Layers } from 'lucide-react';
import { projectsApi } from '../../lib/api';
import toast from 'react-hot-toast';

interface SettingsPanelProps {
  projectSlug: string;
  onLockToggle?: (locked: boolean) => void;
}

type PreviewMode = 'normal' | 'browser-tabs';

export function SettingsPanel({ projectSlug }: SettingsPanelProps) {
  const [previewMode, setPreviewMode] = useState<PreviewMode>('normal');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadSettings();
  }, [projectSlug]);

  const loadSettings = async () => {
    try {
      const data = await projectsApi.getSettings(projectSlug);
      const settings = data.settings || {};
      setPreviewMode(settings.preview_mode || 'normal');
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const handlePreviewModeChange = async (mode: PreviewMode) => {
    setSaving(true);
    try {
      await projectsApi.updateSettings(projectSlug, { preview_mode: mode });
      setPreviewMode(mode);
      toast.success('Preview mode updated! Refresh the page to see changes.');
    } catch (error: any) {
      console.error('Failed to update settings:', error);
      toast.error(error.response?.data?.detail || 'Failed to update settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-[var(--text)]/60">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="panel-section p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Settings size={20} className="text-purple-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--text)]">Project Settings</h2>
            <p className="text-xs text-[var(--text)]/60">
              Customize your development environment
            </p>
          </div>
        </div>

        {/* Preview Mode Setting */}
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-[var(--text)] mb-3">Preview Mode</h3>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Choose how the preview window displays your application
            </p>

            <div className="space-y-3">
              {/* Normal Mode */}
              <button
                onClick={() => handlePreviewModeChange('normal')}
                disabled={saving}
                className={`
                  w-full p-4 rounded-lg border-2 transition-all text-left
                  ${previewMode === 'normal'
                    ? 'border-orange-500 bg-orange-500/10'
                    : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div className={`p-2 rounded-lg ${previewMode === 'normal' ? 'bg-orange-500/20' : 'bg-white/10'}`}>
                    <Monitor size={20} className={previewMode === 'normal' ? 'text-orange-400' : 'text-[var(--text)]/60'} />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-[var(--text)]">Normal Mode</span>
                      {previewMode === 'normal' && (
                        <Check size={16} className="text-orange-400" />
                      )}
                    </div>
                    <p className="text-xs text-[var(--text)]/60">
                      Simple preview window with basic browser controls
                    </p>
                  </div>
                </div>
              </button>

              {/* Browser Tabs Mode */}
              <button
                onClick={() => handlePreviewModeChange('browser-tabs')}
                disabled={saving}
                className={`
                  w-full p-4 rounded-lg border-2 transition-all text-left
                  ${previewMode === 'browser-tabs'
                    ? 'border-orange-500 bg-orange-500/10'
                    : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div className={`p-2 rounded-lg ${previewMode === 'browser-tabs' ? 'bg-orange-500/20' : 'bg-white/10'}`}>
                    <Layers size={20} className={previewMode === 'browser-tabs' ? 'text-orange-400' : 'text-[var(--text)]/60'} />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-[var(--text)]">Browser with Tabs</span>
                      {previewMode === 'browser-tabs' && (
                        <Check size={16} className="text-orange-400" />
                      )}
                    </div>
                    <p className="text-xs text-[var(--text)]/60">
                      Full browser experience with multiple tabs support
                    </p>
                  </div>
                </div>
              </button>
            </div>
          </div>

          {previewMode === 'browser-tabs' && (
            <div className="mt-4 p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
              <p className="text-xs text-blue-400">
                💡 Browser tabs mode allows you to open multiple pages of your application simultaneously.
                Refresh the page to activate this feature.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
