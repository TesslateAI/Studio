import { useEffect, useState } from 'react';
import { appActionsApi, marketplaceApi } from '../../../lib/api';
import type {
  AutomationActionIn,
  AutomationActionType,
  AppActionRow,
} from '../../../types/automations';
import { DestinationPicker } from './DestinationPicker';

interface Props {
  value: AutomationActionIn;
  onChange: (next: AutomationActionIn) => void;
}

const ACTION_OPTIONS: Array<{ value: AutomationActionType; label: string; help: string }> = [
  {
    value: 'agent.run',
    label: 'Run an AI agent',
    help: 'Pick one of your agents and tell it what to do.',
  },
  {
    value: 'app.invoke',
    label: 'Use one of my apps',
    help: 'Call an action exposed by one of your installed apps.',
  },
  {
    value: 'gateway.send',
    label: 'Send a message',
    help: 'Post a message to a Slack channel, Telegram chat, email, or webhook.',
  },
];

interface AgentRow {
  id: string;
  name: string;
}

/**
 * Selects the action_type and renders a tiny config form per type. Network
 * calls are intentionally tolerant: if /api/marketplace/my-agents or
 * /api/apps/{id}/actions returns nothing (or errors), the dropdowns
 * degrade to free-text UUID inputs so the user can still wire up an
 * automation.
 */
