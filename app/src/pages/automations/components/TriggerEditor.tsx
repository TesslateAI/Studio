import type {
  AutomationTriggerIn,
  AutomationTriggerKind,
} from '../../../types/automations';

interface Props {
  value: AutomationTriggerIn;
  onChange: (next: AutomationTriggerIn) => void;
  /** Optional webhook receive URL (Phase 2) — when populated, displayed read-only. */
  webhookUrl?: string | null;
}

const KIND_OPTIONS: Array<{ value: AutomationTriggerKind; label: string; help: string }> = [
  { value: 'cron', label: 'Cron schedule', help: 'Run on a recurring cron expression.' },
  { value: 'webhook', label: 'Webhook', help: 'Run when an external HTTP POST arrives.' },
  { value: 'manual', label: 'Manual', help: 'Only ever run via the "Run now" button.' },
  {
    value: 'app_invocation',
    label: 'App invocation',
    help: 'Run when an installed app calls this automation.',
  },
];

/**
 * Phase 1 trigger editor. Renders a `kind` select plus a tiny
 * kind-specific config form. Cron has the only meaningful field
 * (the cron expression). Webhooks display the receive URL once the
 * automation is created — Phase 2 builds the actual receive endpoint.
 */
export function TriggerEditor({ value, onChange, webhookUrl }: Props) {
  const updateConfig = (patch: Record<string, unknown>) =>
    onChange({ ...value, config: { ...(value.config || {}), ...patch } });

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          Trigger kind
        </span>
        <select
          value={value.kind}
          onChange={(e) => onChange({ kind: e.target.value as AutomationTriggerKind, config: {} })}
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        >
          {KIND_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          {KIND_OPTIONS.find((o) => o.value === value.kind)?.help}
        </span>
      </label>

      {value.kind === 'cron' && (
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">
            Cron expression
          </span>
          <input
            type="text"
            value={String(value.config.expression ?? '')}
            onChange={(e) => updateConfig({ expression: e.target.value })}
            placeholder="0 9 * * 1-5"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
          <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
            Standard 5-field cron (min hour day month weekday). Optional 6th field = seconds.
          </span>
        </label>
      )}

      {value.kind === 'cron' && (
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">
            Timezone (optional)
          </span>
          <input
            type="text"
            value={String(value.config.timezone ?? '')}
            onChange={(e) => updateConfig({ timezone: e.target.value })}
            placeholder="UTC"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          />
          <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
            IANA timezone name. Defaults to UTC if omitted.
          </span>
        </label>
      )}

      {value.kind === 'webhook' && (
        <div className="space-y-2">
          <div>
            <span className="block text-xs font-medium text-[var(--text)] mb-1">
              Webhook URL
            </span>
            <code className="block text-[11px] font-mono px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-[var(--text-muted)] break-all">
              {webhookUrl ?? '(URL appears after the automation is created)'}
            </code>
            <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
              Phase 2 surfaces a signed receive endpoint. Phase 1 saves the trigger row only.
            </span>
          </div>
        </div>
      )}

      {value.kind === 'manual' && (
        <p className="text-[11px] text-[var(--text-muted)]">
          Manual triggers run only via the "Run now" button on the detail page.
        </p>
      )}

      {value.kind === 'app_invocation' && (
        <p className="text-[11px] text-[var(--text-muted)]">
          App-invocation triggers fire when an installed app emits an event matching the
          automation. Phase 1 stores the trigger row; Phase 2 wires the dispatcher.
        </p>
      )}
    </div>
  );
}
