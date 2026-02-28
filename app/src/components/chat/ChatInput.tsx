import { useState, useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react';
import { AgentSelector } from './AgentSelector';

import { EditModeStatus, type EditMode } from './EditModeStatus';
import {
  Gear,
  DotsThreeVertical,
  ArrowsInSimple,
  ArrowsOutSimple,
  DownloadSimple,
  Trash,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import JSZip from 'jszip';
import { type ChatAgent } from '../../types/chat';
import { modKey } from '../../lib/keyboard-registry';

// Width thresholds for responsive collapse
// Below VERY_COMPACT: Only essential icons (agent icon, menu, send button)
// Below COMPACT: Agent name hidden, 3 buttons merge into menu
// Below EDIT_MODE_COMPACT: Edit mode label hidden, icon only
// Above EDIT_MODE_COMPACT: Full labels shown
const VERY_COMPACT_WIDTH_THRESHOLD = 300;
const COMPACT_WIDTH_THRESHOLD = 380;
const EDIT_MODE_COMPACT_THRESHOLD = 480;

interface ProjectFile {
  file_path: string;
  content: string;
}

interface ChatInputProps {
  agents: ChatAgent[];
  currentAgent: ChatAgent;
  onSelectAgent: (agent: ChatAgent) => void;
  onSendMessage: (message: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  placeholder?: string;
  disabled?: boolean;
  isExecuting?: boolean;
  onStop?: () => void;
  onClearHistory?: () => void;
  isExpanded?: boolean;
  editMode?: EditMode;
  onModeChange?: (mode: EditMode) => void;
  onPlanMode?: () => void;
  onModelChange?: (model: string) => void;
  isDocked?: boolean; // When true, removes rounded corners at bottom
  prefillMessage?: string | null;
  onPrefillConsumed?: () => void;
  toolCallsCollapsed?: boolean;
  onToggleToolCallsCollapsed?: () => void;
}

export function ChatInput({
  agents,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  projectFiles = [],
  projectName = 'project',
  placeholder:
    _placeholder = 'Ask AI to build something... (Enter or ⌃↵ to send, Shift+Enter for new line)',
  disabled = false,
  isExecuting = false,
  onStop,
  onClearHistory,
  isExpanded = true,
  editMode = 'allow',
  onModeChange,
  onPlanMode,
  onModelChange,
  isDocked = false,
  prefillMessage,
  onPrefillConsumed,
  toolCallsCollapsed = false,
  onToggleToolCallsCollapsed,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const [showCommands, setShowCommands] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [filteredCommands, setFilteredCommands] = useState<
    Array<{ command: string; description: string }>
  >([]);
  const [messageHistory, setMessageHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [compactLevel, setCompactLevel] = useState<'normal' | 'compact' | 'veryCompact'>('normal');
  const [containerWidth, setContainerWidth] = useState(Infinity);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLFormElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const commandsRef = useRef<HTMLDivElement>(null);
  const commandsButtonRef = useRef<HTMLButtonElement>(null);

  // Derived compact states
  const isCompact = compactLevel === 'compact' || compactLevel === 'veryCompact';
  const isEditModeCompact = isCompact || containerWidth < EDIT_MODE_COMPACT_THRESHOLD;

  // Use ResizeObserver to track width changes for responsive layout
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const updateCompactLevel = (width: number) => {
      setContainerWidth(width);
      // Compact-level breakpoints only apply when docked (floating chat has fixed width)
      if (!isDocked) return;
      if (width < VERY_COMPACT_WIDTH_THRESHOLD) {
        setCompactLevel('veryCompact');
      } else if (width < COMPACT_WIDTH_THRESHOLD) {
        setCompactLevel('compact');
      } else {
        setCompactLevel('normal');
      }
    };

    // Debounced resize handler to reduce state updates during rapid panel resize
    const resizeObserver = new ResizeObserver((entries) => {
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        for (const entry of entries) {
          updateCompactLevel(entry.contentRect.width);
        }
      }, 50); // 50ms debounce
    });
    resizeObserver.observe(container);

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      resizeObserver.disconnect();
    };
  }, [isDocked]);

  // Close settings/commands dropdowns on click outside
  useEffect(() => {
    if (!showSettings && !showCommands) return;

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        showSettings &&
        settingsRef.current &&
        !settingsRef.current.contains(target) &&
        (!settingsButtonRef.current || !settingsButtonRef.current.contains(target))
      ) {
        setShowSettings(false);
      }
      if (
        showCommands &&
        commandsRef.current &&
        !commandsRef.current.contains(target) &&
        (!commandsButtonRef.current || !commandsButtonRef.current.contains(target))
      ) {
        setShowCommands(false);
      }
    };

    // Capture phase so it fires before children can stopPropagation
    const handleBlur = () => {
      setShowSettings(false);
      setShowCommands(false);
    };

    document.addEventListener('mousedown', handleClickOutside, true);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside, true);
      window.removeEventListener('blur', handleBlur);
    };
  }, [showSettings, showCommands]);

  // Available slash commands
  const slashCommands = [
    { command: '/clear', description: 'Clear chat history' },
    { command: '/plan', description: 'Toggle plan mode' },
    // Add more commands here as needed
  ];

  // Check for landing page prompt on component mount
  useEffect(() => {
    const landingPrompt = localStorage.getItem('landingPrompt');
    if (landingPrompt) {
      setMessage(landingPrompt);
      // Clear the prompt after using it
      localStorage.removeItem('landingPrompt');
    }
  }, []);

  // Handle prefill message from external triggers (e.g. "Ask Agent" button)
  useEffect(() => {
    if (prefillMessage) {
      setMessage(prefillMessage);
      onPrefillConsumed?.();
    }
  }, [prefillMessage, onPrefillConsumed]);

  // Detect slash commands
  useEffect(() => {
    if (message.startsWith('/')) {
      const query = message.slice(1).toLowerCase();
      const matches = slashCommands.filter((cmd) =>
        cmd.command.slice(1).toLowerCase().startsWith(query)
      );
      setFilteredCommands(matches);
      setShowCommands(matches.length > 0);
    } else {
      setShowCommands(false);
      setFilteredCommands([]);
    }
  }, [message]);

  // Auto-resize textarea as user types
  // Note: This causes a reflow but it's unavoidable for auto-sizing textareas
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset height to get accurate scrollHeight, then set final height
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${newHeight}px`;
  }, [message]);

  const executeCommand = (cmd: string) => {
    if (cmd === '/clear') {
      if (onClearHistory) {
        onClearHistory();
        setMessage('');
      }
    } else if (cmd === '/plan') {
      if (onPlanMode) {
        onPlanMode();
        setMessage('');
      }
    }
    // Add more command handlers here
  };

  const sendMessage = () => {
    if (message.trim() && !disabled) {
      // Check if it's a slash command
      if (message.startsWith('/')) {
        executeCommand(message.trim());
      } else {
        // Add to history
        setMessageHistory((prev) => [...prev, message.trim()]);
        onSendMessage(message.trim());
      }
      setMessage('');
      setHistoryIndex(-1);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Only send if explicitly triggered, not on form submit
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Up arrow - navigate backwards through history
    if (e.key === 'ArrowUp' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      if (messageHistory.length > 0) {
        const newIndex =
          historyIndex === -1 ? messageHistory.length - 1 : Math.max(0, historyIndex - 1);
        setHistoryIndex(newIndex);
        setMessage(messageHistory[newIndex]);
      }
    }
    // Down arrow - navigate forwards through history
    else if (e.key === 'ArrowDown' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      if (historyIndex > -1) {
        const newIndex = historyIndex + 1;
        if (newIndex >= messageHistory.length) {
          setHistoryIndex(-1);
          setMessage('');
        } else {
          setHistoryIndex(newIndex);
          setMessage(messageHistory[newIndex]);
        }
      }
    }
    // Enter alone sends message (both slash commands and regular messages)
    // Ctrl+Enter or Cmd+Enter also works for sending messages
    else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    // Shift+Enter creates a new line (default behavior, no need to handle)
  };

  const downloadProject = async () => {
    try {
      toast.loading('Preparing download...', { id: 'download' });

      const zip = new JSZip();

      // Add all project files to zip
      projectFiles.forEach((file) => {
        zip.file(file.file_path, file.content);
      });

      // Generate zip file
      const blob = await zip.generateAsync({ type: 'blob' });

      // Create download link
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${projectName}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success('Project downloaded!', { id: 'download', icon: '📦' });
    } catch (error) {
      console.error('Failed to download project:', error);
      toast.error('Failed to download project', { id: 'download' });
    }
  };

  const clearChatHistory = () => {
    if (onClearHistory) {
      onClearHistory();
    }
  };

  return (
    <form
      ref={containerRef}
      className="chat-input-wrapper flex-shrink-0 relative"
      onSubmit={handleSubmit}
    >
      {/* Command suggestions bar - Minecraft style */}
      {showCommands && filteredCommands.length > 0 && (
        <div ref={commandsRef} className="absolute bottom-full left-0 right-0 mb-2 px-3">
          <div className="bg-[var(--surface)] border-2 border-[var(--primary)]/40 rounded-xl p-2 shadow-lg shadow-[var(--primary)]/10">
            {filteredCommands.map((cmd, idx) => (
              <div
                key={idx}
                onClick={() => {
                  setMessage(cmd.command);
                  setShowCommands(false);
                }}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--primary)]/10 cursor-pointer transition-colors"
              >
                <span className="text-[var(--primary)} font-mono font-semibold">{cmd.command}</span>
                <span className="text-[var(--text)]/60 text-sm">{cmd.description}</span>
              </div>
            ))}
            <div className="mt-2 pt-2 border-t border-[var(--border-color)]">
              <span className="text-xs text-[var(--text)]/40 px-3">Press Enter to execute</span>
            </div>
          </div>
        </div>
      )}

      {/* Settings / menu dropdown */}
      {showSettings && (
        <div ref={settingsRef} className="absolute bottom-full right-0 mb-2 mr-3">
          <div className="bg-[var(--surface)] border-2 border-[var(--border-color)] rounded-xl p-2 shadow-lg min-w-[200px]">
            {/* Compact-only items: collapse toggle + commands */}
            {isCompact && (
              <>
                {onToggleToolCallsCollapsed && (
                  <button
                    type="button"
                    onClick={() => {
                      onToggleToolCallsCollapsed();
                      setShowSettings(false);
                    }}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--text)]/5 cursor-pointer transition-colors w-full text-left"
                  >
                    <span
                      className={
                        toolCallsCollapsed ? 'text-[var(--primary)]' : 'text-[var(--text)]/60'
                      }
                    >
                      {toolCallsCollapsed ? (
                        <ArrowsOutSimple size={16} weight="bold" />
                      ) : (
                        <ArrowsInSimple size={16} weight="bold" />
                      )}
                    </span>
                    <span className="text-[var(--text)] text-sm">
                      {toolCallsCollapsed ? 'Expand Tool Calls' : 'Collapse Tool Calls'}
                    </span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setMessage('/');
                    setShowSettings(false);
                    setShowCommands(true);
                    textareaRef.current?.focus();
                  }}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--text)]/5 cursor-pointer transition-colors w-full text-left"
                >
                  <span className="text-[var(--text)]/60 w-4 text-center font-mono font-bold text-base leading-none">
                    /
                  </span>
                  <span className="text-[var(--text)] text-sm">Commands</span>
                </button>
                <div className="my-1 border-t border-[var(--border-color)]" />
              </>
            )}

            {/* Always-visible items: download + clear */}
            <button
              type="button"
              onClick={() => {
                downloadProject();
                setShowSettings(false);
              }}
              className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--text)]/5 cursor-pointer transition-colors w-full text-left"
            >
              <span className="text-[var(--text)]/60">
                <DownloadSimple size={16} weight="bold" />
              </span>
              <span className="text-[var(--text)] text-sm">Download Project</span>
            </button>
            {onClearHistory && (
              <button
                type="button"
                onClick={() => {
                  clearChatHistory();
                  setShowSettings(false);
                }}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--text)]/5 cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[var(--text)]/60">
                  <Trash size={16} weight="bold" />
                </span>
                <span className="text-[var(--text)] text-sm">Clear Chat History</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Two-row layout */}
      <div
        className={`flex flex-col bg-[var(--text)]/10 w-full ${isDocked ? '' : isExpanded ? 'rounded-b-3xl' : 'rounded-3xl'} ${!isDocked ? 'max-md:rounded-b-none' : ''}`}
      >
        {/* First row: Growing textarea */}
        <div
          className="px-3 flex items-center border-b border-[var(--border-color)]"
          style={{ minHeight: '44px' }}
        >
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            placeholder=""
            rows={1}
            className="chat-input bg-transparent border-none w-full text-[var(--text)] text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40 resize-none overflow-hidden leading-relaxed my-2"
            style={{
              minHeight: '24px',
              maxHeight: '200px',
            }}
          />
        </div>

        {/* Second row: Agent selector and buttons */}
        <div className="flex items-center gap-1.5 px-2 py-1.5 w-full min-w-0">
          {/* Agent selector */}
          <div className="min-w-0 shrink">
            <AgentSelector
              agents={agents}
              currentAgent={currentAgent}
              onSelectAgent={onSelectAgent}
              onModelChange={onModelChange}
              compact={isCompact}
            />
          </div>

          {/* Spacer */}
          <div className="flex-1 min-w-0" />

          {/* Edit Mode Status - icon-only when narrow */}
          {onModeChange && (
            <div className="flex-shrink-0">
              <EditModeStatus
                mode={editMode}
                onModeChange={onModeChange}
                className="scale-90"
                compact={isEditModeCompact}
              />
            </div>
          )}

          {/* Desktop: 3 individual buttons */}
          {!isCompact && (
            <>
              {/* Collapse tool calls */}
              {onToggleToolCallsCollapsed && (
                <button
                  type="button"
                  onClick={onToggleToolCallsCollapsed}
                  className={`w-7 h-7 flex items-center justify-center rounded-lg transition-all flex-shrink-0 ${
                    toolCallsCollapsed
                      ? 'text-[var(--primary)] bg-[var(--primary)]/10'
                      : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--text)]/5'
                  }`}
                  title={toolCallsCollapsed ? 'Expand tool calls' : 'Collapse tool calls'}
                >
                  {toolCallsCollapsed ? (
                    <ArrowsOutSimple size={14} weight="bold" />
                  ) : (
                    <ArrowsInSimple size={14} weight="bold" />
                  )}
                </button>
              )}

              {/* Settings gear */}
              <button
                ref={settingsButtonRef}
                type="button"
                onClick={() => {
                  setShowSettings(!showSettings);
                  setShowCommands(false);
                }}
                className={`w-7 h-7 flex items-center justify-center rounded-lg transition-all flex-shrink-0 ${
                  showSettings
                    ? 'text-[var(--primary)] bg-[var(--primary)]/10'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--text)]/5'
                }`}
                title="Settings"
              >
                <Gear size={14} weight="bold" />
              </button>

              {/* Slash commands */}
              <button
                ref={commandsButtonRef}
                type="button"
                onClick={() => {
                  if (showCommands) {
                    setShowCommands(false);
                    setMessage('');
                  } else {
                    setMessage('/');
                    setShowCommands(true);
                    setShowSettings(false);
                  }
                }}
                className={`w-7 h-7 flex items-center justify-center rounded-lg transition-all flex-shrink-0 font-mono font-bold text-sm ${
                  showCommands
                    ? 'text-[var(--primary)] bg-[var(--primary)]/10'
                    : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--text)]/5'
                }`}
                title="Commands"
              >
                /
              </button>
            </>
          )}

          {/* Compact/very compact: single menu button combining all 3 */}
          {isCompact && (
            <button
              ref={settingsButtonRef}
              type="button"
              onClick={() => {
                setShowSettings(!showSettings);
                setShowCommands(false);
              }}
              className={`w-7 h-7 flex items-center justify-center rounded-lg transition-all flex-shrink-0 ${
                showSettings
                  ? 'text-[var(--primary)] bg-[var(--primary)]/10'
                  : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--text)]/5'
              }`}
              title="Menu"
            >
              <DotsThreeVertical size={16} weight="bold" />
            </button>
          )}

          {/* Send button - always visible */}
          <button
            type="button"
            onClick={isExecuting ? onStop : sendMessage}
            disabled={!isExecuting && (!message.trim() || disabled)}
            className="w-7 h-7 bg-[var(--text)]/10 hover:bg-[var(--text)]/20 rounded-lg border-2 border-[var(--border-color)] text-[var(--text)] flex items-center justify-center flex-shrink-0 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            title={
              isExecuting ? 'Stop execution (Escape)' : `Send message (Enter or ${modKey}+Enter)`
            }
          >
            {isExecuting ? (
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                <rect x="64" y="64" width="128" height="128" rx="8" />
              </svg>
            ) : (
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                <path d="M231.87,114l-168-95.89A16,16,0,0,0,40.92,37.34L71.55,128,40.92,218.67A16,16,0,0,0,56,240a16.15,16.15,0,0,0,7.93-2.1l167.92-96.05a16,16,0,0,0,.05-27.89ZM56,224a.56.56,0,0,0,0-.12L85.74,136H144a8,8,0,0,0,0-16H85.74L56.06,32.16A.46.46,0,0,0,56,32l168,95.83Z" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
