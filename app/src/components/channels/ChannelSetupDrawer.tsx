import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X, ChevronRight, ExternalLink, Eye, EyeOff, Copy, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import { channelsApi, type ChannelConfig } from '../../lib/api';
import type { ChannelPlatform } from './platforms';

interface ChannelSetupDrawerProps {
  open: boolean;
  platform: ChannelPlatform;
  /**
   * If supplied, drawer opens in "Edit" mode and PATCHes this channel.
   * Otherwise drawer creates a new ChannelConfig.
   */
  existing?: ChannelConfig;
  onClose: () => void;
  onSaved: () => void;
}

interface TestState {
  status: 'idle' | 'pending' | 'ok' | 'error';
  message?: string;
}

export function ChannelSetupDrawer({
  open,
  platform,
  existing,
  onClose,
  onSaved,
}: ChannelSetupDrawerProps) {
  const isEdit = Boolean(existing);
  const Preview = platform.preview;

  const [name, setName] = useState('');
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showSteps, setShowSteps] = useState(!isEdit);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [testState, setTestState] = useState<TestState>({ status: 'idle' });
  const [savedChannel, setSavedChannel] = useState<ChannelConfig | null>(null);
  const [webhookCopied, setWebhookCopied] = useState(false);

  const firstFieldRef = useRef<HTMLInputElement>(null);

  // Reset form when drawer opens or platform changes
  useEffect(() => {
    if (!open) return;
    setName(existing?.name || `My ${platform.name}`);
    setCredentials({});
    setRevealed({});
    setShowAdvanced(false);
    setShowSteps(!isEdit && platform.credentials.length > 0);
    setTestState({ status: 'idle' });
    setSavedChannel(existing || null);
    setWebhookCopied(false);
    // Autofocus first credential field after mount
    requestAnimationFrame(() => firstFieldRef.current?.focus());
  }, [open, platform, existing, isEdit]);

  // ESC closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, saving, onClose]);

  const allFields = [...platform.credentials, ...(platform.advancedCredentials || [])];

  const requiredFilled =
    platform.credentials.length === 0 ||
    platform.credentials.every((f) => (credentials[f.key] || '').trim().length > 0);

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error('Give this channel a name first.');
      return;
    }
    if (!requiredFilled) {
      toast.error('Fill in the required credentials.');
      return;
    }

    setSaving(true);
    setTestState({ status: 'idle' });
    try {
      // Strip empty optional values so the backend doesn't get blank strings
      const creds = Object.fromEntries(
        Object.entries(credentials).filter(([, v]) => v.trim().length > 0)
      );

      let channel: ChannelConfig;
      if (isEdit && existing) {
        channel = await channelsApi.update(existing.id, {
          name: name.trim(),
          ...(Object.keys(creds).length > 0 ? { credentials: creds } : {}),
        });
      } else {
        channel = await channelsApi.create({
          channel_type: platform.key,
          name: name.trim(),
          credentials: creds,
        });
      }

      setSavedChannel(channel);

      // Auto-run a test for platforms that support it. CLI has no creds,
      // skip the round-trip.
      if (platform.credentials.length > 0) {
        setTestState({ status: 'pending' });
        try {
          await channelsApi.test(channel.id, 'self');
          setTestState({ status: 'ok', message: 'Test message delivered.' });
        } catch (err) {
          const detail =
            (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
            'Channel saved, but the test message failed. Check your credentials.';
          setTestState({ status: 'error', message: detail });
        }
      }

      onSaved();
      toast.success(isEdit ? 'Channel updated' : `${platform.name} connected`);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string | unknown[] } } }).response?.data
        ?.detail;
      const msg = typeof detail === 'string' ? detail : `Failed to ${isEdit ? 'update' : 'connect'} ${platform.name}`;
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleRetest = async () => {
    if (!savedChannel) return;
    setTestState({ status: 'pending' });
    try {
      await channelsApi.test(savedChannel.id, 'self');
      setTestState({ status: 'ok', message: 'Test message delivered.' });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Test failed.';
      setTestState({ status: 'error', message: detail });
    }
  };

  const handleCopyWebhook = async () => {
    if (!savedChannel?.webhook_url) return;
    await navigator.clipboard.writeText(savedChannel.webhook_url);
    setWebhookCopied(true);
    setTimeout(() => setWebhookCopied(false), 1500);
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
          style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
          onClick={() => !saving && onClose()}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={`Connect ${platform.name}`}
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 4 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg)] shadow-2xl"
          >
            {/* Header */}
            <header className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md"
                  style={{ backgroundColor: `${platform.brandColor}1a` }}
                  aria-hidden="true"
                >
                  <span
                    className="block h-5 w-5"
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
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-semibold text-[var(--text)]">
                    {isEdit ? `Edit ${platform.name} connection` : `Connect ${platform.name}`}
                  </h2>
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{platform.tagline}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                disabled={saving}
                aria-label="Close"
                className="shrink-0 rounded-[var(--radius-small)] p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </header>

            {/* Body — scrolling */}
            <div className="flex-1 overflow-y-auto">
              {/* Preview slab — anchors the user in the visual outcome */}
              <div className="border-b border-[var(--border)] bg-[var(--surface)] px-5 py-4">
                <div className="rounded-md bg-[var(--bg)] p-2.5 ring-1 ring-[var(--border)]">
                  <Preview />
                </div>
                <p className="mt-2 text-[10.5px] text-[var(--text-subtle)]">
                  This is what an approval looks like in {platform.name}.
                </p>
              </div>

              <div className="space-y-4 px-5 py-4">
                {/* Channel name */}
                <Field label="Connection name" htmlFor="channel-name">
                  <input
                    id="channel-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={100}
                    placeholder={`My ${platform.name}`}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  />
                </Field>

                {/* Credentials */}
                {platform.credentials.map((field, idx) => (
                  <CredentialInput
                    key={field.key}
                    field={field}
                    value={credentials[field.key] || ''}
                    onChange={(v) => setCredentials((prev) => ({ ...prev, [field.key]: v }))}
                    revealed={!!revealed[field.key]}
                    onToggleReveal={() =>
                      setRevealed((prev) => ({ ...prev, [field.key]: !prev[field.key] }))
                    }
                    inputRef={idx === 0 ? firstFieldRef : undefined}
                  />
                ))}

                {/* Advanced credentials */}
                {platform.advancedCredentials && platform.advancedCredentials.length > 0 && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setShowAdvanced((v) => !v)}
                      className="flex items-center gap-1 text-[11px] font-medium text-[var(--text-muted)] hover:text-[var(--text)]"
                    >
                      <ChevronRight
                        size={12}
                        className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
                      />
                      Advanced ({platform.advancedCredentials.length} optional)
                    </button>
                    {showAdvanced && (
                      <div className="mt-3 space-y-3">
                        {platform.advancedCredentials.map((field) => (
                          <CredentialInput
                            key={field.key}
                            field={field}
                            value={credentials[field.key] || ''}
                            onChange={(v) =>
                              setCredentials((prev) => ({ ...prev, [field.key]: v }))
                            }
                            revealed={!!revealed[field.key]}
                            onToggleReveal={() =>
                              setRevealed((prev) => ({ ...prev, [field.key]: !prev[field.key] }))
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* CLI-style "no credentials needed" banner */}
                {allFields.length === 0 && (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-3 text-[12px] text-[var(--text-muted)]">
                    The CLI uses your existing Tesslate session — no tokens to paste.
                    Click Connect to register this surface for delivery.
                  </div>
                )}

                {/* Test result banner */}
                {testState.status !== 'idle' && (
                  <TestBanner state={testState} onRetry={handleRetest} />
                )}

                {/* Webhook URL panel — appears after first save when relevant */}
                {savedChannel?.webhook_url && (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
                    <div className="text-[11px] font-medium text-[var(--text)]">Webhook URL</div>
                    <p className="mt-0.5 text-[10.5px] text-[var(--text-muted)]">
                      Paste this into your {platform.name} app's webhook configuration.
                    </p>
                    <div className="mt-2 flex items-center gap-1.5">
                      <code className="flex-1 truncate rounded bg-[var(--bg)] px-2 py-1.5 font-mono text-[10.5px] text-[var(--text)] ring-1 ring-[var(--border)]">
                        {savedChannel.webhook_url}
                      </code>
                      <button
                        type="button"
                        onClick={handleCopyWebhook}
                        className="btn btn-sm flex items-center gap-1"
                      >
                        {webhookCopied ? (
                          <>
                            <Check size={12} /> Copied
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> Copy
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )}

                {/* Setup steps — collapsible */}
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface)]">
                  <button
                    type="button"
                    onClick={() => setShowSteps((v) => !v)}
                    className="flex w-full items-center justify-between px-3 py-2 text-left"
                  >
                    <span className="text-[12px] font-medium text-[var(--text)]">
                      How to get these
                    </span>
                    <ChevronRight
                      size={14}
                      className={`text-[var(--text-muted)] transition-transform ${showSteps ? 'rotate-90' : ''}`}
                    />
                  </button>
                  {showSteps && (
                    <div className="border-t border-[var(--border)] px-3 py-3">
                      <ol className="list-decimal space-y-1.5 pl-4 text-[12px] leading-relaxed text-[var(--text-muted)]">
                        {platform.setupSteps.map((step, i) => (
                          <li key={i}>{step}</li>
                        ))}
                      </ol>
                      {platform.consoleUrl && (
                        <a
                          href={platform.consoleUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-3 inline-flex items-center gap-1 text-[11px] font-medium text-[var(--primary)] hover:underline"
                        >
                          Open {platform.name} console
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Footer */}
            <footer className="flex items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--surface)] px-5 py-3">
              <span className="text-[11px] text-[var(--text-subtle)]">
                {testState.status === 'ok'
                  ? 'Test message delivered'
                  : testState.status === 'pending'
                    ? 'Sending test message…'
                    : isEdit
                      ? 'Edit credentials and save to re-test'
                      : 'Auto-tests on save'}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={onClose} disabled={saving} className="btn btn-sm">
                  {testState.status === 'ok' ? 'Done' : 'Cancel'}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving || !requiredFilled || !name.trim()}
                  className="btn btn-filled btn-sm disabled:opacity-50"
                >
                  {saving
                    ? isEdit
                      ? 'Saving…'
                      : 'Connecting…'
                    : isEdit
                      ? 'Save changes'
                      : `Connect ${platform.name}`}
                </button>
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}

function Field({
  label,
  htmlFor,
  children,
  helpText,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
  helpText?: string;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-[11px] font-medium text-[var(--text)]">
        {label}
      </label>
      {children}
      {helpText && <p className="mt-1 text-[10.5px] text-[var(--text-subtle)]">{helpText}</p>}
    </div>
  );
}

interface CredentialInputProps {
  field: { key: string; label: string; placeholder?: string; helpText?: string };
  value: string;
  onChange: (v: string) => void;
  revealed: boolean;
  onToggleReveal: () => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

function CredentialInput({
  field,
  value,
  onChange,
  revealed,
  onToggleReveal,
  inputRef,
}: CredentialInputProps) {
  const id = `cred-${field.key}`;
  return (
    <Field label={field.label} htmlFor={id} helpText={field.helpText}>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type={revealed ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          autoComplete="off"
          spellCheck={false}
          className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 pr-10 text-sm font-mono text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
        />
        <button
          type="button"
          onClick={onToggleReveal}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--text-subtle)] hover:text-[var(--text)]"
          aria-label={revealed ? 'Hide value' : 'Reveal value'}
        >
          {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </Field>
  );
}

function TestBanner({
  state,
  onRetry,
}: {
  state: TestState;
  onRetry: () => void;
}) {
  if (state.status === 'pending') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[12px] text-[var(--text-muted)]">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--text-muted)] border-t-transparent" />
        Sending a test message…
      </div>
    );
  }
  if (state.status === 'ok') {
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-500">
        ✓ {state.message || 'Test message delivered.'}
      </div>
    );
  }
  if (state.status === 'error') {
    return (
      <div className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
        <div className="font-medium">Test failed</div>
        <div className="mt-0.5 text-[11.5px] text-red-500/90">{state.message}</div>
        <button
          type="button"
          onClick={onRetry}
          className="mt-1.5 text-[11px] font-medium underline"
        >
          Retry test
        </button>
      </div>
    );
  }
  return null;
}
