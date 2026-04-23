# Custom Hooks

All custom React hooks for OpenSail live in `app/src/hooks/`.

## File Index

| File | Purpose |
|------|---------|
| `hooks/useAuth.ts` | Thin re-export of `useAuth()` from `AuthContext` |
| `hooks/useCancellableRequest.ts` | `useCancellableRequest<T>()` + `useCancellableParallelRequests()`: AbortController-based fetches with mount tracking and silent AbortError/CanceledError handling |
| `hooks/useTask.ts` | `useTask(taskId)`, `useActiveTasks()`, `useTaskPolling(taskId)`: subscribe to and poll background tasks via `taskService` |
| `hooks/useTaskNotifications.ts` | Wires `taskService` WebSocket + toast notifications. Call once in `App.tsx` |
| `hooks/useContainerStartup.ts` | Full container-startup lifecycle: SSE phase/progress/logs, `HEALTH_CHECK_TIMEOUT:` error-prefix protocol, retry, onReady/onError callbacks |
| `hooks/useReferralTracking.ts` | Captures `?ref=CODE` on first visit, stores referrer in sessionStorage, posts to `/api/track-landing` once per session |
| `hooks/useAgentChat.ts` | Standalone chat page: agent message streaming with `overrideChatId` param to avoid stale-closure races; handles SSE event types (text_delta, agent_step, approval_required, complete) |
| `hooks/useChatSessions.ts` | Standalone chat session CRUD with optimistic temp-ID creation (rolls back on error); paginated at limit=30; no search |
| `hooks/useAttachments.ts` | File-drop + paste attachment management for `ChatInput` (image uploads, MIME validation, object URL cleanup) |
| `hooks/useFileTree.ts` | File-tree fetch + caching for `CodeEditor` and Design view; uses `buildFileTree` and `filterFileTree` utilities |
| `hooks/useToolDock.ts` | Tool-dock tab state for the project page: open tabs, active tab, ephemeral vs pinned, open/close/select handlers |

## Design Rules

1. **Prefer `useCancellableRequest` over raw `useEffect + fetch`** – it prevents memory leaks and race conditions automatically.
2. **Memoize callbacks** (`useCallback`) before passing to the hook's `execute` or to dependency arrays.
3. **Don't await `execute`** inside effects – let `onSuccess`/`onError` callbacks handle results.
4. **`useContainerStartup` error prefix**: `HEALTH_CHECK_TIMEOUT:<msg>` triggers the "Ask Agent to start it" UX in `ContainerLoadingOverlay`; any other error string triggers the red error state.
5. **`useAgentChat.sendMessage(msg, overrideChatId?)`** – always pass `overrideChatId` when the session was just created optimistically.

## Key Patterns

### Cancellable effect
```tsx
const { execute } = useCancellableRequest<User[]>();
useEffect(() => {
  execute(
    (signal) => api.getUsers({ signal }),
    { onSuccess: setUsers, onError: (e) => toast.error(e.message) }
  );
}, [execute]);
```

### Parallel loads
```tsx
const { executeAll } = useCancellableParallelRequests();
executeAll(
  [() => api.getProviders(), () => api.getCredentials()],
  { onAllSuccess: ([p, c]) => { setProviders(p); setCreds(c); } }
);
```

### Container startup
```tsx
const { status, phase, progress, logs, error, containerUrl, retry } =
  useContainerStartup(slug, containerId, { onReady, onError });
```

## Related Docs

- `docs/app/contexts/CLAUDE.md` – the providers that hooks consume
- `docs/app/state/task-service.md` – `taskService` singleton that `useTask*` wraps
- `docs/app/components/chat/CLAUDE.md` – how chat hooks compose with chat components
