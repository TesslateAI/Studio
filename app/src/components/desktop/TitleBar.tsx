import { useState, useCallback } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Platform detection (runs once at module load — stable for the session)
// ─────────────────────────────────────────────────────────────────────────────

type Platform = 'mac' | 'windows' | 'linux';

function detectPlatform(): Platform {
  const ua = navigator.userAgent;
  if (/Mac OS X/.test(ua)) return 'mac';
  if (/Windows NT/.test(ua)) return 'windows';
  return 'linux';
}

const PLATFORM: Platform = detectPlatform();

// ─────────────────────────────────────────────────────────────────────────────
// Tauri invoke shim — avoids adding @tauri-apps/api as a hard npm dep
// ─────────────────────────────────────────────────────────────────────────────

type TauriInternals = {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
};

function getTauriInvoke(): TauriInternals['invoke'] | undefined {
  return (window as unknown as Record<string, unknown> & { __TAURI_INTERNALS__?: TauriInternals })
    .__TAURI_INTERNALS__?.invoke;
}

async function invokeCmd(cmd: string): Promise<void> {
  const invoke = getTauriInvoke();
  if (invoke) await invoke(cmd);
}

// Called on mousedown of the drag region so the OS receives the drag intent
// before any mousemove. WebkitAppRegion CSS alone is unreliable on Linux GTK.
async function startDragging(): Promise<void> {
  const invoke = getTauriInvoke();
  if (invoke) {
    try {
      await invoke('start_dragging');
    } catch {
      // Ignore — window may already be maximised / fullscreen
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// macOS traffic-light button
// ─────────────────────────────────────────────────────────────────────────────

const MAC_COLORS = {
  close: { base: '#FF5F57', hover: '#FF5F57' },
  minimize: { base: '#FEBC2E', hover: '#FEBC2E' },
  maximize: { base: '#28C840', hover: '#28C840' },
};

const MacTrafficLight = ({
  kind,
  onClick,
  showIcon,
}: {
  kind: 'close' | 'minimize' | 'maximize';
  onClick: () => void;
  showIcon: boolean;
}) => {
  const color = MAC_COLORS[kind];

  const icon =
    kind === 'close' ? (
      // × glyph
      <svg width="6" height="6" viewBox="0 0 6 6" fill="none">
        <path d="M1 1L5 5M5 1L1 5" stroke="#4d0000" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    ) : kind === 'minimize' ? (
      // − glyph
      <svg width="6" height="6" viewBox="0 0 6 6" fill="none">
        <path d="M1 3H5" stroke="#5a3a00" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    ) : (
      // ⊞ glyph (two diagonal arrows)
      <svg width="6" height="6" viewBox="0 0 6 6" fill="none">
        <path
          d="M1 1L5 5M3.5 1H5V2.5M1 3.5V5H2.5"
          stroke="#003a1a"
          strokeWidth="1.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );

  return (
    <button
      onClick={onClick}
      style={
        {
          WebkitAppRegion: 'no-drag',
          width: 12,
          height: 12,
          borderRadius: '50%',
          background: color.base,
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          transition: 'opacity 150ms ease',
        } as React.CSSProperties
      }
      aria-label={kind}
    >
      {showIcon && icon}
    </button>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Windows / Linux control button
// ─────────────────────────────────────────────────────────────────────────────

const WinControlButton = ({
  kind,
  onClick,
}: {
  kind: 'minimize' | 'maximize' | 'close';
  onClick: () => void;
}) => {
  const [hovered, setHovered] = useState(false);
  const isClose = kind === 'close';

  const icon =
    kind === 'minimize' ? (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <path d="M2 5H8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    ) : kind === 'maximize' ? (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <rect x="2" y="2" width="6" height="6" rx="0.5" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    ) : (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
        <path
          d="M2.5 2.5L7.5 7.5M7.5 2.5L2.5 7.5"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    );

  return (
    <button
      onClick={onClick}
      // Prevent the title bar's onMouseDown drag from firing when clicking a button
      onMouseDown={(e) => e.stopPropagation()}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={
        {
          WebkitAppRegion: 'no-drag',
          width: 46,
          height: '100%',
          background: hovered
            ? isClose
              ? 'rgba(239, 68, 68, 0.85)'
              : 'var(--sidebar-hover)'
            : 'transparent',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: hovered && isClose ? '#ffffff' : 'var(--text-muted)',
          flexShrink: 0,
          transition: 'background 120ms ease, color 120ms ease',
        } as React.CSSProperties
      }
      aria-label={kind}
    >
      {icon}
    </button>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TitleBar
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Custom window titlebar rendered only inside the Tauri shell.
 * Replaces the native OS titlebar removed via `decorations: false`.
 *
 * - macOS: traffic-light circles on the left, app name centred.
 * - Windows/Linux: app name on the left, win32-style control buttons on the right.
 *
 * All colours come from the active theme's CSS variables so the bar
 * automatically adjusts when the user switches themes.
 */
export function TitleBar() {
  const [macHovered, setMacHovered] = useState(false);

  const handleMinimize = useCallback(() => invokeCmd('minimize_window'), []);
  const handleMaximize = useCallback(() => invokeCmd('toggle_maximize_window'), []);
  const handleClose = useCallback(() => invokeCmd('close_window'), []);

  const titleText = (
    <span
      style={{
        fontSize: 11,
        fontWeight: 500,
        color: 'var(--text-subtle)',
        letterSpacing: '0.02em',
        userSelect: 'none',
        pointerEvents: 'none',
      }}
    >
      OpenSail
    </span>
  );

  // Shared drag mousedown handler — fires the Tauri startDragging API on the
  // primary button so Linux WebKitGTK doesn't have to rely on CSS webkit-app-region.
  const handleDragMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0) {
      e.preventDefault();
      void startDragging();
    }
  }, []);

  if (PLATFORM === 'mac') {
    return (
      <div
        onMouseEnter={() => setMacHovered(true)}
        onMouseLeave={() => setMacHovered(false)}
        onMouseDown={handleDragMouseDown}
        style={
          {
            height: 36,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--sidebar-bg)',
            WebkitAppRegion: 'drag',
            position: 'relative',
            userSelect: 'none',
          } as React.CSSProperties
        }
      >
        {/* Traffic lights on the left */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            paddingLeft: 16,
            paddingRight: 8,
          }}
        >
          <MacTrafficLight kind="close" onClick={handleClose} showIcon={macHovered} />
          <MacTrafficLight kind="minimize" onClick={handleMinimize} showIcon={macHovered} />
          <MacTrafficLight kind="maximize" onClick={handleMaximize} showIcon={macHovered} />
        </div>

        {/* Centred title */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            pointerEvents: 'none',
          }}
        >
          {titleText}
        </div>
      </div>
    );
  }

  // Windows / Linux — full-width bar spanning the entire window top edge.
  // The sidebar sits below this bar, so no sidebar-width spacer is needed.
  return (
    <div
      onMouseDown={handleDragMouseDown}
      style={
        {
          height: 36,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--sidebar-bg)',
          WebkitAppRegion: 'drag',
          userSelect: 'none',
        } as React.CSSProperties
      }
    >
      {/* App name — left-aligned after a small inset */}
      <div style={{ flex: 1, paddingLeft: 12 }}>{titleText}</div>

      {/* Window controls — right side */}
      <div style={{ display: 'flex', alignItems: 'center', height: '100%', flexShrink: 0 }}>
        <WinControlButton kind="minimize" onClick={handleMinimize} />
        <WinControlButton kind="maximize" onClick={handleMaximize} />
        <WinControlButton kind="close" onClick={handleClose} />
      </div>
    </div>
  );
}
