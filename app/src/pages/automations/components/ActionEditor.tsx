import { useEffect, useRef, useState } from 'react';
import { appActionsApi, marketplaceApi } from '../../../lib/api';
import type {
  AutomationActionIn,
  AutomationActionType,
  AppActionRow,
} from '../../../types/automations';
import { DestinationPicker } from './DestinationPicker';
import { JsonSchemaForm } from './JsonSchemaForm';
import { VariableMenu } from './VariableMenu';

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
  const promptRef = useRef<HTMLTextAreaElement | null>(null);

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

      <div className="block">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-[var(--text)]">Tell the agent what to do</span>
          <VariableMenu
            targetRef={promptRef}
            onInsert={(next) => updateConfig({ prompt: next })}
            groups={[
              {
                label: 'From the trigger event',
                variables: [
                  { token: '{{event.payload}}', help: 'The whole event payload as JSON' },
                  {
                    token: '{{event.payload.field}}',
                    help: 'A specific field — replace "field"',
                  },
                  {
                    token: '{{event.received_at}}',
                    help: 'When the trigger fired (ISO timestamp)',
                  },
                ],
              },
            ]}
          />
        </div>
        <textarea
          ref={promptRef}
          rows={5}
          value={String(value.config.prompt ?? '')}
          onChange={(e) => updateConfig({ prompt: e.target.value })}
          placeholder="Summarize today's pipeline metrics and post the highlights."
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        />
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          Click <em>Insert variable</em> to drop trigger-event data into the prompt.
        </span>
      </div>
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
  const selectedAction = actions?.find((a) => a.id === value.app_action_id) ?? null;

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

      <div>
        <span className="block text-xs font-medium text-[var(--text)] mb-1">Action input</span>
        <JsonSchemaForm
          schema={selectedAction?.input_schema ?? null}
          value={(value.config.input as Record<string, unknown> | string | undefined) ?? {}}
          onChange={(next) =>
            onChange({ ...value, config: { ...(value.config || {}), input: next } })
          }
        />
      </div>
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
  const bodyRef = useRef<HTMLTextAreaElement | null>(null);
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

      <div className="block">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-[var(--text)]">Message to send</span>
          <VariableMenu targetRef={bodyRef} onInsert={(next) => updateConfig({ body: next })} />
        </div>
        <textarea
          ref={bodyRef}
          rows={5}
          value={String(value.config.body ?? '')}
          onChange={(e) => updateConfig({ body: e.target.value })}
          placeholder="Daily summary: {{run.output.summary}}"
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        />
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          Click <em>Insert variable</em> to pull values from the previous step or the trigger event.
        </span>
      </div>
    </div>
  );
}
