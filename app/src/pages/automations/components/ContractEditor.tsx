import { useState } from 'react';

interface Props {
  /** Stringified JSON. Source of truth lives in the parent. */
  value: string;
  onChange: (next: string) => void;
}

const DEFAULT_CONTRACT = {
  allowed_tools: ['read', 'write', 'bash'],
  max_compute_tier: 1,
  max_iterations: 25,
};

/**
 * Permissions editor — JSON textarea with two helper buttons: "Use
 * defaults" (writes a sensible starter contract) and "Validate JSON"
 * (parses and reports errors inline). A structured editor will replace
 * this textarea later; the JSON form remains as the escape hatch.
 */
export function ContractEditor({ value, onChange }: Props) {
  const [validation, setValidation] = useState<{ ok: boolean; message: string } | null>(null);

  const handleValidate = () => {
    try {
      const parsed = JSON.parse(value);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setValidation({ ok: false, message: 'Contract must be a JSON object (not array/null).' });
        return;
      }
      if (Object.keys(parsed).length === 0) {
        setValidation({ ok: false, message: 'Contract must contain at least one key.' });
        return;
      }
      setValidation({ ok: true, message: 'Looks good — valid JSON object.' });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setValidation({ ok: false, message: `Invalid JSON: ${msg}` });
    }
  };

  const handleUseDefaults = () => {
    const next = JSON.stringify(DEFAULT_CONTRACT, null, 2);
    onChange(next);
    setValidation({ ok: true, message: 'Inserted a starter contract.' });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-[var(--text)]">Permissions (JSON)</span>
        <div className="flex gap-1.5">
          <button type="button" onClick={handleUseDefaults} className="btn btn-sm">
            Use defaults
          </button>
          <button type="button" onClick={handleValidate} className="btn btn-sm">
            Validate JSON
          </button>
        </div>
      </div>
      <textarea
        rows={10}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setValidation(null);
        }}
        placeholder='{"allowed_tools": ["read", "write"], "max_compute_tier": 1}'
        className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
      />
      <p className="text-[10px] text-[var(--text-subtle)]">
        Required guardrails for what the automation can do. At a minimum, include{' '}
        <code>allowed_tools</code> and <code>max_compute_tier</code>. Click{' '}
        <strong>Use defaults</strong> for a sensible starter.
      </p>
      {validation && (
        <p
          className={`text-[10px] ${
            validation.ok ? 'text-emerald-400' : 'text-[var(--status-error)]'
          }`}
        >
          {validation.message}
        </p>
      )}
    </div>
  );
}
