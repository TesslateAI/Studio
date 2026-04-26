/**
 * DestinationPicker — dropdown that selects a CommunicationDestination
 * (Phase 4 primitive) by id.
 *
 * The user's destinations are loaded once and grouped by their backing
 * ``ChannelConfig`` (e.g., "Slack — Acme Workspace > #standup, DM
 * Manav, …"). The top option opens an inline modal that creates a new
 * destination on top of an existing channel-config; if the user has no
 * channel configs at all, the modal links them out to /settings/channels
 * to set one up.
 *
 * The component owns no automation state — it just emits the selected
 * destination_id (UUID string) via ``onChange``. Empty string means "no
 * destination selected".
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, X } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import {
  channelsApi,
  communicationDestinationsApi,
  type ChannelConfig,
} from '../../../lib/api';
import type {
  CommunicationDestination,
  CommunicationDestinationCreate,
  CommunicationDestinationFormattingPolicy,
  CommunicationDestinationKind,
} from '../../../types/automations';

interface Props {
  /** The currently-selected destination id (or empty string for none). */
  value: string;
  onChange: (destinationId: string) => void;
  /**
   * When ``true`` adds a "— No destination —" option at the top so the
   * caller can clear the selection. Defaults to ``true``.
   */
  allowEmpty?: boolean;
  /** Optional placeholder when nothing is selected. */
  placeholder?: string;
}

const KIND_LABELS: Record<CommunicationDestinationKind, string> = {
  slack_channel: 'Slack channel',
  slack_dm: 'Slack DM',
  slack_thread: 'Slack thread',
  telegram_chat: 'Telegram chat',
  telegram_topic: 'Telegram topic',
  discord_channel: 'Discord channel',
  discord_dm: 'Discord DM',
  email: 'Email',
  webhook: 'Webhook',
  web_inbox: 'Web inbox',
};

const FORMATTING_POLICIES: CommunicationDestinationFormattingPolicy[] = [
  'text',
  'blocks',
  'rich',
  'code_block',
  'inline_table',
  'jinja_template',
];

/** Default destination kind for a given channel type. */
function defaultKindFor(channelType: string): CommunicationDestinationKind {
  switch (channelType) {
    case 'slack':
      return 'slack_channel';
    case 'telegram':
      return 'telegram_chat';
    case 'discord':
      return 'discord_channel';
    case 'whatsapp':
      return 'telegram_chat'; // closest semantic — still a chat
    default:
      return 'webhook';
  }
}

function kindOptionsFor(channelType: string): CommunicationDestinationKind[] {
  switch (channelType) {
    case 'slack':
      return ['slack_channel', 'slack_dm', 'slack_thread'];
    case 'telegram':
      return ['telegram_chat', 'telegram_topic'];
    case 'discord':
      return ['discord_channel', 'discord_dm'];
    default:
      return ['email', 'webhook', 'web_inbox'];
  }
}

