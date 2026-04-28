import { useState, useEffect, useCallback, useMemo } from 'react';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import { Zap, Trash2, Edit3 } from 'lucide-react';
import { channelsApi, type ChannelConfig } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { staggerContainer, staggerItem } from '../../components/cards';
import { CHANNEL_PLATFORMS, getPlatform, type ChannelPlatform } from '../../components/channels/platforms';
import { ChannelTile } from '../../components/channels/ChannelTile';
import { ChannelSetupDrawer } from '../../components/channels/ChannelSetupDrawer';

/**
 * Library → Channels page. Renders a grid of platform tiles with native
 * preview cards (show-not-tell), plus a list of currently connected
 * channels for management. Replaces the form-heavy
 * `pages/settings/ChannelsSettings.tsx` (deleted) per the same pattern that
 * moved Connectors out of Settings (#307).
 */
export default function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeDrawer, setActiveDrawer] = useState<{
    platform: ChannelPlatform;
    existing?: ChannelConfig;
  } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ChannelConfig | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadChannels = useCallback(async () => {
    try {
      const list = await channelsApi.list();
      setChannels(list);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail || 'Failed to load channels');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadChannels();
  }, [loadChannels]);

  const grouped = useMemo(() => {
    const map: Record<string, ChannelConfig[]> = {};
    for (const ch of channels) {
      const key = ch.channel_type.toLowerCase();
      if (!map[key]) map[key] = [];
      map[key].push(ch);
    }
    return map;
  }, [channels]);

  const handleTest = async (channel: ChannelConfig) => {
    setBusyId(channel.id);
    try {
      await channelsApi.test(channel.id, 'self');
      toast.success(`Test message sent via ${channel.name}`);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail || 'Test failed');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    const ch = confirmDelete;
    setConfirmDelete(null);
    setBusyId(ch.id);
    try {
      await channelsApi.deactivate(ch.id);
      toast.success(`${ch.name} disconnected`);
      await loadChannels();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail || 'Failed to disconnect channel');
    } finally {
      setBusyId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <LoadingSpinner message="Loading channels…" size={60} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        {/* Header */}
        <header className="mb-6">
          <h1 className="text-lg font-semibold text-[var(--text)]">Channels</h1>
          <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-[var(--text-muted)]">
            Send approvals, deliver runs, and trigger automations from any messaging surface
            your team already lives in. Click a tile to connect.
          </p>
        </header>

        {/* Tile grid */}
        <motion.div
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          {CHANNEL_PLATFORMS.map((platform) => (
            <motion.div key={platform.key} variants={staggerItem}>
              <ChannelTile
                platform={platform}
                connections={grouped[platform.key] || []}
                onClick={() =>
                  setActiveDrawer({
                    platform,
                    existing: (grouped[platform.key] || []).find((c) => c.is_active),
                  })
                }
              />
            </motion.div>
          ))}
        </motion.div>

        {/* Connected channels list */}
        {channels.length > 0 && (
          <section className="mt-8">
            <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Connected channels
            </h2>
            <div className="overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]">
              <ul className="divide-y divide-[var(--border)]">
                {channels.map((ch) => {
                  const platform = getPlatform(ch.channel_type);
                  return (
                    <li
                      key={ch.id}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface-hover)]"
                    >
                      <div
                        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md"
                        style={{
                          backgroundColor: platform ? `${platform.brandColor}1a` : 'var(--bg)',
                        }}
                        aria-hidden="true"
                      >
                        {platform && (
                          <span
                            className="block h-4 w-4"
                            style={{
                              backgroundColor: platform.brandColor,
                              maskImage: `url("${platform.iconUrl}")`,
                              WebkitMaskImage: `url("${platform.iconUrl}")`,
                              maskRepeat: 'no-repeat',
                              WebkitMaskRepeat: 'no-repeat',
                              maskSize: 'contain',
                              WebkitMaskSize: 'contain',
                              maskPosition: 'center',
                              WebkitMaskPosition: 'center',
                            }}
                          />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-[var(--text)]">{ch.name}</span>
                          <span
                            className={`rounded px-1.5 py-px text-[9px] font-medium uppercase tracking-wide ${
                              ch.is_active
                                ? 'bg-emerald-500/10 text-emerald-500'
                                : 'bg-amber-500/10 text-amber-500'
                            }`}
                          >
                            {ch.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <p className="text-[11px] capitalize text-[var(--text-muted)]">
                          {platform?.name || ch.channel_type}
                          {ch.webhook_url && (
                            <>
                              <span className="mx-1.5 text-[var(--text-subtle)]">·</span>
                              <span className="font-mono text-[10.5px]">{ch.webhook_url}</span>
                            </>
                          )}
                        </p>
                      </div>
                      <div className="flex flex-shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => handleTest(ch)}
                          disabled={busyId === ch.id}
                          className="btn btn-sm flex items-center gap-1 disabled:opacity-50"
                          aria-label={`Test ${ch.name}`}
                        >
                          <Zap size={12} />
                          Test
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            platform &&
                            setActiveDrawer({
                              platform,
                              existing: ch,
                            })
                          }
                          disabled={!platform}
                          className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-30"
                          aria-label={`Edit ${ch.name}`}
                          title="Edit"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(ch)}
                          disabled={busyId === ch.id}
                          className="rounded p-1.5 text-[var(--text-muted)] hover:bg-red-500/10 hover:text-red-500 disabled:opacity-50"
                          aria-label={`Disconnect ${ch.name}`}
                          title="Disconnect"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>
        )}
      </div>

      {/* Drawer */}
      {activeDrawer && (
        <ChannelSetupDrawer
          open
          platform={activeDrawer.platform}
          existing={activeDrawer.existing}
          onClose={() => setActiveDrawer(null)}
          onSaved={loadChannels}
        />
      )}

      {/* Disconnect confirmation */}
      <ConfirmDialog
        isOpen={Boolean(confirmDelete)}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title={confirmDelete ? `Disconnect "${confirmDelete.name}"` : 'Disconnect channel'}
        message={
          confirmDelete
            ? `This deactivates the ${confirmDelete.channel_type} channel. Automations targeting it will stop delivering until reconnected.`
            : ''
        }
        confirmText="Disconnect"
        variant="danger"
      />
    </div>
  );
}
