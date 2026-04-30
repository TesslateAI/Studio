import { useMemo, useState } from 'react';
import { ContractEditor } from './ContractEditor';

interface Props {
  /** Stringified JSON contract — source of truth lives in the parent. */
  contractText: string;
  onContractTextChange: (next: string) => void;

  maxComputeTier: string;
  onMaxComputeTierChange: (next: string) => void;

  maxSpendPerRun: string;
  onMaxSpendPerRunChange: (next: string) => void;

  maxSpendPerDay: string;
  onMaxSpendPerDayChange: (next: string) => void;
}

/** Tools the structured allow-list checkbox surface offers out of the box.
 *  Anything else the contract has gets preserved on save (we merge, not
 *  replace, the allowed_tools array). */
const COMMON_TOOLS = [
  { id: 'read', label: 'Read files' },
  { id: 'write', label: 'Write files' },
  { id: 'edit', label: 'Edit files' },
  { id: 'bash', label: 'Run shell commands' },
  { id: 'web', label: 'Browse the web' },
] as const;

const POWER_LEVELS: Array<{ tier: number; label: string; help: string }> = [
  { tier: 0, label: 'Light', help: 'No sandbox. Cheapest. Use for quick LLM-only actions.' },
  { tier: 1, label: 'Standard', help: 'Default sandbox. Most automations should use this.' },
  { tier: 2, label: 'Heavy', help: 'Larger sandbox for big jobs. Higher cost.' },
];

interface ParsedContract {
  ok: boolean;
  obj: Record<string, unknown> | null;
  error: string | null;
}

function parseContract(text: string): ParsedContract {
  if (!text.trim()) return { ok: false, obj: null, error: 'Permissions are required.' };
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { ok: false, obj: null, error: 'Permissions must be a JSON object.' };
    }
    return { ok: true, obj: parsed as Record<string, unknown>, error: null };
  } catch (err) {
    return {
      ok: false,
      obj: null,
      error: `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

export function LimitsForm({
  contractText,
  onContractTextChange,
  maxComputeTier,
  onMaxComputeTierChange,
  maxSpendPerRun,
  onMaxSpendPerRunChange,
  maxSpendPerDay,
  onMaxSpendPerDayChange,
}: Props) {
  const [rawOpen, setRawOpen] = useState(false);

  const parsed = useMemo(() => parseContract(contractText), [contractText]);

  const allowedTools = useMemo(() => {
    if (!parsed.ok || !parsed.obj) return [] as string[];
    const v = parsed.obj.allowed_tools;
    if (!Array.isArray(v)) return [];
    return v.map(String);
  }, [parsed]);

  const maxIterations = useMemo(() => {
    if (!parsed.ok || !parsed.obj) return '';
    const v = parsed.obj.max_iterations;
    return typeof v === 'number' ? String(v) : '';
  }, [parsed]);

  const writeContract = (mutate: (obj: Record<string, unknown>) => void) => {
    if (!parsed.ok || !parsed.obj) return;
    const next = { ...parsed.obj };
    mutate(next);
    onContractTextChange(JSON.stringify(next, null, 2));
  };

  const toggleTool = (tool: string) => {
    writeContract((obj) => {
      const current = Array.isArray(obj.allowed_tools)
        ? (obj.allowed_tools as unknown[]).map(String)
        : [];
      const set = new Set(current);
      if (set.has(tool)) set.delete(tool);
      else set.add(tool);
      obj.allowed_tools = Array.from(set);
    });
  };

  const setMaxIterations = (next: string) => {
    writeContract((obj) => {
      if (!next.trim()) {
        delete obj.max_iterations;
      } else {
        const n = parseInt(next, 10);
        if (Number.isFinite(n) && n > 0) obj.max_iterations = n;
      }
    });
  };

  const structuredDisabled = !parsed.ok;

  return (
    <div className="space-y-4">
      {/* Power level */}
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium text-[var(--text)] mb-1">Power level</legend>
        {POWER_LEVELS.map((opt) => (
          <label key={opt.tier} className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="power-level"
              value={opt.tier}
              checked={parseInt(maxComputeTier, 10) === opt.tier}
              onChange={() => onMaxComputeTierChange(String(opt.tier))}
              className="mt-0.5"
            />
            <span className="flex-1">
              <span className="block text-xs text-[var(--text)]">{opt.label}</span>
              <span className="block text-[10px] text-[var(--text-subtle)]">{opt.help}</span>
            </span>
          </label>
        ))}
        <p className="text-[10px] text-[var(--text-subtle)]">
          Higher tiers (3+) are available — type a number in the raw JSON if you need them.
        </p>
        <input
          type="number"
          min={0}
          step={1}
          value={maxComputeTier}
          onChange={(e) => onMaxComputeTierChange(e.target.value)}
          aria-label="Power level (numeric override)"
          className="w-20 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
        />
      </fieldset>

      {/* Allowed tools */}
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium text-[var(--text)] mb-1">
          What is the AI allowed to do?
        </legend>
        <div className="grid grid-cols-2 gap-1.5">
          {COMMON_TOOLS.map((tool) => {
            const checked = allowedTools.includes(tool.id);
            return (
              <label key={tool.id} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={structuredDisabled}
                  onChange={() => toggleTool(tool.id)}
                />
                <span className="text-xs text-[var(--text)]">{tool.label}</span>
              </label>
            );
          })}
        </div>
        {allowedTools.some((t) => !COMMON_TOOLS.find((c) => c.id === t)) && (
          <p className="text-[10px] text-[var(--text-subtle)]">
            Other tools allowed:{' '}
            <code className="font-mono">
              {allowedTools.filter((t) => !COMMON_TOOLS.find((c) => c.id === t)).join(', ')}
            </code>
          </p>
        )}
      </fieldset>

      {/* Max steps + spend caps */}
      <div className="grid grid-cols-3 gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">
            Max steps per run
          </span>
          <input
            type="number"
            min={1}
            step={1}
            value={maxIterations}
            disabled={structuredDisabled}
            onChange={(e) => setMaxIterations(e.target.value)}
            placeholder="e.g. 25"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)] disabled:opacity-50"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">Max $ per run</span>
          <input
            type="text"
            inputMode="decimal"
            value={maxSpendPerRun}
            onChange={(e) => onMaxSpendPerRunChange(e.target.value)}
            placeholder="e.g. 0.50"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">Max $ per day</span>
          <input
            type="text"
            inputMode="decimal"
            value={maxSpendPerDay}
            onChange={(e) => onMaxSpendPerDayChange(e.target.value)}
            placeholder="e.g. 5.00"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
        </label>
      </div>

      {/* Raw JSON disclosure — covers everything the structured form doesn't,
          and stays the canonical source of truth either way. */}
      <div>
        <button
          type="button"
          onClick={() => setRawOpen((v) => !v)}
          className="text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
        >
          {rawOpen ? 'Hide raw permissions JSON' : 'Edit raw permissions JSON'}
        </button>
        {!parsed.ok && parsed.error && (
          <p className="mt-1 text-[10px] text-[var(--status-error)]">
            Structured form locked — {parsed.error} Open the raw JSON below to fix it.
          </p>
        )}
        {rawOpen && (
          <div className="mt-2">
            <ContractEditor value={contractText} onChange={onContractTextChange} />
          </div>
        )}
      </div>
    </div>
  );
}
