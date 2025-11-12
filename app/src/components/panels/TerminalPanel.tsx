import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Plus, X } from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import { createTerminalWebSocket } from '../../lib/api';

interface TerminalPanelProps {
  projectId: string;
}

interface TerminalTab {
  id: string;
  title: string;
  terminal: Terminal;
  fitAddon: FitAddon;
  ws: WebSocket | null;
  isMain: boolean;
  reconnectAttempts: number;
  reconnectTimer: NodeJS.Timeout | null;
}

export function TerminalPanel({ projectId }: TerminalPanelProps) {
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
      fontSize: 14,
      fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
      theme: {
        background: '#0a0a0a',
        foreground: '#e5e5e5',
        cursor: 'var(--primary)',
        cursorAccent: '#000000',
        selection: 'rgba(var(--primary-rgb), 0.3)',
        black: '#000000',
        red: '#ff5555',
        green: '#50fa7b',
        yellow: '#f1fa8c',
        blue: '#bd93f9',
        magenta: '#ff79c6',
        cyan: '#8be9fd',
        white: '#bfbfbf',
        brightBlack: '#4d4d4d',
        brightRed: '#ff6e67',
        brightGreen: '#5af78e',
        brightYellow: '#f4f99d',
        brightBlue: '#caa9fa',
        brightMagenta: '#ff92d0',
        brightCyan: '#9aedfe',
        brightWhite: '#e6e6e6',
      },
      scrollback: 10000,
      convertEol: true,
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);

    const webLinksAddon = new WebLinksAddon();
    terminal.loadAddon(webLinksAddon);

    const newTab: TerminalTab = {
      id: tabId,
      title: tabTitle,
      terminal,
      fitAddon,
      ws: null,
      isMain,
      reconnectAttempts: 0,
      reconnectTimer: null,
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
      tabs.forEach(tab => {
        if (tab.reconnectTimer) {
          clearTimeout(tab.reconnectTimer);
        }
        if (tab.ws) {
          tab.ws.close();
        }
        tab.terminal.dispose();
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

        if (isReconnect) {
          tab.terminal.writeln('\x1b[32m✓ Reconnected to tmux session\x1b[0m');
        } else {
          tab.terminal.writeln('\x1b[32m✓ Connected to tmux session\x1b[0m');
        }
        tab.terminal.writeln('');

        // Send attach message to connect to tmux
        if (tab.isMain) {
          // Main tab attaches to main window (window 0)
          ws.send(JSON.stringify({
            type: 'attach',
            window_id: 'main'
          }));
        } else {
          // New tabs request a new tmux window
          ws.send(JSON.stringify({
            type: 'new_window',
            name: tab.title
          }));
        }

        // Send initial terminal size
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
            // Clear terminal and write new output (tmux capture-pane returns full buffer)
            tab.terminal.clear();
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
          tab.terminal.write(event.data);
        }
      };

      ws.onerror = () => {
        tab.terminal.writeln('\r\n\x1b[31m✗ Connection error\x1b[0m\r\n');
      };

      ws.onclose = () => {
        tab.ws = null;

        // Attempt to reconnect with exponential backoff
        const maxAttempts = 10;
        const baseDelay = 1000; // 1 second
        const maxDelay = 30000; // 30 seconds

        if (tab.reconnectAttempts < maxAttempts) {
          const delay = Math.min(baseDelay * Math.pow(1.5, tab.reconnectAttempts), maxDelay);
          tab.reconnectAttempts++;

          tab.terminal.writeln('');
          tab.terminal.writeln(`\x1b[33m⚠ Connection closed. Reconnecting in ${Math.round(delay / 1000)}s... (attempt ${tab.reconnectAttempts}/${maxAttempts})\x1b[0m`);

          tab.reconnectTimer = setTimeout(() => {
            connectTerminal(tab, true);
          }, delay);
        } else {
          tab.terminal.writeln('');
          tab.terminal.writeln('\x1b[31m✗ Connection failed after multiple attempts. Click to reconnect:\x1b[0m');
          tab.terminal.writeln('\x1b[36m  → Refresh the page to try again\x1b[0m');

          // Add click handler to allow manual reconnect
          const reconnectHandler = () => {
            tab.reconnectAttempts = 0;
            connectTerminal(tab, true);
          };

          // Store handler so it can be cleaned up
          (tab as any).reconnectHandler = reconnectHandler;
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
    <div className="flex flex-col h-full bg-[#0a0a0a] rounded-lg overflow-hidden">
      {/* Tab Bar */}
      <div className="flex items-center gap-1 px-2 py-1.5 bg-[#1a1a1a] border-b border-white/[0.08] overflow-x-auto">
        {tabs.map(tab => (
          <div
            key={tab.id}
            className={`
              flex items-center gap-2 px-3 py-1.5 rounded-md cursor-pointer
              transition-colors min-w-fit
              ${activeTabId === tab.id
                ? 'bg-[rgba(var(--primary-rgb),0.1)] text-[var(--primary)]'
                : 'bg-[#0a0a0a] text-gray-400 hover:bg-[#1a1a1a] hover:text-gray-300'
              }
            `}
            onClick={() => setActiveTabId(tab.id)}
          >
            <span className="text-sm font-medium whitespace-nowrap">{tab.title}</span>
            {!tab.isMain && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(tab.id);
                }}
                className="p-0.5 hover:bg-white/10 rounded"
              >
                <X size={14} />
              </button>
            )}
          </div>
        ))}

        {/* New Shell Button */}
        <button
          onClick={() => createTab(false)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md
                   bg-[#0a0a0a] text-gray-400 hover:bg-[#1a1a1a] hover:text-gray-300
                   transition-colors min-w-fit"
        >
          <Plus size={14} />
          <span className="text-sm font-medium">New Shell</span>
        </button>
      </div>

      {/* Terminal Content */}
      <div
        ref={terminalContainerRef}
        className="flex-1 p-2"
        style={{ minHeight: 0 }}
      />

      {/* Info Footer */}
      <div className="px-4 py-2 bg-[#1a1a1a] border-t border-white/[0.08]">
        <p className="text-xs text-gray-500">
          💡 Tip: Use the Main tab to manage your app process. Create new shells for additional tasks.
        </p>
      </div>
    </div>
  );
}
