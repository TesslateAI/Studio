import type { AutomationTriggerIn, AutomationTriggerKind } from '../../../types/automations';
import { humanizeCron } from '../utils/humanize';

interface Props {
  value: AutomationTriggerIn;
  onChange: (next: AutomationTriggerIn) => void;
  /** Optional webhook receive URL (Phase 2) — when populated, displayed read-only. */
  webhookUrl?: string | null;
}

const KIND_OPTIONS: Array<{ value: AutomationTriggerKind; label: string; help: string }> = [
  {
    value: 'cron',
    label: 'On a schedule',
    help: 'Run at recurring times — every day, every weekday, every Monday, etc.',
  },
  {
    value: 'webhook',
    label: 'When a URL receives data',
    help: "Run when something POSTs to your automation's webhook URL.",
  },
  {
    value: 'manual',
    label: 'Only when I run it',
    help: 'Run only when you click "Run now" on this automation.',
  },
  {
    value: 'app_invocation',
    label: 'When an installed app calls it',
    help: 'Run when one of your installed apps emits a matching event.',
  },
];

/**
 * Renders a `kind` select plus a tiny kind-specific config form. Cron has
 * the only meaningful field (the cron expression). Webhooks display the
 * receive URL once the automation is created.
 */
export function TriggerEditor({ value, onChange, webhookUrl }: Props) {
  const updateConfig = (patch: Record<string, unknown>) =>
    onChange({ ...value, config: { ...(value.config || {}), ...patch } });

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          When should this run?
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
            Schedule (cron expression)
          </span>
          <input
            type="text"
            value={String(value.config.expression ?? '')}
            onChange={(e) => updateConfig({ expression: e.target.value })}
            placeholder="0 9 * * 1-5"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
          {value.config.expression ? (
            <span className="mt-1 block text-[10px] text-emerald-400">
              {humanizeCron(
                String(value.config.expression),
                value.config.timezone ? String(value.config.timezone) : null
              )}
            </span>
          ) : (
            <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
              Five fields: minute, hour, day-of-month, month, weekday. Example:{' '}
              <code className="font-mono">0 9 * * 1-5</code> = every weekday at 9 AM.
            </span>
          )}
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
            <span className="block text-xs font-medium text-[var(--text)] mb-1">Webhook URL</span>
            <code className="block text-[11px] font-mono px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-[var(--text-muted)] break-all">
              {webhookUrl ?? '(URL appears after the automation is created)'}
            </code>
            <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
              You'll get a signed URL once the automation is saved. Anything POSTed there will
              trigger a run.
            </span>
          </div>
        </div>
      )}

      {value.kind === 'manual' && (
        <p className="text-[11px] text-[var(--text-muted)]">
          This automation will only run when you click "Run now" on its detail page.
        </p>
      )}

      {value.kind === 'app_invocation' && (
        <p className="text-[11px] text-[var(--text-muted)]">
          This automation will run whenever one of your installed apps emits a matching event.
        </p>
      )}
    </div>
  );
}
