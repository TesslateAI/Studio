import { useEffect, useRef, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { SearchAddon } from '@xterm/addon-search';
import '@xterm/xterm/css/xterm.css';
import { getTerminalTargets, createTerminalWebSocket } from '../../lib/api';
import { useTheme } from '../../theme/ThemeContext';

interface TerminalPanelProps {
  projectId: string; // project slug (used for API calls)
  projectUuid?: string; // stable UUID (used for localStorage key)
  instanceId?: string; // dock tab id — each dock tab owns its own session
}

type SessionState = 'selecting' | 'provisioning' | 'select_container' | 'connected' | 'disconnected';

interface TerminalTarget {
  id: string;
  name: string;
  type: string;
  status: string;
  port: number | null;
  container_directory: string;
}

interface TerminalAction {
  id: string;
  name: string;
  description: string;
}

const MAX_RECONNECT = 3;
const RECONNECT_DELAY = 2000;
const RECONNECT_STABLE_MS = 3000;

function persistKey(projectKey: string, instanceId: string) {
  return `tesslate-terminal-${projectKey}-${instanceId}`;
}

function loadPersistedTargetId(projectKey: string, instanceId: string): string | null {
  try {
    return localStorage.getItem(persistKey(projectKey, instanceId));
  } catch {
    return null;
  }
}

function persistTargetId(projectKey: string, instanceId: string, targetId: string | null) {
  const key = persistKey(projectKey, instanceId);
  try {
    if (targetId && !targetId.startsWith('ephemeral')) {
      localStorage.setItem(key, targetId);
    } else {
      localStorage.removeItem(key);
    }
  } catch {
    /* ignore quota errors */
  }
}

export function TerminalPanel({ projectId, projectUuid, instanceId = 'default' }: TerminalPanelProps) {
  const { theme } = useTheme();
  const terminalContainerRef = useRef<HTMLDivElement>(null);

  // All session state lives in refs — the terminal is imperative and
  // there's exactly one session per panel instance now, so rerenders add nothing.
  const termRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<SessionState>('selecting');
  const targetIdRef = useRef<string | null>(null);
  const inputBufferRef = useRef<string>('');
  const targetsRef = useRef<TerminalTarget[]>([]);
  const actionsRef = useRef<TerminalAction[]>([]);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentProjectIdRef = useRef(projectId);
  currentProjectIdRef.current = projectId;
  const projectKey = projectUuid ?? projectId;
  const projectKeyRef = useRef(projectKey);
  projectKeyRef.current = projectKey;
  const instanceIdRef = useRef(instanceId);
  instanceIdRef.current = instanceId;

  // -----------------------------------------------------------------------
  // Terminal theme
  // -----------------------------------------------------------------------
  const termTheme = {
    background: theme === 'dark' ? '#0a0a0a' : '#ffffff',
    foreground: theme === 'dark' ? '#e5e7eb' : '#1f2937',
    cursor: theme === 'dark' ? '#f97316' : '#ea580c',
    cursorAccent: theme === 'dark' ? '#000000' : '#ffffff',
    selectionBackground: theme === 'dark' ? 'rgba(249,115,22,0.25)' : 'rgba(234,88,12,0.25)',
    selectionForeground: theme === 'dark' ? '#ffffff' : '#000000',
    black: '#1f2937',
    red: '#ef4444',
    green: '#10b981',
    yellow: '#f59e0b',
    blue: '#3b82f6',
    magenta: '#a855f7',
    cyan: '#06b6d4',
    white: '#e5e7eb',
    brightBlack: '#6b7280',
    brightRed: '#f87171',
    brightGreen: '#34d399',
    brightYellow: '#fbbf24',
    brightBlue: '#60a5fa',
    brightMagenta: '#c084fc',
    brightCyan: '#22d3ee',
    brightWhite: '#f9fafb',
  };

  // -----------------------------------------------------------------------
  // Menu rendering
  // -----------------------------------------------------------------------
  const renderMenu = useCallback(
    (options: { label: string; detail?: string }[], defaultIdx: number, header?: string) => {
      const term = termRef.current;
      if (!term) return;
      term.write('\x1b[2J\x1b[H'); // clear
      if (header) {
        term.write(`\x1b[38;5;208m╔${'═'.repeat(38)}╗\x1b[0m\r\n`);
        term.write(`\x1b[38;5;208m║   ${header.padEnd(35)}║\x1b[0m\r\n`);
        term.write(`\x1b[38;5;208m╚${'═'.repeat(38)}╝\x1b[0m\r\n\r\n`);
      }
      term.write('Select a terminal target:\r\n\r\n');
      options.forEach((opt, i) => {
        const num = i + 1;
        const def = i === defaultIdx ? ' \x1b[2m(default)\x1b[0m' : '';
        const detail = opt.detail ? ` \x1b[2m— ${opt.detail}\x1b[0m` : '';
        term.write(`  [\x1b[1m${num}\x1b[0m] ${opt.label}${detail}${def}\r\n`);
      });
      term.write(`\r\nEnter selection [default: ${defaultIdx + 1}]: `);
    },
    []
  );

  const renderDisconnectMenu = useCallback((reason: string) => {
    const term = termRef.current;
    if (!term) return;
    term.write('\r\n\r\n');
    term.write(`\x1b[31m✗ ${reason}\x1b[0m\r\n\r\n`);
    term.write('What would you like to do?\r\n');
    term.write('  [\x1b[1m1\x1b[0m] Reconnect — same target \x1b[2m(default)\x1b[0m\r\n');
    term.write('  [\x1b[1m2\x1b[0m] New session — pick a target\r\n');
    term.write('\r\nEnter selection [default: 1]: ');
  }, []);

  const renderSelectContainerMenu = useCallback(
    (targets: TerminalTarget[], elapsed: string) => {
      const term = termRef.current;
      if (!term) return;
      term.write('\r\n\r\n');
      term.write(`\x1b[32m✓ Environment ready (${elapsed})\x1b[0m\r\n\r\n`);
      term.write('Connect to:\r\n');
      targets.forEach((t, i) => {
        const portStr = t.port ? `port ${t.port}` : '';
        term.write(`  [\x1b[1m${i + 1}\x1b[0m] ${t.name} \x1b[2m— ${portStr}\x1b[0m\r\n`);
      });
      term.write(`\r\nEnter selection [default: 1]: `);
    },
    []
  );

  // -----------------------------------------------------------------------
  // Fetch targets & show selection menu
  // -----------------------------------------------------------------------
  const fetchAndShowMenu = useCallback(async () => {
    stateRef.current = 'selecting';
    inputBufferRef.current = '';
    try {
      const data = await getTerminalTargets(currentProjectIdRef.current);
      targetsRef.current = data.targets || [];
      actionsRef.current = data.actions || [];
    } catch {
      targetsRef.current = [];
      actionsRef.current = [
        { id: 'ephemeral', name: 'Ephemeral Shell', description: 'lightweight pod, ~2s' },
        { id: 'environment', name: 'Start Environment', description: 'full dev server, ~10s' },
      ];
    }

    const options = [
      ...targetsRef.current.map((t) => ({
        label: `${t.name} \x1b[32m●\x1b[0m running`,
        detail: t.port ? `port ${t.port}` : undefined,
      })),
      ...actionsRef.current.map((a) => ({
        label: a.name,
        detail: a.description,
      })),
    ];

    if (options.length === 0) {
      termRef.current?.write('\r\nNo targets available.\r\n');
      return;
    }

    renderMenu(options, 0, 'Tesslate Terminal');
  }, [renderMenu]);

  // -----------------------------------------------------------------------
  // Connect to a target via WebSocket
  // -----------------------------------------------------------------------
  const connectToTarget = useCallback(
    (targetId: string) => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      stateRef.current = 'provisioning';
      inputBufferRef.current = '';
      targetIdRef.current = targetId;

      const token = localStorage.getItem('token') || '';
      const ws = createTerminalWebSocket(currentProjectIdRef.current, targetId, token);
      wsRef.current = ws;

      let connectedAt = 0;
      let gotOutput = false;
      const provisionStartTime = Date.now();

      ws.onopen = () => {
        // Wait for ready/provisioning messages
      };

      ws.onmessage = (event) => {
        const term = termRef.current;
        if (!term) return;
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'provisioning') {
            stateRef.current = 'provisioning';
            term.write(`\r\x1b[K\x1b[33m⟳ ${msg.message}\x1b[0m`);
          } else if (msg.type === 'select_container') {
            stateRef.current = 'select_container';
            targetsRef.current = msg.targets || [];
            const elapsed = ((Date.now() - provisionStartTime) / 1000).toFixed(1);
            renderSelectContainerMenu(targetsRef.current, `${elapsed}s`);
          } else if (msg.type === 'ready') {
            term.write('\r\n');
            stateRef.current = 'connected';
            connectedAt = Date.now();
            gotOutput = false;
            persistTargetId(projectKeyRef.current, instanceIdRef.current, targetIdRef.current);
          } else if (msg.type === 'output') {
            gotOutput = true;
            term.write(msg.data);
          } else if (msg.type === 'error') {
            term.write(`\r\n\x1b[31m[ERROR] ${msg.message}\x1b[0m\r\n`);
          }
        } catch {
          term.write(event.data);
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        const wasConnected = stateRef.current === 'connected';
        const wasStable =
          wasConnected &&
          connectedAt > 0 &&
          Date.now() - connectedAt >= RECONNECT_STABLE_MS &&
          gotOutput;

        if (wasStable) {
          reconnectAttemptsRef.current = 0;
        }

        if (
          stateRef.current === 'provisioning' ||
          stateRef.current === 'select_container'
        ) {
          stateRef.current = 'disconnected';
          renderDisconnectMenu('Connection lost during provisioning.');
          return;
        }

        // Silent reconnect attempts
        if (wasConnected && reconnectAttemptsRef.current < MAX_RECONNECT) {
          reconnectAttemptsRef.current++;
          reconnectTimerRef.current = setTimeout(() => {
            if (targetIdRef.current) {
              connectToTarget(targetIdRef.current);
            }
          }, RECONNECT_DELAY);
          return;
        }

        stateRef.current = 'disconnected';
        const reason = wasConnected ? 'Session ended — connection lost.' : 'Connection failed.';
        renderDisconnectMenu(reason);
      };

      ws.onerror = () => {
        // onclose will fire after
      };
    },
    [renderDisconnectMenu, renderSelectContainerMenu]
  );

  // -----------------------------------------------------------------------
  // Handle local keystroke during SELECTING / SELECT_CONTAINER / DISCONNECTED
  // -----------------------------------------------------------------------
  const handleLocalInput = useCallback(
    (data: string) => {
      const term = termRef.current;
      if (!term) return;
      for (const ch of data) {
        if (ch === '\r' || ch === '\n') {
          const input = inputBufferRef.current.trim();
          term.write('\r\n');

          if (stateRef.current === 'selecting') {
            const allOptions = [...targetsRef.current, ...actionsRef.current];
            const idx = input === '' ? 0 : parseInt(input, 10) - 1;
            if (isNaN(idx) || idx < 0 || idx >= allOptions.length) {
              term.write('\x1b[31mInvalid selection.\x1b[0m\r\n');
              inputBufferRef.current = '';
              return;
            }
            const selected = allOptions[idx];
            const targetId = selected.id;
            connectToTarget(targetId);
          } else if (stateRef.current === 'select_container') {
            const idx = input === '' ? 0 : parseInt(input, 10) - 1;
            if (isNaN(idx) || idx < 0 || idx >= targetsRef.current.length) {
              term.write('\x1b[31mInvalid selection.\x1b[0m\r\n');
              inputBufferRef.current = '';
              return;
            }
            const selected = targetsRef.current[idx];
            targetIdRef.current = selected.id;
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'select', target_id: selected.id }));
            }
          } else if (stateRef.current === 'disconnected') {
            const choice = input === '' ? 1 : parseInt(input, 10);
            if (choice === 1 && targetIdRef.current) {
              connectToTarget(targetIdRef.current);
            } else if (choice === 2) {
              persistTargetId(projectKeyRef.current, instanceIdRef.current, null);
              fetchAndShowMenu();
            }
          }
          inputBufferRef.current = '';
        } else if (ch === '\x7f' || ch === '\b') {
          if (inputBufferRef.current.length > 0) {
            inputBufferRef.current = inputBufferRef.current.slice(0, -1);
            term.write('\b \b');
          }
        } else if (ch >= ' ') {
          inputBufferRef.current += ch;
          term.write(ch);
        }
      }
    },
    [connectToTarget, fetchAndShowMenu]
  );

  // -----------------------------------------------------------------------
  // Lifecycle: create terminal on mount, dispose on unmount
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!terminalContainerRef.current) return;

    const terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: 'block',
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      lineHeight: 1.2,
      theme: termTheme,
      scrollback: 50000,
      convertEol: true,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.loadAddon(new WebLinksAddon());
    const searchAddon = new SearchAddon();
    terminal.loadAddon(searchAddon);

    termRef.current = terminal;
    fitAddonRef.current = fitAddon;
    terminal.open(terminalContainerRef.current);

    terminal.onData((data) => {
      if (
        stateRef.current === 'selecting' ||
        stateRef.current === 'select_container' ||
        stateRef.current === 'disconnected'
      ) {
        handleLocalInput(data);
      } else if (
        stateRef.current === 'connected' &&
        wsRef.current?.readyState === WebSocket.OPEN
      ) {
        wsRef.current.send(JSON.stringify({ type: 'input', data }));
      }
    });

    terminal.onResize(({ cols, rows }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    });

    requestAnimationFrame(() => {
      try {
        fitAddon.fit();
      } catch {
        /* ignore */
      }
      const restoredTargetId = loadPersistedTargetId(
        projectKeyRef.current,
        instanceIdRef.current
      );
      if (restoredTargetId) {
        connectToTarget(restoredTargetId);
      } else {
        fetchAndShowMenu();
      }
    });

    let resizeTimeout: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        try {
          fitAddon.fit();
        } catch {
          /* ignore */
        }
        // Re-render selection menu on resize so the layout stays clean
        if (
          stateRef.current === 'selecting' &&
          (targetsRef.current.length > 0 || actionsRef.current.length > 0)
        ) {
          const opts = [
            ...targetsRef.current.map((t) => ({
              label: `${t.name} \x1b[32m●\x1b[0m running`,
              detail: t.port ? `port ${t.port}` : undefined,
            })),
            ...actionsRef.current.map((a) => ({
              label: a.name,
              detail: a.description,
            })),
          ];
          renderMenu(opts, 0, 'Tesslate Terminal');
          if (inputBufferRef.current) {
            termRef.current?.write(inputBufferRef.current);
          }
        }
      }, 50);
    });
    observer.observe(terminalContainerRef.current);

    return () => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      observer.disconnect();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      terminal.dispose();
      termRef.current = null;
      fitAddonRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, instanceId]);

  return (
    <div
      ref={terminalContainerRef}
      className="w-full h-full bg-[var(--bg)] p-3 overflow-hidden"
      style={{ minHeight: 0, minWidth: 0 }}
    />
  );
}
