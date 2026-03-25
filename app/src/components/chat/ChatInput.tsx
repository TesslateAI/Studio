import { useState, useEffect, useRef, useMemo, type FormEvent, type KeyboardEvent } from 'react';
import { AgentSelector } from './AgentSelector';

import { EditModeStatus, type EditMode } from './EditModeStatus';
import {
  Gear,
  DotsThreeVertical,
  ArrowsInSimple,
  ArrowsOutSimple,
  DownloadSimple,
  Trash,
  Bug,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import JSZip from 'jszip';
import { type ChatAgent } from '../../types/chat';
import { type SerializedAttachment } from '../../types/agent';
import { projectsApi } from '../../lib/api';
import { modKey } from '../../lib/keyboard-registry';
import { useAttachments } from '../../hooks/useAttachments';
import { AttachmentStrip } from './AttachmentStrip';
import { FilePickerDropdown } from './FilePickerDropdown';

// Width thresholds for responsive collapse
// Below VERY_COMPACT: Only essential icons (agent icon, menu, send button)
// Below COMPACT: Agent name hidden, 3 buttons merge into menu
// Below EDIT_MODE_COMPACT: Edit mode label hidden, icon only
// Above EDIT_MODE_COMPACT: Full labels shown
const VERY_COMPACT_WIDTH_THRESHOLD = 300;
const COMPACT_WIDTH_THRESHOLD = 380;
const EDIT_MODE_COMPACT_THRESHOLD = 480;
const EMPTY_SKILLS: { name: string; description: string }[] = [];

interface ChatInputProps {
  agents: ChatAgent[];
  currentAgent: ChatAgent;
  onSelectAgent: (agent: ChatAgent) => void;
  onSendMessage: (message: string, attachments?: SerializedAttachment[]) => void;
  slug?: string;
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
  availableSkills?: { name: string; description: string }[];
  isAdmin?: boolean;
  onOpenDebugTools?: () => void;
  currentModelSupportsVision?: boolean;
}

export function ChatInput({
  agents,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  slug: projectSlug,
  projectName = 'project',
  placeholder:
    _placeholder = 'Ask AI to build something... (Enter or ⌃↵ to send, Shift+Enter for new line)',
  disabled = false,
  isExecuting = false,
  onStop,
  onClearHistory,
  _isExpanded = true,
  editMode = 'allow',
  onModeChange,
  onPlanMode,
  onModelChange,
  isDocked = false,
  prefillMessage,
  onPrefillConsumed,
  toolCallsCollapsed = false,
  onToggleToolCallsCollapsed,
  availableSkills = [],
  isAdmin = false,
  onOpenDebugTools,
  currentModelSupportsVision,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const [showCommands, setShowCommands] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [filteredCommands, setFilteredCommands] = useState<
    Array<{ command: string; description: string; isSkill: boolean }>
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

  const {
    attachments,
    addImage,
    addPastedText,
    addFileReference,
    removeAttachment,
    clearAttachments,
    serializeForSend,
  } = useAttachments();
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [filePickerQuery, setFilePickerQuery] = useState('');
  const [isDragging, setIsDragging] = useState(false);

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

  // Available slash commands (built-in + installed skills)
  // Stabilize the reference: avoid re-creating slashCommands when availableSkills
  // is undefined/empty (which would cause an infinite render loop via the
  // useEffect that depends on slashCommands).
  const stableSkills = availableSkills?.length ? availableSkills : EMPTY_SKILLS;
  const slashCommands = useMemo(() => {
    const builtIn = [
      { command: '/clear', description: 'Clear chat history', isSkill: false },
      { command: '/plan', description: 'Toggle plan mode', isSkill: false },
    ];
    const skillCommands = stableSkills.map((skill) => ({
      command: `/${skill.name}`,
      description: skill.description,
      isSkill: true,
    }));
    return [...builtIn, ...skillCommands];
  }, [stableSkills]);

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

      // Detect @ file references
      const atMatch = message.match(/@(\S*)$/);
      if (atMatch && projectSlug) {
        setFilePickerQuery(atMatch[1]);
        setShowFilePicker(true);
      } else {
        setShowFilePicker(false);
      }
    }
  }, [message, slashCommands, projectSlug]);

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

  const sendMessage = async () => {
    const hasContent = message.trim() || attachments.length > 0;
    if (hasContent && !disabled) {
      const trimmed = message.trim();
      // Check if it's a built-in slash command
      if (trimmed.startsWith('/')) {
        const isBuiltIn = ['/clear', '/plan'].includes(trimmed);
        if (isBuiltIn) {
          executeCommand(trimmed);
        } else {
          // Skill slash commands are sent as regular messages to the agent
          setMessageHistory((prev) => [...prev, trimmed]);
          const serialized = await serializeForSend();
          onSendMessage(trimmed, serialized.length > 0 ? serialized : undefined);
        }
      } else {
        // Regular message
        setMessageHistory((prev) => [...prev, trimmed]);
        const serialized = await serializeForSend();
        onSendMessage(trimmed, serialized.length > 0 ? serialized : undefined);
      }
      setMessage('');
      setHistoryIndex(-1);
      clearAttachments();
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Only send if explicitly triggered, not on form submit
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Up arrow - navigate backwards through history
    if (e.key === 'ArrowUp' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      const atStart = !textareaRef.current || textareaRef.current.selectionStart === 0;
      if (atStart && messageHistory.length > 0) {
        e.preventDefault();
        const newIndex =
          historyIndex === -1 ? messageHistory.length - 1 : Math.max(0, historyIndex - 1);
        setHistoryIndex(newIndex);
        setMessage(messageHistory[newIndex]);
      }
    }
    // Down arrow - navigate forwards through history
    else if (e.key === 'ArrowDown' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      const atEnd =
        !textareaRef.current ||
        textareaRef.current.selectionStart === textareaRef.current.value.length;
      if (atEnd && historyIndex > -1) {
        e.preventDefault();
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
    if (!projectSlug) return;
    try {
      toast.loading('Preparing download...', { id: 'download' });

      // Fetch file tree, then batch-fetch all file contents
      const tree = await projectsApi.getFileTree(projectSlug);
      const filePaths = tree.filter((e) => !e.is_dir).map((e) => e.path);

      const zip = new JSZip();

      // Batch fetch in chunks of 200 (server limit)
      const BATCH_SIZE = 200;
      for (let i = 0; i < filePaths.length; i += BATCH_SIZE) {
        const chunk = filePaths.slice(i, i + BATCH_SIZE);
        const { files: contents } = await projectsApi.getFileContentBatch(projectSlug, chunk);
        contents.forEach((file) => {
          zip.file(file.path, file.content);
        });
      }

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

      toast.success('Project downloaded!', { id: 'download' });
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

  const handlePaste = (e: React.ClipboardEvent) => {
    // Check clipboardData.files first (works for most drag/paste)
    const imageFiles = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'));
    if (imageFiles.length > 0) {
      if (currentModelSupportsVision === false) {
        e.preventDefault();
        toast.error(
          'The current model does not support images. Switch to a vision-capable model to attach images.'
        );
        return;
      }
      e.preventDefault();
      imageFiles.forEach((f) => addImage(f));
      return;
    }

    // Fallback: check clipboardData.items (some browsers put images here instead)
    if (e.clipboardData.items) {
      const imageItems: File[] = [];
      for (const item of Array.from(e.clipboardData.items)) {
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (file) imageItems.push(file);
        }
      }
      if (imageItems.length > 0) {
        if (currentModelSupportsVision === false) {
          e.preventDefault();
          toast.error(
            'The current model does not support images. Switch to a vision-capable model to attach images.'
          );
          return;
        }
        e.preventDefault();
        imageItems.forEach((f) => addImage(f));
        return;
      }
    }

    // Check for long text paste
    const text = e.clipboardData.getData('text/plain');
    const lines = text.split('\n');
    if (lines.length > 5) {
      e.preventDefault();
      addPastedText(text);
      return;
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    // Only trigger when leaving the form itself, not children
    if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const imageFiles = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/'));
    if (imageFiles.length > 0) {
      if (currentModelSupportsVision === false) {
        toast.error(
          'The current model does not support images. Switch to a vision-capable model to attach images.'
        );
        return;
      }
      imageFiles.forEach((f) => addImage(f));
    }
  };

  const handleFileSelect = (filePath: string, fileName: string) => {
    addFileReference(filePath, fileName);
    setMessage((prev) => prev.replace(/@\S*$/, ''));
    setShowFilePicker(false);
  };

  return (
    <form
      ref={containerRef}
      className={`chat-input-wrapper flex-shrink-0 relative ${isDragging ? 'ring-2 ring-[var(--primary)]/40 rounded-[var(--radius-medium)]' : ''}`}
      onSubmit={handleSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Command suggestions bar - Minecraft style */}
      {showCommands && filteredCommands.length > 0 && (
        <div ref={commandsRef} className="absolute bottom-full left-0 right-0 mb-2 px-3">
          <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg">
            {filteredCommands.map((cmd, idx) => (
              <div
                key={idx}
                onClick={() => {
                  setMessage(cmd.command);
                  setShowCommands(false);
                }}
                className="flex items-center gap-3 px-3 py-1.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] cursor-pointer transition-colors"
              >
                <span className="text-[var(--text)] font-mono text-xs font-semibold">
                  {cmd.command}
                </span>
                <span className="text-[var(--text-muted)] text-xs">{cmd.description}</span>
                {cmd.isSkill && (
                  <span className="ml-auto text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-[var(--surface-hover)] text-[var(--text-muted)] border border-[var(--border)]">
                    Skill
                  </span>
                )}
              </div>
            ))}
            <div className="mt-2 pt-2 border-t border-[var(--border)]">
              <span className="text-xs text-[var(--text)]/40 px-3">
                {filteredCommands.some((c) => c.isSkill)
                  ? 'Press Enter to send'
                  : 'Press Enter to execute'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* @ file picker */}
      {showFilePicker && projectSlug && (
        <FilePickerDropdown
          slug={projectSlug}
          query={filePickerQuery}
          onSelect={handleFileSelect}
          onClose={() => setShowFilePicker(false)}
        />
      )}

      {/* Settings / menu dropdown */}
      {showSettings && (
        <div ref={settingsRef} className="absolute bottom-full right-0 mb-2 mr-3">
          <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg min-w-[200px]">
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
                    className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--surface-hover)] cursor-pointer transition-colors w-full text-left"
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
                  className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--surface-hover)] cursor-pointer transition-colors w-full text-left"
                >
                  <span className="text-[var(--text)]/60 w-4 text-center font-mono font-bold text-base leading-none">
                    /
                  </span>
                  <span className="text-[var(--text)] text-sm">Commands</span>
                </button>
                <div className="my-1 border-t border-[var(--border)]" />
              </>
            )}

            {/* Admin-only: Debug tools */}
            {isAdmin && onOpenDebugTools && (
              <button
                type="button"
                onClick={() => {
                  onOpenDebugTools();
                  setShowSettings(false);
                }}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--surface-hover)] cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[var(--text)]/60">
                  <Bug size={16} weight="bold" />
                </span>
                <span className="text-[var(--text)] text-sm">Debug Tools</span>
              </button>
            )}

            {/* Always-visible items: download + clear */}
            <button
              type="button"
              onClick={() => {
                downloadProject();
                setShowSettings(false);
              }}
              className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--surface-hover)] cursor-pointer transition-colors w-full text-left"
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
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[var(--surface-hover)] cursor-pointer transition-colors w-full text-left"
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
        className={`flex flex-col bg-[var(--surface)] w-full ${isDocked ? '' : 'border border-[var(--border)] rounded-[var(--radius-medium)] shadow-sm'}`}
      >
        {/* First row: Growing textarea */}
        <div
          className="px-3 flex items-center border-b border-[var(--border)]"
          style={{ minHeight: '44px' }}
        >
          {disabled ? (
            <div className="flex items-center gap-2 w-full py-2">
              <span className="text-xs text-[var(--text-subtle)]">Viewer mode — chat is read-only</span>
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => {
                setMessage(e.target.value);
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder=""
              rows={1}
              className="chat-input bg-transparent border-none w-full text-[var(--text)] text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40 resize-none overflow-hidden leading-relaxed my-2"
              style={{
                minHeight: '24px',
                maxHeight: '200px',
              }}
            />
          )}
        </div>

        {/* Attachment chips */}
        {attachments.length > 0 && (
          <AttachmentStrip attachments={attachments} onRemove={removeAttachment} />
        )}

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
                className=""
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
                  className={`btn btn-icon btn-sm ${toolCallsCollapsed ? 'btn-active' : ''}`}
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
                className={`btn btn-icon btn-sm ${showSettings ? 'btn-active' : ''}`}
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
                className={`btn btn-icon btn-sm font-mono font-bold text-sm ${showCommands ? 'btn-active' : ''}`}
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
              className={`btn btn-icon btn-sm ${showSettings ? 'btn-active' : ''}`}
              title="Menu"
            >
              <DotsThreeVertical size={16} weight="bold" />
            </button>
          )}

          {/* Send button - always visible */}
          <button
            type="button"
            onClick={isExecuting ? onStop : sendMessage}
            disabled={!isExecuting && ((!message.trim() && attachments.length === 0) || disabled)}
            className="btn btn-icon btn-sm"
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
