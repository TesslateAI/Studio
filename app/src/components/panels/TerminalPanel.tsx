import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { SearchAddon } from '@xterm/addon-search';
import { Plus, X, Search, Wifi, WifiOff } from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import { createTerminalWebSocket } from '../../lib/api';
import { useTheme } from '../../theme/ThemeContext';

interface TerminalPanelProps {
  projectId: string;
}

interface TerminalTab {
  id: string;
  title: string;
  terminal: Terminal;
  fitAddon: FitAddon;
  searchAddon: SearchAddon;
  ws: WebSocket | null;
  isMain: boolean;
  reconnectAttempts: number;
  reconnectTimer: NodeJS.Timeout | null;
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
}

export function TerminalPanel({ projectId }: TerminalPanelProps) {
  const { theme } = useTheme();
  const [tabs, setTabs] = useState<TerminalTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const nextTabNumber = useRef(2);

  // Create a new terminal tab
  const createTab = (isMain: boolean = false) => {
    const tabId = isMain ? 'main' : `shell-${Date.now()}`;
    const tabTitle = isMain ? '⚡ Main' : `Shell ${nextTabNumber.current++}`;

    const terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: 'block',
      cursorWidth: 2,
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', 'Monaco', 'Courier New', monospace",
      fontWeight: '400',
      fontWeightBold: '700',
      lineHeight: 1.2,
      letterSpacing: 0,
      theme: {
        background: theme === 'dark' ? '#0a0a0a' : '#ffffff',
        foreground: theme === 'dark' ? '#e5e7eb' : '#1f2937',
        cursor: theme === 'dark' ? '#f97316' : '#ea580c',
        cursorAccent: theme === 'dark' ? '#000000' : '#ffffff',
        selectionBackground: theme === 'dark' ? 'rgba(249, 115, 22, 0.25)' : 'rgba(234, 88, 12, 0.25)',
        selectionForeground: theme === 'dark' ? '#ffffff' : '#000000',
        // Modern color palette
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
      },
      scrollback: 50000, // Increased for better history
      convertEol: true,
      allowProposedApi: true,
      smoothScrollDuration: 100,
      fastScrollModifier: 'shift',
      fastScrollSensitivity: 5,
      scrollSensitivity: 3,
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);

    const webLinksAddon = new WebLinksAddon();
    terminal.loadAddon(webLinksAddon);

    const searchAddon = new SearchAddon();
    terminal.loadAddon(searchAddon);

    const newTab: TerminalTab = {
      id: tabId,
      title: tabTitle,
      terminal,
      fitAddon,
      searchAddon,
      ws: null,
      isMain,
      reconnectAttempts: 0,
      reconnectTimer: null,
      connectionStatus: 'connecting',
    };

    setTabs(prev => [...prev, newTab]);
    setActiveTabId(tabId);

    return newTab;
  };

  // Initialize first (main) tab on mount
  useEffect(() => {
    const mainTab = createTab(true);
    return () => {
      // Cleanup all tabs on unmount
      // Use setState callback to get current tabs value, avoiding stale closure
      setTabs(currentTabs => {
        currentTabs.forEach(tab => {
          if (tab.reconnectTimer) {
            clearTimeout(tab.reconnectTimer);
          }
          if (tab.ws) {
            tab.ws.close();
          }
          tab.terminal.dispose();
        });
        return []; // Clear tabs array
      });
    };
  }, [projectId]);

  // Handle terminal rendering when active tab changes
  useEffect(() => {
    if (!terminalContainerRef.current || !activeTabId) return;

    const activeTab = tabs.find(tab => tab.id === activeTabId);
    if (!activeTab) return;

    // Hide all terminal divs
    Array.from(terminalContainerRef.current.children).forEach((child) => {
      (child as HTMLElement).style.display = 'none';
    });

    // Find or create terminal div for this tab
    let terminalDiv = terminalContainerRef.current.querySelector(`[data-terminal-id="${activeTab.id}"]`) as HTMLDivElement;

    if (!terminalDiv) {
      // Create new div for this terminal
      terminalDiv = document.createElement('div');
      terminalDiv.setAttribute('data-terminal-id', activeTab.id);
      terminalDiv.style.width = '100%';
      terminalDiv.style.height = '100%';
      terminalContainerRef.current.appendChild(terminalDiv);

      // Open terminal in this div (only once)
      activeTab.terminal.open(terminalDiv);

      // Connect WebSocket if not already connected
      if (!activeTab.ws) {
        connectTerminal(activeTab);
      }
    }

    // Show this terminal
    terminalDiv.style.display = 'block';

    // Fit terminal to container
    setTimeout(() => {
      try {
        activeTab.fitAddon.fit();
      } catch (e) {
        // Ignore fit errors
      }
    }, 0);

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      try {
        activeTab.fitAddon.fit();
      } catch (e) {
        // Ignore resize errors
      }
    });

    resizeObserver.observe(terminalDiv);

    return () => {
      resizeObserver.disconnect();
    };
  }, [activeTabId, tabs]);

  // Connect WebSocket for a terminal tab with auto-reconnect
  const connectTerminal = (tab: TerminalTab, isReconnect: boolean = false) => {
    // Clear any existing reconnect timer
    if (tab.reconnectTimer) {
      clearTimeout(tab.reconnectTimer);
      tab.reconnectTimer = null;
    }

    // Close existing connection if any
    if (tab.ws) {
      tab.ws.close();
      tab.ws = null;
    }

    try {
      const ws = createTerminalWebSocket(projectId);
      tab.ws = ws;

      ws.onopen = () => {
        // Reset reconnect attempts on successful connection
        tab.reconnectAttempts = 0;
        tab.connectionStatus = 'connected';
        setTabs(prev => [...prev]); // Trigger re-render for status indicator

        // Connection established - backend will send scrollback history automatically
        // No need to write connection message, let the shell output speak for itself

        // Send initial terminal size for proper rendering
        const dims = tab.fitAddon.proposeDimensions();
        if (dims) {
          ws.send(JSON.stringify({
            type: 'resize',
            cols: dims.cols,
            rows: dims.rows
          }));
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'output') {
            // Write incremental output - DO NOT clear the terminal
            // The backend sends only new data, not the full buffer
            tab.terminal.write(data.data);
          } else if (data.type === 'attached') {
            tab.terminal.writeln(`\x1b[36m⟳ Attached to pane: ${data.pane_id}\x1b[0m\r\n`);
          } else if (data.type === 'window_created') {
            tab.terminal.writeln(`\x1b[32m✓ Created new shell: ${data.window_name}\x1b[0m\r\n`);
          } else if (data.type === 'error') {
            tab.terminal.writeln(`\r\n\x1b[31m✗ Error: ${data.message}\x1b[0m\r\n`);
          } else if (data.type === 'status') {
            tab.terminal.writeln(`\x1b[36m⟳ ${data.message}\x1b[0m`);
          }
        } catch (e) {
          console.error('Failed to parse message:', e);
          // If parsing fails, write raw data
          tab.terminal.write(event.data);
        }
      };

      ws.onerror = () => {
        tab.connectionStatus = 'error';
        setTabs(prev => [...prev]); // Trigger re-render for status indicator
        tab.terminal.writeln('\r\n\x1b[31m✗ Connection error\x1b[0m\r\n');
      };

      ws.onclose = (event) => {
        tab.ws = null;
        tab.connectionStatus = 'disconnected';
        setTabs(prev => [...prev]); // Trigger re-render for status indicator

        // Attempt to reconnect with fixed delay
        const maxAttempts = 10;
        const delay = 10000;

        if (tab.reconnectAttempts < maxAttempts) {
          tab.reconnectAttempts++;

          tab.terminal.writeln('');
          tab.terminal.writeln(`\x1b[33m⚠ Connection lost. Reconnecting in ${delay / 1000}s... (${tab.reconnectAttempts}/${maxAttempts})\x1b[0m`);

          tab.connectionStatus = 'connecting';
          setTabs(prev => [...prev]); // Update status

          tab.reconnectTimer = setTimeout(() => {
            connectTerminal(tab, true);
          }, delay);
        } else {
          tab.connectionStatus = 'error';
          setTabs(prev => [...prev]); // Update status

          tab.terminal.writeln('');
          tab.terminal.writeln('\x1b[31m✗ Unable to reconnect. Please refresh the page.\x1b[0m');
        }
      };

      // Handle user input
      tab.terminal.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'input',
            data: data
          }));
        }
      });

      // Handle terminal resize
      tab.terminal.onResize((dimensions) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: 'resize',
            cols: dimensions.cols,
            rows: dimensions.rows
          }));
        }
      });

    } catch (err) {
      console.error('Failed to connect WebSocket:', err);
      tab.terminal.writeln('\x1b[31m✗ Failed to establish connection\x1b[0m');

      // Retry connection
      if (tab.reconnectAttempts < 10) {
        tab.reconnectAttempts++;
        tab.reconnectTimer = setTimeout(() => {
          connectTerminal(tab, true);
        }, 2000);
      }
    }
  };

  // Close a tab
  const closeTab = (tabId: string) => {
    const tab = tabs.find(t => t.id === tabId);
    if (!tab) return;

    // Don't allow closing the main tab
    if (tab.isMain) return;

    // Clear reconnect timer
    if (tab.reconnectTimer) {
      clearTimeout(tab.reconnectTimer);
    }

    // Close WebSocket connection
    if (tab.ws) {
      tab.ws.close();
    }

    // Dispose terminal
    tab.terminal.dispose();

    // Remove from tabs array
    const newTabs = tabs.filter(t => t.id !== tabId);
    setTabs(newTabs);

    // Switch to main tab if closing active tab
    if (activeTabId === tabId) {
      setActiveTabId(newTabs[0]?.id || null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[var(--surface)] rounded-lg overflow-hidden shadow-xl border border-[var(--sidebar-border)]">
      {/* Tab Bar - Improved with better mobile support */}
      <div className="flex items-center gap-1 px-2 py-2 bg-[var(--bg-dark)] border-b border-[var(--sidebar-border)] overflow-x-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-transparent">
        <div className="flex items-center gap-1 min-w-0">
          {tabs.map(tab => {
            const getStatusIcon = () => {
              switch (tab.connectionStatus) {
                case 'connected':
                  return <Wifi size={12} className="text-green-500" />;
                case 'connecting':
                  return <Wifi size={12} className="text-yellow-500 animate-pulse" />;
                case 'disconnected':
                case 'error':
                  return <WifiOff size={12} className="text-red-500" />;
              }
            };

            return (
              <div
                key={tab.id}
                className={`
                  group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
                  transition-all duration-200 min-w-fit
                  ${activeTabId === tab.id
                    ? 'bg-gradient-to-r from-orange-500/20 to-orange-600/20 text-orange-500 shadow-md border border-orange-500/30'
                    : 'bg-[var(--surface)] text-[var(--text)]/60 hover:bg-[var(--sidebar-hover)] hover:text-[var(--text)] border border-transparent'
                  }
                `}
                onClick={() => setActiveTabId(tab.id)}
              >
                {getStatusIcon()}
                <span className={`text-sm font-medium whitespace-nowrap ${activeTabId === tab.id ? 'font-semibold' : ''}`}>
                  {tab.title}
                </span>
                {!tab.isMain && (
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
            );
          })}
        </div>

        {/* New Shell Button - Mobile friendly */}
        <button
          onClick={() => createTab(false)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg ml-auto
                   bg-[var(--surface)] text-[var(--text)]/70 hover:bg-orange-500/10 hover:text-orange-500
                   transition-all duration-200 min-w-fit border border-[var(--sidebar-border)] hover:border-orange-500/30"
          aria-label="New shell"
        >
          <Plus size={16} className="flex-shrink-0" />
          <span className="text-sm font-medium hidden sm:inline">New Shell</span>
        </button>
      </div>

      {/* Terminal Content - Better padding and overflow handling */}
      <div
        ref={terminalContainerRef}
        className="flex-1 p-3 overflow-hidden"
        style={{ minHeight: 0, minWidth: 0 }}
      />

      {/* Info Footer - More compact on mobile */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-[#1a1a1a] to-[#151515] border-t border-white/[0.08]">
        <p className="text-xs text-gray-500 hidden sm:block">
          💡 Type <code className="px-1 py-0.5 bg-black/30 rounded text-orange-500 font-mono">dev-server</code> to control your app (logs, stop, restart). Dev server runs in background.
        </p>
        <p className="text-xs text-gray-500 sm:hidden">
          💡 Type <code className="px-1 py-0.5 bg-black/30 rounded text-orange-500 font-mono">dev-server</code> for commands
        </p>
      </div>
    </div>
  );
}