export function DestinationPicker({
  value,
  onChange,
  allowEmpty = true,
  placeholder = 'Select a destination…',
}: Props) {
  const [destinations, setDestinations] = useState<CommunicationDestination[] | null>(null);
  const [channels, setChannels] = useState<ChannelConfig[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const reload = useCallback(async () => {
    setLoadError(null);
    try {
      const [dests, chans] = await Promise.all([
        communicationDestinationsApi.list(),
        channelsApi.list().catch(() => [] as ChannelConfig[]),
      ]);
      setDestinations(dests);
      setChannels(chans);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } }; message?: string }).response?.data
          ?.detail ||
        (err as { message?: string }).message ||
        'Failed to load destinations';
      setLoadError(typeof msg === 'string' ? msg : 'Failed to load destinations');
      // Keep the dropdown usable as a free-text fallback.
      setDestinations([]);
      setChannels([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Group destinations by their channel_config_id for nicer rendering. */
  const grouped = useMemo(() => {
    if (!destinations || !channels) return [];
    const channelById = new Map(channels.map((c) => [c.id, c]));
    const buckets = new Map<string, { channel: ChannelConfig | null; rows: CommunicationDestination[] }>();
    for (const dest of destinations) {
      const channel = channelById.get(dest.channel_config_id) ?? null;
      let bucket = buckets.get(dest.channel_config_id);
      if (!bucket) {
        bucket = { channel, rows: [] };
        buckets.set(dest.channel_config_id, bucket);
      }
      bucket.rows.push(dest);
    }
    return Array.from(buckets.values());
  }, [destinations, channels]);

  const handleCreated = (created: CommunicationDestination) => {
    setDestinations((prev) => (prev ? [created, ...prev] : [created]));
    onChange(created.id);
    setShowCreate(false);
    toast.success('Destination created');
  };

  return (
    <div className="space-y-1.5">
      <select
        value={value}
        onChange={(e) => {
          const next = e.target.value;
          if (next === '__create__') {
            setShowCreate(true);
            return;
          }
          onChange(next);
        }}
        className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
      >
        {allowEmpty && <option value="">— {placeholder} —</option>}
        {destinations === null && <option disabled>Loading destinations…</option>}
        {grouped.map(({ channel, rows }) => (
          <optgroup
            key={channel?.id ?? 'orphan'}
            label={
              channel
                ? `${channel.channel_type[0].toUpperCase()}${channel.channel_type.slice(1)} — ${channel.name}`
                : 'Other'
            }
          >
            {rows.map((dest) => (
              <option key={dest.id} value={dest.id}>
                {dest.name} · {KIND_LABELS[dest.kind] ?? dest.kind}
              </option>
            ))}
          </optgroup>
        ))}
        <option value="__create__">+ Create new destination…</option>
      </select>
      {loadError && (
        <p className="text-[10px] text-[var(--status-error)]">
          {loadError} — paste a destination UUID into the form below as a fallback.
        </p>
      )}
      {value && destinations !== null && destinations.find((d) => d.id === value) === undefined && (
        <p className="text-[10px] text-[var(--text-subtle)] font-mono">
          Selected: {value} (not in your destination list — manual id)
        </p>
      )}

      {showCreate && (
        <CreateDestinationModal
          channels={channels ?? []}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CreateDestinationModal — inline create flow.
// ---------------------------------------------------------------------------

interface ModalProps {
  channels: ChannelConfig[];
  onClose: () => void;
  onCreated: (created: CommunicationDestination) => void;
}

function CreateDestinationModal({ channels, onClose, onCreated }: ModalProps) {
  const activeChannels = useMemo(() => channels.filter((c) => c.is_active), [channels]);
  const [channelConfigId, setChannelConfigId] = useState<string>(activeChannels[0]?.id ?? '');
  const [kind, setKind] = useState<CommunicationDestinationKind>(() =>
    defaultKindFor(activeChannels[0]?.channel_type ?? '')
  );
  const [name, setName] = useState('');
  const [configText, setConfigText] = useState('{}');
  const [formattingPolicy, setFormattingPolicy] =
    useState<CommunicationDestinationFormattingPolicy>('text');
  const [submitting, setSubmitting] = useState(false);

  const selectedChannel = activeChannels.find((c) => c.id === channelConfigId) ?? null;
  const kindOptions = selectedChannel
    ? kindOptionsFor(selectedChannel.channel_type)
    : (Object.keys(KIND_LABELS) as CommunicationDestinationKind[]);

  // Re-snap the kind whenever the channel changes so we don't end up with
  // a slack-only kind picked under a Telegram channel.
  useEffect(() => {
    if (!selectedChannel) return;
    if (!kindOptions.includes(kind)) {
      setKind(kindOptions[0]);
    }
    // Intentionally only depends on selectedChannel — kindOptions is
    // derived from it on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChannel?.id]);

  const canSubmit = !!channelConfigId && name.trim().length > 0 && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    let config: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(configText.trim() || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('Config must be a JSON object.');
      }
      config = parsed as Record<string, unknown>;
    } catch (err) {
      toast.error(`Invalid config: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }

    const payload: CommunicationDestinationCreate = {
      channel_config_id: channelConfigId,
      kind,
      name: name.trim(),
      config,
      formatting_policy: formattingPolicy,
    };

    setSubmitting(true);
    try {
      const created = await communicationDestinationsApi.create(payload);
      onCreated(created);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to create destination';
      toast.error(typeof msg === 'string' ? msg : 'Failed to create destination');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Create destination"
    >
      <div
        className="w-full max-w-md rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <h3 className="text-xs font-semibold text-[var(--text)]">New destination</h3>
          <button
            onClick={onClose}
            className="btn btn-icon btn-sm"
            aria-label="Close"
            type="button"
          >
            <X className="w-3 h-3" />
          </button>
        </header>

        {activeChannels.length === 0 ? (
          <div className="px-4 py-6 space-y-3">
            <p className="text-xs text-[var(--text-muted)]">
              You don't have any active messaging channels yet. Add a Slack workspace,
              Telegram bot, or other channel first — then you can name destinations
              inside it.
            </p>
            <a
              href="/settings/channels"
              className="btn btn-sm btn-filled inline-flex items-center gap-1.5"
            >
              <Plus className="w-3 h-3" />
              Set up a channel
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="px-4 py-4 space-y-3">
            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">
                Channel connection
              </span>
              <select
                value={channelConfigId}
                onChange={(e) => setChannelConfigId(e.target.value)}
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                {activeChannels.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.channel_type} — {c.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">Kind</span>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as CommunicationDestinationKind)}
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                {kindOptions.map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="#standup, DM Manav, Daily summary email…"
                required
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              />
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">
                Config JSON
              </span>
              <textarea
                rows={3}
                value={configText}
                onChange={(e) => setConfigText(e.target.value)}
                placeholder='{"chat_id": "C123", "thread_id": null}'
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
              />
              <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
                Address fields (chat_id, thread_id, email_address, webhook_url, …) for
                the gateway adapter. Optional for some kinds.
              </span>
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">
                Formatting
              </span>
              <select
                value={formattingPolicy}
                onChange={(e) =>
                  setFormattingPolicy(
                    e.target.value as CommunicationDestinationFormattingPolicy
                  )
                }
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                {FORMATTING_POLICIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="btn btn-sm"
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-sm btn-filled"
                disabled={!canSubmit}
              >
                {submitting ? 'Creating…' : 'Create destination'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
