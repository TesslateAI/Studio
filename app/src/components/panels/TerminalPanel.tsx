import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { createTerminalWebSocket } from '../../lib/api';

interface TerminalPanelProps {
  projectId: string;
}

export function TerminalPanel({ projectId }: TerminalPanelProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!terminalRef.current || !projectId) return;

    // Create terminal instance
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
      theme: {
        background: '#0a0a0a',
        foreground: '#e5e5e5',
        cursor: '#ff6b00',
        cursorAccent: '#000000',
        selection: 'rgba(255, 107, 0, 0.3)',
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

    // Add fit addon
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);

    // Add web links addon (makes URLs clickable)
    const webLinksAddon = new WebLinksAddon();
    terminal.loadAddon(webLinksAddon);

    // Open terminal
    terminal.open(terminalRef.current);
    fitAddon.fit();

    xtermRef.current = terminal;
    fitAddonRef.current = fitAddon;

    // Show initial message
    terminal.writeln('\x1b[38;5;208m╔═══════════════════════════════════════╗\x1b[0m');
    terminal.writeln('\x1b[38;5;208m║  Tesslate Studio - Interactive Shell  ║\x1b[0m');
    terminal.writeln('\x1b[38;5;208m╚═══════════════════════════════════════╝\x1b[0m');
    terminal.writeln('');
    terminal.writeln('Connecting to container shell...');
    terminal.writeln('');

    // Connect to WebSocket for interactive terminal
    const connectWebSocket = () => {
      try {
        const ws = createTerminalWebSocket(projectId);
        wsRef.current = ws;

        ws.onopen = () => {
          setIsConnected(true);
          setError(null);
          terminal.writeln('\x1b[32m✓ Connected to interactive shell\x1b[0m');
          terminal.writeln('');

          // Send initial terminal size
          const dims = fitAddon.proposeDimensions();
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
              // Write shell output to terminal
              terminal.write(data.data);
            } else if (data.type === 'error') {
              terminal.writeln(`\r\n\x1b[31m✗ Error: ${data.message}\x1b[0m\r\n`);
            } else if (data.type === 'status') {
              terminal.writeln(`\x1b[36m⟳ ${data.message}\x1b[0m`);
            }
          } catch (e) {
            // If not JSON, just write the raw data
            terminal.write(event.data);
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          setError('Connection error');
          terminal.writeln('\r\n\x1b[31m✗ Connection error\x1b[0m\r\n');
        };

        ws.onclose = () => {
          setIsConnected(false);
          terminal.writeln('');
          terminal.writeln('\x1b[33m⚠ Connection closed. Reconnecting...\x1b[0m');

          // Attempt to reconnect after 3 seconds
          setTimeout(() => {
            if (xtermRef.current) {
              connectWebSocket();
            }
          }, 3000);
        };

        // Handle user input (keystrokes)
        terminal.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
              type: 'input',
              data: data
            }));
          }
        });

        // Handle terminal resize
        terminal.onResize((dimensions) => {
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
        setError('Failed to connect');
        terminal.writeln('\x1b[31m✗ Failed to establish connection\x1b[0m');
      }
    };

    connectWebSocket();

    // Handle terminal resize
    const resizeObserver = new ResizeObserver(() => {
      if (fitAddonRef.current) {
        try {
          fitAddonRef.current.fit();
        } catch (e) {
          // Ignore resize errors
        }
      }
    });

    if (terminalRef.current) {
      resizeObserver.observe(terminalRef.current);
    }

    // Cleanup
    return () => {
      resizeObserver.disconnect();
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (xtermRef.current) {
        xtermRef.current.dispose();
      }
    };
  }, [projectId]);

  return (
    <div className="flex flex-col h-full bg-[#0a0a0a] rounded-lg overflow-hidden">
      {/* Terminal Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#1a1a1a] border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500/80"></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500/80"></div>
            <div className="w-3 h-3 rounded-full bg-green-500/80"></div>
          </div>
          <span className="text-sm text-gray-400 ml-2">Interactive Shell</span>
        </div>

        <div className="flex items-center gap-2">
          {isConnected ? (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
              <span className="text-xs text-green-400">Live</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-yellow-500"></div>
              <span className="text-xs text-yellow-400">Connecting...</span>
            </div>
          )}
        </div>
      </div>

      {/* Terminal Content */}
      <div
        ref={terminalRef}
        className="flex-1 p-2"
        style={{ minHeight: 0 }}
      />

      {/* Error Message */}
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-t border-red-500/20">
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {/* Info Footer */}
      <div className="px-4 py-2 bg-[#1a1a1a] border-t border-white/[0.08]">
        <p className="text-xs text-gray-500">
          💡 Tip: This is a fully interactive shell running inside your container.
          You can run commands, use vim, navigate directories, and more.
        </p>
      </div>
    </div>
  );
}
