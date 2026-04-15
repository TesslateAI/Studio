/**
 * HostedAgentInspector — right-pane inspector for a selected HostedAgentNode.
 * Callers wire `onUpdate` to persist the spec back to .tesslate/config.json
 * via the existing configSyncApi.
 */
import { useState, useEffect } from 'react';
import type { HostedAgentNodeData } from './HostedAgentNode';

export interface HostedAgentInspectorProps {
  spec: HostedAgentNodeData;
  onUpdate: (next: HostedAgentNodeData) => void;
}

const THINKING_EFFORTS = ['none', 'low', 'medium', 'high'] as const;

export function HostedAgentInspector({ spec, onUpdate }: HostedAgentInspectorProps) {
  const [local, setLocal] = useState<HostedAgentNodeData>(spec);

  useEffect(() => {
    setLocal(spec);
  }, [spec]);

  const commit = (next: HostedAgentNodeData) => {
    setLocal(next);
    onUpdate(next);
  };

  const setField = <K extends keyof HostedAgentNodeData>(
    key: K,
    value: HostedAgentNodeData[K]
  ) => {
    commit({ ...local, [key]: value });
  };

  return (
    <div
      data-testid="hosted-agent-inspector"
      className="w-80 border-l border-[var(--border)] bg-[var(--bg)] p-4 space-y-3 overflow-y-auto"
    >
      <h2 className="text-sm font-semibold">Hosted Agent</h2>

      <Field label="id">
        <input
          data-testid="field-id"
          value={local.id}
          onChange={(e) => setField('id', e.target.value)}
          className={inputCls}
        />
      </Field>

      <Field label="system_prompt_ref">
        <input
          data-testid="field-system-prompt-ref"
          value={local.system_prompt_ref ?? ''}
          onChange={(e) => setField('system_prompt_ref', e.target.value)}
          className={inputCls}
        />
      </Field>

      <Field label="model_pref">
        <input
          data-testid="field-model-pref"
          value={local.model_pref ?? ''}
          onChange={(e) => setField('model_pref', e.target.value)}
          className={inputCls}
        />
      </Field>

      <Field label="tools_ref (comma-separated)">
        <input
          data-testid="field-tools-ref"
          value={(local.tools_ref ?? []).join(',')}
          onChange={(e) => setField('tools_ref', splitTags(e.target.value))}
          className={inputCls}
        />
      </Field>

      <Field label="mcps_ref (comma-separated)">
        <input
          data-testid="field-mcps-ref"
          value={(local.mcps_ref ?? []).join(',')}
          onChange={(e) => setField('mcps_ref', splitTags(e.target.value))}
          className={inputCls}
        />
      </Field>

      <Field label="temperature">
        <input
          data-testid="field-temperature"
          type="number"
          step="0.1"
          value={local.temperature ?? ''}
          onChange={(e) =>
            setField(
              'temperature',
              e.target.value === '' ? undefined : parseFloat(e.target.value)
            )
          }
          className={inputCls}
        />
      </Field>

      <Field label="max_tokens">
        <input
          data-testid="field-max-tokens"
          type="number"
          value={local.max_tokens ?? ''}
          onChange={(e) =>
            setField(
              'max_tokens',
              e.target.value === '' ? undefined : parseInt(e.target.value, 10)
            )
          }
          className={inputCls}
        />
      </Field>

      <Field label="thinking_effort">
        <select
          data-testid="field-thinking-effort"
          value={local.thinking_effort ?? 'none'}
          onChange={(e) => setField('thinking_effort', e.target.value)}
          className={inputCls}
        >
          {THINKING_EFFORTS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </Field>

      <Field label="warm_pool_size">
        <input
          data-testid="field-warm-pool-size"
          type="number"
          min={0}
          value={local.warm_pool_size ?? 0}
          onChange={(e) =>
            setField('warm_pool_size', parseInt(e.target.value, 10) || 0)
          }
          className={inputCls}
        />
      </Field>
    </div>
  );
}

function splitTags(raw: string): string[] {
  return raw
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);
}

const inputCls =
  'w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm';

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
