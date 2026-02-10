import { useState, useEffect } from 'react';
import { Settings, Monitor, Check, Layers, Package } from 'lucide-react';
import { ChatCentered } from '@phosphor-icons/react';
import { projectsApi } from '../../lib/api';
import { useChatPosition, type ChatPosition } from '../../contexts/ChatPositionContext';
import { ExportTemplateModal } from '../modals/ExportTemplateModal';
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
  const [savingChatPos, setSavingChatPos] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const { chatPosition, setChatPosition } = useChatPosition();

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
    } catch (error: unknown) {
      console.error('Failed to update settings:', error);
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || 'Failed to update settings');
    } finally {
      setSaving(false);
    }
  };

  const handleChatPositionChange = async (position: ChatPosition) => {
    setSavingChatPos(true);
    try {
      await setChatPosition(position);
      toast.success(`Chat moved to ${position}`);
    } catch {
      toast.error('Failed to update chat position');
    } finally {
      setSavingChatPos(false);
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
            <p className="text-xs text-[var(--text)]/60">Customize your development environment</p>
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
                  ${
                    previewMode === 'normal'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`p-2 rounded-lg ${previewMode === 'normal' ? 'bg-orange-500/20' : 'bg-white/10'}`}
                  >
                    <Monitor
                      size={20}
                      className={
                        previewMode === 'normal' ? 'text-orange-400' : 'text-[var(--text)]/60'
                      }
                    />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-[var(--text)]">Normal Mode</span>
                      {previewMode === 'normal' && <Check size={16} className="text-orange-400" />}
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
                  ${
                    previewMode === 'browser-tabs'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`p-2 rounded-lg ${previewMode === 'browser-tabs' ? 'bg-orange-500/20' : 'bg-white/10'}`}
                  >
                    <Layers
                      size={20}
                      className={
                        previewMode === 'browser-tabs' ? 'text-orange-400' : 'text-[var(--text)]/60'
                      }
                    />
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
                💡 Browser tabs mode allows you to open multiple pages of your application
                simultaneously. Refresh the page to activate this feature.
              </p>
            </div>
          )}
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Chat Position Setting */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <ChatCentered size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Chat Position</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Choose where the chat panel appears in the builder
            </p>

            <div className="grid grid-cols-3 gap-3">
              {/* Left Position */}
              <button
                onClick={() => handleChatPositionChange('left')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'left'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - chat on left */}
                  <div className="flex w-full h-8 rounded overflow-hidden border border-[var(--text)]/20">
                    <div
                      className={`w-1/3 ${chatPosition === 'left' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                    <div className="flex-1 bg-[var(--surface)]" />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Left</span>
                </div>
              </button>

              {/* Center Position */}
              <button
                onClick={() => handleChatPositionChange('center')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'center'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - floating chat in center */}
                  <div className="relative w-full h-8 rounded overflow-hidden border border-[var(--text)]/20 bg-[var(--surface)]">
                    <div
                      className={`absolute bottom-0 left-1/2 -translate-x-1/2 w-1/2 h-3 rounded-t ${chatPosition === 'center' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Center</span>
                </div>
              </button>

              {/* Right Position */}
              <button
                onClick={() => handleChatPositionChange('right')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'right'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - chat on right */}
                  <div className="flex w-full h-8 rounded overflow-hidden border border-[var(--text)]/20">
                    <div className="flex-1 bg-[var(--surface)]" />
                    <div
                      className={`w-1/3 ${chatPosition === 'right' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Right</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Template Export */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Package size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Template Export</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Share this project as a reusable template on the marketplace
            </p>

            <button
              onClick={() => setShowExportModal(true)}
              className="w-full p-4 rounded-lg border-2 border-[var(--text)]/15 bg-white/5 hover:border-[var(--primary)]/50 hover:bg-[var(--primary)]/5 transition-all cursor-pointer text-left"
            >
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-white/10">
                  <Package size={20} className="text-[var(--text)]/60" />
                </div>
                <div className="flex-1">
                  <span className="font-medium text-[var(--text)]">Export as Template</span>
                  <p className="text-xs text-[var(--text)]/60 mt-1">
                    Package your project files into a shareable template archive
                  </p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <ExportTemplateModal
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        onSuccess={() => {}}
        projectSlug={projectSlug}
      />
    </div>
  );
}
