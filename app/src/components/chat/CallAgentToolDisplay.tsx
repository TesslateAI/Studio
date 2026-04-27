/**
 * Drill-in renderer for the ``call_agent`` tool call.
 *
 * Distinct from the in-process ``task`` tool (which spawns ephemeral
 * specialist subagents inside the agent process and returns its full
 * trajectory inline). ``call_agent`` invokes another *configured*
 * marketplace agent through the worker; its full trajectory lives on a
 * disposable ``Chat`` row tagged ``is_delegated_run=true``. This panel
 * surfaces:
 *
 *   - The delegated agent's slug + duration so the user sees who answered.
 *   - The final assistant output verbatim (already returned by the tool).
 *   - The delegated chat / task ids, so an audit-minded user can find
 *     the full trajectory manually until a richer drill-in lands.
 *
 * The legacy ``ToolCallDisplay`` renders a generic card; this component
 * intercepts ``name === 'call_agent'`` and renders a focused card with
 * the orange ``--primary`` accent (matches the agent kind in the picker).
 */
import { useState } from 'react';
import { CaretDown, CaretRight, Robot, WarningCircle, CheckCircle } from '@phosphor-icons/react';

import { type ToolCallDetail } from '../../types/agent';

interface Props {
  toolCall: ToolCallDetail;
}

interface CallAgentResultPayload {
  ok?: boolean;
  output?: string;
  agent_slug?: string;
  sub_chat_id?: string;
  sub_task_id?: string;
  duration_seconds?: number;
  error?: string;
  error_message?: string;
  message?: string;
  suggestion?: string;
}

export function CallAgentToolDisplay({ toolCall }: Props) {
  const [expanded, setExpanded] = useState(true);

  const params = toolCall.parameters as { agent_id?: string; message?: string };
  // Result shape: tool wraps {success, tool, result: <executor output>} —
  // the executor's actual return is on result.result.
  const rawResult = (toolCall.result as { result?: unknown } | undefined)?.result;
  const payload: CallAgentResultPayload = (rawResult ?? {}) as CallAgentResultPayload;

  const ok = payload.ok === true;
  const output = (payload.output ?? '').trim();
  const agentSlug = payload.agent_slug ?? params.agent_id ?? 'agent';
  const subChatId = payload.sub_chat_id;
  const subTaskId = payload.sub_task_id;
  const duration = payload.duration_seconds;

  const headline = ok
    ? `@${agentSlug} replied${typeof duration === 'number' ? ` · ${duration.toFixed(2)}s` : ''}`
    : `@${agentSlug} failed${typeof duration === 'number' ? ` · ${duration.toFixed(2)}s` : ''}`;

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{
        borderColor: 'var(--primary)',
        background: 'rgb(from var(--primary) r g b / 0.06)',
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-[var(--primary)]/10 text-left"
      >
        {expanded ? (
          <CaretDown size={12} weight="bold" className="text-[var(--primary)]" />
        ) : (
          <CaretRight size={12} weight="bold" className="text-[var(--primary)]" />
        )}
        <Robot size={14} weight="fill" className="text-[var(--primary)]" />
        <span className="text-xs font-semibold text-[var(--primary)] flex-1 truncate">
          {headline}
        </span>
        {ok ? (
          <CheckCircle size={14} weight="fill" className="text-[var(--status-success)]" />
        ) : (
          <WarningCircle size={14} weight="fill" className="text-[var(--status-error)]" />
        )}
      </button>

      {expanded && (
        <div className="px-3 py-2 text-sm text-[var(--text)] space-y-2">
          {params.message ? (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-0.5">
                Sent to delegated agent
              </div>
              <div className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs whitespace-pre-wrap">
                {params.message}
              </div>
            </div>
          ) : null}

          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-0.5">
              {ok ? 'Reply' : 'Error'}
            </div>
            <div className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs whitespace-pre-wrap">
              {ok
                ? output || '(empty reply)'
                : payload.error_message || payload.error || payload.message || 'Unknown error'}
              {!ok && payload.suggestion ? (
                <div className="mt-1 text-[var(--text-muted)] italic">
                  {payload.suggestion}
                </div>
              ) : null}
            </div>
          </div>

          {(subChatId || subTaskId) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-[10px] text-[var(--text-muted)] font-mono">
              {subChatId ? <span>chat: {subChatId}</span> : null}
              {subTaskId ? <span>task: {subTaskId}</span> : null}
              {/*
                Full-trajectory navigation lands in a follow-up — sub-chats
                are reachable by id today (chat-detail endpoint does not
                filter ``is_delegated_run``), but the chat page selects by
                internal state, not URL. A "View full trajectory" button
                that primes ``currentChatId`` will land alongside that
                wiring.
              */}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
