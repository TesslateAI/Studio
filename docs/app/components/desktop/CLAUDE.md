# Desktop Components

Components that only render inside the Tauri desktop shell in `app/src/components/desktop/`.

## File Index

| File | Purpose |
|------|---------|
| `desktop/TitleBar.tsx` | Custom window chrome for Tauri. Platform-detected (mac / windows / linux) from `navigator.userAgent`. Renders traffic-light buttons on mac, standard minimize/maximize/close on windows/linux. Calls Tauri `window.close`/`minimize`/`maximize` IPC |

## Integration

Rendered conditionally in `App.tsx`:

```tsx
{isTauri && <TitleBar />}
```

The web build does not include Tauri globals so `TitleBar` no-ops outside the desktop shell.

## Related Docs

- `docs/desktop/CLAUDE.md` – full desktop runtime, sidecar, tray integration
- `docs/app/CLAUDE.md` – `config.ts` handles runtime env injection shared between web and desktop
