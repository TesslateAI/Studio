import { useEffect, useRef, useState, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { SearchAddon } from '@xterm/addon-search';
import { Plus, X } from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import { getTerminalTargets, createTerminalWebSocket } from '../../lib/api';
import { useTheme } from '../../theme/ThemeContext';

interface TerminalPanelProps {
  projectId: string; // project slug (used for API calls)
  projectUuid?: string; // stable UUID (used for localStorage key)
}

type TabState = 'selecting' | 'provisioning' | 'select_container' | 'connected' | 'disconnected';

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

interface TerminalTab {
  id: string;
  title: string;
  terminal: Terminal;
  fitAddon: FitAddon;
  searchAddon: SearchAddon;
  ws: WebSocket | null;
  state: TabState;
  targetId: string | null;
  reconnectAttempts: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  inputBuffer: string;
  targets: TerminalTarget[];
  actions: TerminalAction[];
  needsInitialMenu: boolean;
}

const MAX_RECONNECT = 3;
const RECONNECT_DELAY = 2000;
const RECONNECT_STABLE_MS = 3000;

function persistTabs(projectId: string, currentTabs: TerminalTab[]) {
  const key = `tesslate-terminals-${projectId}`;
  const data = currentTabs
    .filter((t) => t.targetId && !t.targetId.startsWith('ephemeral'))
    .map((t) => ({ targetId: t.targetId!, title: t.title }));
  if (data.length > 0) {
    localStorage.setItem(key, JSON.stringify(data));
  } else {
    localStorage.removeItem(key);
  }
}

export function TerminalPanel({ projectId, projectUuid }: TerminalPanelProps) {
  const { theme } = useTheme();
  const [tabs, setTabs] = useState<TerminalTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const nextTabNumber = useRef(1);
  const currentProjectIdRef = useRef(projectId);
  currentProjectIdRef.current = projectId;
  const storageKey = projectUuid ?? projectId;
  const storageKeyRef = useRef(storageKey);
  storageKeyRef.current = storageKey;
  const tabsRef = useRef<TerminalTab[]>([]);
  tabsRef.current = tabs;

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
  function renderMenu(
    term: Terminal,
    options: { label: string; detail?: string }[],
    defaultIdx: number,
    header?: string
  ) {
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
  }

  function renderDisconnectMenu(term: Terminal, reason: string) {
    term.write('\r\n\r\n');
    term.write(`\x1b[31m✗ ${reason}\x1b[0m\r\n\r\n`);
    term.write('What would you like to do?\r\n');
    term.write('  [\x1b[1m1\x1b[0m] Reconnect — same target \x1b[2m(default)\x1b[0m\r\n');
    term.write('  [\x1b[1m2\x1b[0m] New session — pick a target\r\n');
    term.write('  [\x1b[1m3\x1b[0m] Close tab\r\n');
    term.write('\r\nEnter selection [default: 1]: ');
  }

  function renderSelectContainerMenu(term: Terminal, targets: TerminalTarget[], elapsed: string) {
    term.write('\r\n\r\n');
    term.write(`\x1b[32m✓ Environment ready (${elapsed})\x1b[0m\r\n\r\n`);
    term.write('Connect to:\r\n');
    targets.forEach((t, i) => {
      const portStr = t.port ? `port ${t.port}` : '';
      term.write(`  [\x1b[1m${i + 1}\x1b[0m] ${t.name} \x1b[2m— ${portStr}\x1b[0m\r\n`);
    });
    term.write(`\r\nEnter selection [default: 1]: `);
  }

  // -----------------------------------------------------------------------
  // Tab creation
  // -----------------------------------------------------------------------
  const createTab = useCallback(() => {
    const tabId = `term-${Date.now()}`;
    const tabNum = nextTabNumber.current++;
    const tabTitle = tabNum === 1 ? 'Terminal' : `Terminal ${tabNum}`;

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

    const tab: TerminalTab = {
      id: tabId,
      title: tabTitle,
      terminal,
      fitAddon,
      searchAddon,
      ws: null,
      state: 'selecting',
      targetId: null,
      reconnectAttempts: 0,
      reconnectTimer: null,
      inputBuffer: '',
      targets: [],
      actions: [],
      needsInitialMenu: true,
    };

    setTabs((prev) => [...prev, tab]);
    setActiveTabId(tabId);

    return tab;
  }, [theme]);

  // -----------------------------------------------------------------------
  // Tab restoration (from localStorage)
  // -----------------------------------------------------------------------
  const restoreTab = useCallback(
    (targetId: string, title: string) => {
      const tabId = `term-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const tabNum = nextTabNumber.current++;
      const tabTitle = title || (tabNum === 1 ? 'Terminal' : `Terminal ${tabNum}`);

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

      const tab: TerminalTab = {
        id: tabId,
        title: tabTitle,
        terminal,
        fitAddon,
        searchAddon,
        ws: null,
        state: 'provisioning',
        targetId,
        reconnectAttempts: 0,
        reconnectTimer: null,
        inputBuffer: '',
        targets: [],
        actions: [],
        needsInitialMenu: false,
      };

      setTabs((prev) => [...prev, tab]);
      setActiveTabId((prev) => prev ?? tabId);

      // Auto-connect after terminal mounts
      setTimeout(() => connectToTarget(tab, targetId), 50);
      return tab;
    },
    [theme]
  );

  // -----------------------------------------------------------------------
  // Fetch targets & show selection menu
  // -----------------------------------------------------------------------
  async function fetchAndShowMenu(tab: TerminalTab) {
    tab.state = 'selecting';
    tab.inputBuffer = '';
    try {
      const data = await getTerminalTargets(currentProjectIdRef.current);
      tab.targets = data.targets || [];
      tab.actions = data.actions || [];
    } catch {
      tab.targets = [];
      tab.actions = [
        { id: 'ephemeral', name: 'Ephemeral Shell', description: 'lightweight pod, ~2s' },
        { id: 'environment', name: 'Start Environment', description: 'full dev server, ~10s' },
      ];
    }

    const options = [
      ...tab.targets.map((t) => ({
        label: `${t.name} \x1b[32m●\x1b[0m running`,
        detail: t.port ? `port ${t.port}` : undefined,
      })),
      ...tab.actions.map((a) => ({
        label: a.name,
        detail: a.description,
      })),
    ];

    if (options.length === 0) {
      tab.terminal.write('\r\nNo targets available.\r\n');
      return;
    }

    renderMenu(tab.terminal, options, 0, 'Tesslate Terminal');
    setTabs((prev) => [...prev]);
  }

  // -----------------------------------------------------------------------
  // Handle local keystroke during SELECTING / SELECT_CONTAINER / DISCONNECTED
  // -----------------------------------------------------------------------
  function handleLocalInput(tab: TerminalTab, data: string) {
    for (const ch of data) {
      if (ch === '\r' || ch === '\n') {
        const input = tab.inputBuffer.trim();
        tab.terminal.write('\r\n');

        if (tab.state === 'selecting') {
          const allOptions = [...tab.targets, ...tab.actions];
          const idx = input === '' ? 0 : parseInt(input, 10) - 1;
          if (isNaN(idx) || idx < 0 || idx >= allOptions.length) {
            tab.terminal.write('\x1b[31mInvalid selection.\x1b[0m\r\n');
            tab.inputBuffer = '';
            return;
          }
          const selected = allOptions[idx];
          const targetId = selected.id;
          tab.targetId = targetId;
          tab.title = 'name' in selected ? selected.name : 'Terminal';
          setTabs((prev) => [...prev]);
          connectToTarget(tab, targetId);
        } else if (tab.state === 'select_container') {
          const idx = input === '' ? 0 : parseInt(input, 10) - 1;
          if (isNaN(idx) || idx < 0 || idx >= tab.targets.length) {
            tab.terminal.write('\x1b[31mInvalid selection.\x1b[0m\r\n');
            tab.inputBuffer = '';
            return;
          }
          const selected = tab.targets[idx];
          tab.targetId = selected.id;
          tab.title = selected.name;
          setTabs((prev) => [...prev]);
          if (tab.ws && tab.ws.readyState === WebSocket.OPEN) {
            tab.ws.send(JSON.stringify({ type: 'select', target_id: selected.id }));
          }
        } else if (tab.state === 'disconnected') {
          const choice = input === '' ? 1 : parseInt(input, 10);
          if (choice === 1 && tab.targetId) {
            connectToTarget(tab, tab.targetId);
          } else if (choice === 2) {
            fetchAndShowMenu(tab);
          } else if (choice === 3) {
            closeTab(tab.id);
          }
        }
        tab.inputBuffer = '';
      } else if (ch === '\x7f' || ch === '\b') {
        if (tab.inputBuffer.length > 0) {
          tab.inputBuffer = tab.inputBuffer.slice(0, -1);
          tab.terminal.write('\b \b');
        }
      } else if (ch >= ' ') {
        tab.inputBuffer += ch;
        tab.terminal.write(ch);
      }
    }
  }

  // -----------------------------------------------------------------------
  // Connect to a target via WebSocket
  // -----------------------------------------------------------------------
  function connectToTarget(tab: TerminalTab, targetId: string) {
    if (tab.ws) {
      tab.ws.close();
      tab.ws = null;
    }

    tab.state = 'provisioning';
    tab.inputBuffer = '';
    setTabs((prev) => [...prev]);

    const token = localStorage.getItem('token') || '';
    const ws = createTerminalWebSocket(currentProjectIdRef.current, targetId, token);
    tab.ws = ws;

    let connectedAt = 0;
    let gotOutput = false;
    const provisionStartTime = Date.now();

    ws.onopen = () => {
      // Wait for ready/provisioning messages
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'provisioning') {
          tab.state = 'provisioning';
          tab.terminal.write(`\r\x1b[K\x1b[33m⟳ ${msg.message}\x1b[0m`);
          setTabs((prev) => [...prev]);
        } else if (msg.type === 'select_container') {
          tab.state = 'select_container';
          tab.targets = msg.targets || [];
          const elapsed = ((Date.now() - provisionStartTime) / 1000).toFixed(1);
          renderSelectContainerMenu(tab.terminal, tab.targets, `${elapsed}s`);
          setTabs((prev) => [...prev]);
        } else if (msg.type === 'ready') {
          tab.terminal.write('\r\n');
          tab.state = 'connected';
          connectedAt = Date.now();
          gotOutput = false; // reset per-connection
          setTabs((prev) => [...prev]);
          persistTabs(storageKeyRef.current, tabsRef.current);
        } else if (msg.type === 'output') {
          gotOutput = true;
          tab.terminal.write(msg.data);
        } else if (msg.type === 'error') {
          tab.terminal.write(`\r\n\x1b[31m[ERROR] ${msg.message}\x1b[0m\r\n`);
        }
      } catch {
        tab.terminal.write(event.data);
      }
    };

    ws.onclose = () => {
      tab.ws = null;
      const wasConnected = tab.state === 'connected';
      const wasStable =
        wasConnected &&
        connectedAt > 0 &&
        Date.now() - connectedAt >= RECONNECT_STABLE_MS &&
        gotOutput;

      // Stable connection means a real session was active — reset retry counter
      if (wasStable) {
        tab.reconnectAttempts = 0;
      }

      if (tab.state === 'provisioning' || tab.state === 'select_container') {
        tab.state = 'disconnected';
        renderDisconnectMenu(tab.terminal, 'Connection lost during provisioning.');
        setTabs((prev) => [...prev]);
        return;
      }

      // Silent reconnect attempts
      if (wasConnected && tab.reconnectAttempts < MAX_RECONNECT) {
        tab.reconnectAttempts++;
        tab.reconnectTimer = setTimeout(() => {
          if (tab.targetId) {
            connectToTarget(tab, tab.targetId);
          }
        }, RECONNECT_DELAY);
        return;
      }

      tab.state = 'disconnected';
      const reason = wasConnected ? 'Session ended — connection lost.' : 'Connection failed.';
      renderDisconnectMenu(tab.terminal, reason);
      setTabs((prev) => [...prev]);
    };

    ws.onerror = () => {
      // onclose will fire after
    };
  }

  // -----------------------------------------------------------------------
  // Close tab
  // -----------------------------------------------------------------------
  function closeTab(tabId: string) {
    setTabs((prev) => {
      const tab = prev.find((t) => t.id === tabId);
      if (tab) {
        if (tab.reconnectTimer) clearTimeout(tab.reconnectTimer);
        if (tab.ws) tab.ws.close();
        tab.terminal.dispose();
      }
      const next = prev.filter((t) => t.id !== tabId);
      if (activeTabId === tabId) {
        setActiveTabId(next[0]?.id || null);
      }
      // Persist after updater returns via microtask (updaters must be pure)
      queueMicrotask(() => persistTabs(storageKeyRef.current, next));
      return next;
    });
  }

  // -----------------------------------------------------------------------
  // Lifecycle: create first tab on mount / projectId change
  // -----------------------------------------------------------------------
  useEffect(() => {
    const cleanup = () => {
      setTabs((current) => {
        current.forEach((tab) => {
          if (tab.reconnectTimer) clearTimeout(tab.reconnectTimer);
          if (tab.ws) tab.ws.close();
          tab.terminal.dispose();
        });
        return [];
      });
      setActiveTabId(null);
    };
    cleanup();
    nextTabNumber.current = 1;

    // Try restoring tabs from localStorage
    const saved = localStorage.getItem(`tesslate-terminals-${storageKey}`);
    if (saved) {
      try {
        const entries = JSON.parse(saved) as { targetId: string; title: string }[];
        if (entries.length > 0) {
          entries.forEach((entry) => restoreTab(entry.targetId, entry.title));
          return cleanup;
        }
      } catch {
        /* fall through to default */
      }
    }

    createTab();
    return cleanup;
  }, [projectId]);

  // -----------------------------------------------------------------------
  // Terminal rendering when active tab changes
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!terminalContainerRef.current || !activeTabId) return;
    const activeTab = tabs.find((t) => t.id === activeTabId);
    if (!activeTab) return;

    Array.from(terminalContainerRef.current.children).forEach((child) => {
      (child as HTMLElement).style.display = 'none';
    });

    let termDiv = terminalContainerRef.current.querySelector(
      `[data-terminal-id="${activeTab.id}"]`
    ) as HTMLDivElement | null;

    if (!termDiv) {
      termDiv = document.createElement('div');
      termDiv.setAttribute('data-terminal-id', activeTab.id);
      termDiv.style.width = '100%';
      termDiv.style.height = '100%';
      terminalContainerRef.current.appendChild(termDiv);
      activeTab.terminal.open(termDiv);

      // Wire up onData for local input capture + connected passthrough
      activeTab.terminal.onData((data) => {
        if (
          activeTab.state === 'selecting' ||
          activeTab.state === 'select_container' ||
          activeTab.state === 'disconnected'
        ) {
          handleLocalInput(activeTab, data);
        } else if (activeTab.state === 'connected' && activeTab.ws?.readyState === WebSocket.OPEN) {
          activeTab.ws.send(JSON.stringify({ type: 'input', data }));
        }
      });

      activeTab.terminal.onResize(({ cols, rows }) => {
        if (activeTab.ws?.readyState === WebSocket.OPEN) {
          activeTab.ws.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
      });
    }

    termDiv.style.display = 'block';
    requestAnimationFrame(() => {
      try {
        activeTab.fitAddon.fit();
      } catch {
        /* ignore */
      }
      if (activeTab.needsInitialMenu) {
        activeTab.needsInitialMenu = false;
        fetchAndShowMenu(activeTab);
      }
    });

    let resizeTimeout: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        try {
          activeTab.fitAddon.fit();
        } catch {
          /* ignore */
        }
        if (
          activeTab.state === 'selecting' &&
          (activeTab.targets.length > 0 || activeTab.actions.length > 0)
        ) {
          const opts = [
            ...activeTab.targets.map((t) => ({
              label: `${t.name} \x1b[32m●\x1b[0m running`,
              detail: t.port ? `port ${t.port}` : undefined,
            })),
            ...activeTab.actions.map((a) => ({
              label: a.name,
              detail: a.description,
            })),
          ];
          renderMenu(activeTab.terminal, opts, 0, 'Tesslate Terminal');
          if (activeTab.inputBuffer) {
            activeTab.terminal.write(activeTab.inputBuffer);
          }
        }
      }, 50);
    });
    observer.observe(termDiv);

    return () => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      observer.disconnect();
    };
  }, [activeTabId, tabs]);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  const getStatusDot = (state: TabState) => {
    switch (state) {
      case 'connected':
        return <span className="w-2 h-2 rounded-full bg-green-500" />;
      case 'provisioning':
      case 'selecting':
      case 'select_container':
        return <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />;
      case 'disconnected':
        return <span className="w-2 h-2 rounded-full bg-red-500" />;
    }
  };

  return (
    <div className="flex flex-col h-full bg-[var(--surface)] rounded-lg overflow-hidden shadow-xl border border-[var(--sidebar-border)]">
      {/* Tab Bar */}
      <div className="flex items-center gap-1 px-2 py-2 bg-[var(--bg-dark)] border-b border-[var(--sidebar-border)] overflow-x-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-transparent">
        <div className="flex items-center gap-1 min-w-0">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={`
                group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
                transition-all duration-200 min-w-fit
                ${
                  activeTabId === tab.id
                    ? 'bg-gradient-to-r from-orange-500/20 to-orange-600/20 text-orange-500 shadow-md border border-orange-500/30'
                    : 'bg-[var(--surface)] text-[var(--text)]/60 hover:bg-[var(--sidebar-hover)] hover:text-[var(--text)] border border-transparent'
                }
              `}
              onClick={() => setActiveTabId(tab.id)}
            >
              {getStatusDot(tab.state)}
              <span
                className={`text-sm font-medium whitespace-nowrap ${activeTabId === tab.id ? 'font-semibold' : ''}`}
              >
                {tab.state === 'selecting' ? 'Select...' : tab.title}
              </span>
              {tabs.length > 1 && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    closeTab(tab.id);
                  }}
                  className="p-1 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 rounded transition-all duration-150"
                  aria-label="Close tab"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          ))}
        </div>

        <button
          onClick={() => createTab()}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg ml-auto
                   bg-[var(--surface)] text-[var(--text)]/70 hover:bg-orange-500/10 hover:text-orange-500
                   transition-all duration-200 min-w-fit border border-[var(--sidebar-border)] hover:border-orange-500/30"
          aria-label="New terminal"
        >
          <Plus size={16} className="flex-shrink-0" />
          <span className="text-sm font-medium hidden sm:inline">New</span>
        </button>
      </div>

      {/* Terminal Content */}
      <div
        ref={terminalContainerRef}
        className="flex-1 p-3 overflow-hidden"
        style={{ minHeight: 0, minWidth: 0 }}
      />
    </div>
  );
}
