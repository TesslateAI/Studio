# State Management

Singleton services, theme system, and state-related hooks in OpenSail.

## Key Files

| File | Purpose |
|------|---------|
| `app/src/services/taskService.ts` | Background-task WebSocket singleton. Subscribes to `/ws`, dispatches task updates to registered callbacks, auto-reconnect with backoff |
| `app/src/theme/ThemeContext.tsx` | Theme state provider with loading states (`idle`/`loading`/`success`/`error`), `isReady` flag, fallback-on-error |
| `app/src/theme/themePresets.ts` | Theme loading + caching (async from API, client-side cache keyed by id) |
| `app/src/theme/fonts.ts` | Font import + loading helper for typography tokens |
| `app/src/theme/index.ts` | Barrel export (`useTheme`, `useThemeWhenReady`, `ThemeProvider`, types) |
| `app/src/theme/variables.css` | CSS custom properties for light/dark + named presets |
| `app/src/contexts/AuthContext.tsx` | Auth state provider (see `docs/app/contexts/CLAUDE.md`) |
| `app/src/contexts/CommandContext.tsx` | Command dispatch (see `docs/app/contexts/CLAUDE.md`) |
| `app/src/hooks/useTask.ts` | `useTask`, `useActiveTasks`, `useTaskPolling` – read from `taskService` |
| `app/src/hooks/useTaskNotifications.ts` | Wires `taskService` to toast notifications. Call once from `App.tsx` |
| `app/src/hooks/useCancellableRequest.ts` | AbortController-managed fetch lifecycle |
| `app/src/hooks/useContainerStartup.ts` | Container startup lifecycle with `HEALTH_CHECK_TIMEOUT:` prefix protocol |
| `app/src/hooks/useAuth.ts` | Thin wrapper around `useAuth` from AuthContext |
| `app/src/types/theme.ts` | Theme types + runtime validators (`isValidTheme`, `DEFAULT_FALLBACK_THEME`) |

## Related Docs

- `docs/app/contexts/CLAUDE.md` – full context documentation
- `docs/app/hooks/CLAUDE.md` – custom hooks
- `docs/app/types/CLAUDE.md` – theme types + validation
- `docs/app/state/task-service.md` – `taskService` deep dive
- `docs/app/state/theme.md` – theme system internals
- `docs/app/state/hooks.md` – hook patterns

## Patterns

### Theme with loading guard

```tsx
const { themePreset, availablePresets, setThemePreset, isReady } = useTheme();
if (!isReady) return <SkeletonLoader />;
return <ThemePicker themes={availablePresets} selected={themePreset?.id} onChange={setThemePreset} />;
```

### Task polling

```tsx
const { task, isPolling, startPolling } = useTaskPolling();
const create = async () => {
  const { task_id } = await projectsApi.create({ name });
  startPolling(task_id);
};
useEffect(() => {
  if (task?.status === 'completed') navigate(`/project/${task.result.slug}`);
}, [task]);
```

### Cancellable parallel requests

```tsx
const { executeAll } = useCancellableParallelRequests();
executeAll(
  [() => deploymentApi.getProviders(), () => deploymentApi.getCredentials()],
  { onAllSuccess: ([p, c]) => { setProviders(p.data); setCreds(c.data); } }
);
```

### Cross-tab auth sync

`AuthContext` listens to `storage` events so login in one tab updates others. Works automatically as long as tokens use `localStorage` (not `sessionStorage`).

## CSS Variables (excerpt)

| Variable | Purpose |
|----------|---------|
| `--primary` | Brand orange (#F89521) |
| `--primary-hover` | Hover state |
| `--accent` | Accent blue (#00D9FF) |
| `--bg-dark` | Background |
| `--surface` | Elevated surfaces |
| `--text` | Text color |
| `--border-color` | Borders |
| `--status-success`, `--status-info`, `--status-warning`, `--status-error` | Status colors |
| `--radius` | Base border radius (22px) |
| `--ease` | Animation easing |