export function ActionEditor({ value, onChange }: Props) {
  const updateConfig = (patch: Record<string, unknown>) =>
    onChange({ ...value, config: { ...(value.config || {}), ...patch } });

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          What should it do?
        </span>
        <select
          value={value.action_type}
          onChange={(e) =>
            onChange({
              action_type: e.target.value as AutomationActionType,
              config: {},
              app_action_id: null,
              ordinal: value.ordinal,
            })
          }
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        >
          {ACTION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          {ACTION_OPTIONS.find((o) => o.value === value.action_type)?.help}
        </span>
      </label>

      {value.action_type === 'agent.run' && (
        <AgentRunFields value={value} updateConfig={updateConfig} />
      )}

      {value.action_type === 'app.invoke' && <AppInvokeFields value={value} onChange={onChange} />}

      {value.action_type === 'gateway.send' && (
        <GatewaySendFields value={value} updateConfig={updateConfig} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// agent.run — pick an agent + prompt template
// ---------------------------------------------------------------------------

function AgentRunFields({
  value,
  updateConfig,
}: {
  value: AutomationActionIn;
  updateConfig: (patch: Record<string, unknown>) => void;
}) {
  const [agents, setAgents] = useState<AgentRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .getMyAgents()
      .then((data) => {
        if (cancelled) return;
        // Backend response shape: { agents: [...] } or { items: [...] } —
        // be defensive about which key is used.
        const list = (data?.agents ?? data?.items ?? data ?? []) as Array<{
          id: string;
          name?: string;
          slug?: string;
        }>;
        setAgents(
          list.map((a) => ({
            id: String(a.id),
            name: a.name ?? a.slug ?? a.id,
          }))
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err?.message || 'Failed to load agents');
        setAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Which agent?</span>
        {agents === null ? (
          <div className="text-[11px] text-[var(--text-subtle)]">Loading your agents…</div>
        ) : agents.length > 0 ? (
          <select
            value={String(value.config.agent_id ?? '')}
            onChange={(e) => updateConfig({ agent_id: e.target.value })}
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          >
            <option value="">— Pick an agent —</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={String(value.config.agent_id ?? '')}
            onChange={(e) => updateConfig({ agent_id: e.target.value })}
            placeholder="(paste an agent UUID)"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
        )}
        {loadError && (
          <span className="mt-1 block text-[10px] text-[var(--status-error)]">
            Couldn't load your agents ({loadError}). Paste an agent UUID instead.
          </span>
        )}
      </label>

      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          Tell the agent what to do
        </span>
        <textarea
          rows={5}
          value={String(value.config.prompt ?? '')}
          onChange={(e) => updateConfig({ prompt: e.target.value })}
          placeholder="Summarize today's pipeline metrics and post the highlights."
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        />
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          Use <code className="font-mono">{'{{event.payload.field}}'}</code> to insert data from the
          trigger event.
        </span>
      </label>
    </div>
  );
}

// ---------------------------------------------------------------------------
// app.invoke — pick an installed app instance + one of its actions
// ---------------------------------------------------------------------------

function AppInvokeFields({
  value,
  onChange,
}: {
  value: AutomationActionIn;
  onChange: (next: AutomationActionIn) => void;
}) {
  const [actions, setActions] = useState<AppActionRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const instanceId = String(value.config.app_instance_id ?? '');

  useEffect(() => {
    if (!instanceId) {
      setActions(null);
      setLoadError(null);
      return;
    }
    let cancelled = false;
    setActions(null);
    setLoadError(null);
    appActionsApi
      .list(instanceId)
      .then((res) => {
        if (cancelled) return;
        setActions(res.actions);
      })
      .catch((err) => {
        if (cancelled) return;
        setActions([]);
        setLoadError(err?.response?.data?.detail || err?.message || 'Failed to load app actions');
      });
    return () => {
      cancelled = true;
    };
  }, [instanceId]);

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Installed app</span>
        <input
          type="text"
          value={instanceId}
          onChange={(e) =>
            onChange({
              ...value,
              config: { ...(value.config || {}), app_instance_id: e.target.value },
              app_action_id: null,
            })
          }
          placeholder="(paste an installed-app UUID — see My Apps)"
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
        />
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          A picker is coming soon. Find the app's UUID on your{' '}
          <a href="/apps/installed" className="underline hover:text-[var(--text)]">
            installed apps page
          </a>
          .
        </span>
      </label>

      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Which action?</span>
        {actions === null && instanceId ? (
          <div className="text-[11px] text-[var(--text-subtle)]">Loading actions…</div>
        ) : actions && actions.length > 0 ? (
          <select
            value={value.app_action_id ?? ''}
            onChange={(e) => onChange({ ...value, app_action_id: e.target.value || null })}
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          >
            <option value="">— Pick an action —</option>
            {actions.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={value.app_action_id ?? ''}
            onChange={(e) => onChange({ ...value, app_action_id: e.target.value || null })}
            placeholder="(paste an action UUID)"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
        )}
        {loadError && (
          <span className="mt-1 block text-[10px] text-[var(--status-error)]">{loadError}</span>
        )}
      </label>

      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          Action input (JSON)
        </span>
        <textarea
          rows={4}
          value={
            typeof value.config.input === 'string'
              ? (value.config.input as string)
              : JSON.stringify(value.config.input ?? {}, null, 2)
          }
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              onChange({ ...value, config: { ...(value.config || {}), input: parsed } });
            } catch {
              // Keep the raw string so the user can keep typing — the
              // create-page validator catches bad JSON before submit.
              onChange({ ...value, config: { ...(value.config || {}), input: e.target.value } });
            }
          }}
          placeholder='{"key": "value"}'
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
        />
      </label>
    </div>
  );
}

// ---------------------------------------------------------------------------
// gateway.send — body text + destination ID
// ---------------------------------------------------------------------------

function GatewaySendFields({
  value,
  updateConfig,
}: {
  value: AutomationActionIn;
  updateConfig: (patch: Record<string, unknown>) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Destination</span>
        <DestinationPicker
          value={String(value.config.destination_id ?? '')}
          onChange={(destId) => updateConfig({ destination_id: destId })}
          allowEmpty={false}
          placeholder="Select destination"
        />
      </div>

      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Message to send</span>
        <textarea
          rows={5}
          value={String(value.config.body ?? '')}
          onChange={(e) => updateConfig({ body: e.target.value })}
          placeholder="Daily summary: {{run.output.summary}}"
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        />
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          Use <code className="font-mono">{'{{run.output.*}}'}</code> to insert values produced by
          the previous step.
        </span>
      </label>
    </div>
  );
}
