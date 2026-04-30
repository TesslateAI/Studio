import { useMemo, useState } from 'react';
import { humanizeCron } from '../utils/humanize';

interface Props {
  /** Cron expression — empty string when no preset has been chosen yet. */
  expression: string;
  /** IANA timezone name; empty string falls back to UTC server-side. */
  timezone: string;
  onChange: (next: { expression: string; timezone: string }) => void;
}

interface Preset {
  id: string;
  label: string;
  expression: string;
}

const PRESETS: Preset[] = [
  { id: 'every-15m', label: 'Every 15 minutes', expression: '*/15 * * * *' },
  { id: 'hourly', label: 'Every hour', expression: '0 * * * *' },
  { id: 'daily-9am', label: 'Every day at 9:00 AM', expression: '0 9 * * *' },
  { id: 'weekday-9am', label: 'Every weekday at 9:00 AM', expression: '0 9 * * 1-5' },
  { id: 'weekly-mon-9am', label: 'Every Monday at 9:00 AM', expression: '0 9 * * 1' },
  { id: 'monthly-1st-9am', label: 'On the 1st of each month at 9:00 AM', expression: '0 9 1 * *' },
];

/**
 * Common IANA timezones, ordered by "people the user is most likely to be in".
 * Browser-detected timezone is appended at the front when distinct.
 */
const COMMON_TIMEZONES = [
  'UTC',
  'America/Los_Angeles',
  'America/Denver',
  'America/Chicago',
  'America/New_York',
  'America/Toronto',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Asia/Kolkata',
  'Australia/Sydney',
];

function detectBrowserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

export function ScheduleBuilder({ expression, timezone, onChange }: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const browserTz = useMemo(detectBrowserTimezone, []);
  const tzOptions = useMemo(() => {
    const set = new Set<string>(COMMON_TIMEZONES);
    if (browserTz && !set.has(browserTz)) {
      return [browserTz, ...COMMON_TIMEZONES];
    }
    return Array.from(set);
  }, [browserTz]);

  const matchedPreset = PRESETS.find((p) => p.expression === expression.trim()) ?? null;
  const showAdvanced = advancedOpen || (!!expression && !matchedPreset);

  const setExpression = (next: string) => onChange({ expression: next, timezone });
  const setTimezone = (next: string) => onChange({ expression, timezone: next });

  return (
    <div className="space-y-3">
      <div>
        <span className="block text-xs font-medium text-[var(--text)] mb-2">How often?</span>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((preset) => {
            const selected = preset.expression === expression.trim();
            return (
              <button
                type="button"
                key={preset.id}
                onClick={() => setExpression(preset.expression)}
                aria-pressed={selected}
                className={`px-2.5 py-1 rounded-[var(--radius-small)] text-[11px] border transition-colors ${
                  selected
                    ? 'border-[var(--primary)] bg-[var(--primary)]/15 text-[var(--text)]'
                    : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Live humanized preview / status of the current expression */}
      {expression ? (
        <div className="px-2 py-1.5 rounded-[var(--radius-small)] bg-[var(--surface-hover)] text-[11px] text-[var(--text-muted)]">
          <span className="text-[var(--text-subtle)]">Will run:</span>{' '}
          <span className="text-[var(--text)] font-medium">
            {humanizeCron(expression, timezone || null)}
          </span>
        </div>
      ) : (
        <p className="text-[10px] text-[var(--text-subtle)]">
          Pick a preset above, or click <em>Show cron expression</em> below to write your own
          schedule.
        </p>
      )}

      {/* Advanced — raw cron text input. Auto-opens when the saved expression
          doesn't match any preset (so editing keeps working). */}
      <div>
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
        >
          {showAdvanced ? 'Hide cron expression' : 'Show cron expression'}
        </button>
        {showAdvanced && (
          <div className="mt-2 space-y-1.5">
            <input
              type="text"
              value={expression}
              onChange={(e) => setExpression(e.target.value)}
              placeholder="0 9 * * 1-5"
              className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
            />
            <p className="text-[10px] text-[var(--text-subtle)]">
              Five fields: minute, hour, day-of-month, month, weekday. Example:{' '}
              <code className="font-mono">0 9 * * 1-5</code> = every weekday at 9 AM.
            </p>
          </div>
        )}
      </div>

      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Timezone</span>
        <select
          value={timezone || (browserTz ?? 'UTC')}
          onChange={(e) => setTimezone(e.target.value === 'UTC' ? '' : e.target.value)}
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        >
          {tzOptions.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
              {tz === browserTz ? ' (your timezone)' : ''}
            </option>
          ))}
          <option value="__custom__">Other (paste an IANA name)…</option>
        </select>
        {timezone === '__custom__' || (timezone && !tzOptions.includes(timezone)) ? (
          <input
            type="text"
            value={timezone === '__custom__' ? '' : timezone}
            onChange={(e) => setTimezone(e.target.value)}
            placeholder="Europe/Amsterdam"
            className="mt-2 w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          />
        ) : null}
      </label>
    </div>
  );
}
