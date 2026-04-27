import {
  useState,
  useEffect,
  useRef,
  useMemo,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
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
  ArrowCounterClockwise,
  ArrowClockwise,
  Lightning,
  ListChecks,
  Brain,
  ArrowsClockwise,
  Question,
  Plus,
  Robot,
  PencilSimple as PencilSimpleIcon,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import JSZip from 'jszip';
import { type ChatAgent } from '../../types/chat';
import { type SerializedAttachment, type ChatMention } from '../../types/agent';
import { projectsApi, mentionApi, type MentionItem } from '../../lib/api';
import { modKey } from '../../lib/keyboard-registry';
import { useCommands } from '../../contexts/CommandContext';
import { useAttachments } from '../../hooks/useAttachments';
import { AttachmentStrip } from './AttachmentStrip';
import { PlusMenu } from './PlusMenu';
import { MentionPicker, type MentionPickerFile } from './MentionPicker';

// Width thresholds for responsive collapse
// Below VERY_COMPACT: Only essential icons (agent icon, menu, send button)
// Below COMPACT: Agent name hidden, 3 buttons merge into menu
// Below EDIT_MODE_COMPACT: Edit mode label hidden, icon only
// Above EDIT_MODE_COMPACT: Full labels shown
const VERY_COMPACT_WIDTH_THRESHOLD = 300;
const COMPACT_WIDTH_THRESHOLD = 380;
const EDIT_MODE_COMPACT_THRESHOLD = 480;
const EMPTY_SKILLS: { name: string; description: string }[] = [];

const COMMAND_ICONS: Record<string, ReactNode> = {
  '/clear': <Trash size={14} weight="bold" />,
  '/plan': <ListChecks size={14} weight="bold" />,
  '/undo': <ArrowCounterClockwise size={14} weight="bold" />,
  '/retry': <ArrowClockwise size={14} weight="bold" />,
  '/effort': <Brain size={14} weight="bold" />,
  '/compact': <ArrowsClockwise size={14} weight="bold" />,
  '/help': <Question size={14} weight="bold" />,
  '/new': <Plus size={14} weight="bold" />,
  '/model': <Robot size={14} weight="bold" />,
  '/session': <PencilSimpleIcon size={14} weight="bold" />,
};

interface ChatInputProps {
  agents: ChatAgent[];
  currentAgent: ChatAgent;
  onSelectAgent: (agent: ChatAgent) => void;
  onSendMessage: (
    message: string,
    attachments?: SerializedAttachment[],
    mentions?: ChatMention[]
  ) => void;
  slug?: string;
  projectName?: string;
  placeholder?: string;
  disabled?: boolean;
  viewerMode?: boolean;
  isExecuting?: boolean;
  onStop?: () => void;
  onClearHistory?: () => void;
  onUndo?: () => void;
  onRetry?: () => void;
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
  onCompact?: () => void;
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
  viewerMode = false,
  isExecuting = false,
  onStop,
  onClearHistory,
  onUndo,
  onRetry,
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
  onCompact,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const [showCommands, setShowCommands] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [filteredCommands, setFilteredCommands] = useState<
    Array<{ command: string; description: string; isSkill: boolean }>
  >([]);
  const [messageHistory, setMessageHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [commandIndex, setCommandIndex] = useState(0);
  const [compactLevel, setCompactLevel] = useState<'normal' | 'compact' | 'veryCompact'>('normal');
  const [containerWidth, setContainerWidth] = useState(Infinity);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLFormElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const commandsRef = useRef<HTMLDivElement>(null);
  const commandsButtonRef = useRef<HTMLButtonElement>(null);

  // External focus / attach triggers — dispatched by ChatContainer when the
  // command palette or a keybinding fires. Keeps the textarea ref private
  // here without forcing a forwardRef refactor on every consumer.
  useEffect(() => {
    const focus = () => textareaRef.current?.focus();
    const attach = () => {
      // Legacy "open file picker" event — folded into the unified mention
      // picker so a single shortcut surfaces everything attachable.
      setShowMentionPicker(true);
    };
    window.addEventListener('tesslate:focus-chat', focus);
    window.addEventListener('tesslate:open-attach', attach);
    return () => {
      window.removeEventListener('tesslate:focus-chat', focus);
      window.removeEventListener('tesslate:open-attach', attach);
    };
  }, []);

  const commands = useCommands();

  const {
    attachments,
    addImage,
    addPastedText,
    addFileReference,
    removeAttachment,
    clearAttachments,
    serializeForSend,
  } = useAttachments();
  const [isDragging, setIsDragging] = useState(false);

  // Unified @-mention picker. Replaces the previous FilePickerDropdown —
  // files are now one of four sections (Agents / Apps / Connectors / Files).
  // ``mentions`` is the structured list that ships in the chat request
  // alongside the raw message string. The textarea still carries the
  // human-readable ``@coworker`` token so chat history renders naturally.
  const [showMentionPicker, setShowMentionPicker] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentions, setMentions] = useState<ChatMention[]>([]);
  const [mentionAgents, setMentionAgents] = useState<MentionItem[]>([]);
  const [mentionMcps, setMentionMcps] = useState<MentionItem[]>([]);
  const [mentionApps, setMentionApps] = useState<MentionItem[]>([]);
  const [mentionFiles, setMentionFiles] = useState<MentionPickerFile[]>([]);
  const [mentionLoading, setMentionLoading] = useState(false);

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
      { command: '/help', description: 'List available slash commands', isSkill: false },
      { command: '/new', description: 'Start a new chat session', isSkill: false },
      { command: '/clear', description: 'Clear chat history', isSkill: false },
      { command: '/plan', description: 'Toggle plan mode', isSkill: false },
      { command: '/undo', description: 'Remove last message exchange', isSkill: false },
      { command: '/retry', description: 'Retry the last message', isSkill: false },
      {
        command: '/effort',
        description: 'Set thinking effort (low/medium/high/xhigh)',
        isSkill: false,
      },
      { command: '/compact', description: 'Compact conversation context', isSkill: false },
      { command: '/model', description: 'Switch model / agent', isSkill: false },
      { command: '/session', description: 'Rename current session', isSkill: false },
    ];
    const skillCommands = stableSkills.map((skill) => ({
      command: `/${skill.name}`,
      description: skill.description,
      isSkill: true,
    }));
    return [...builtIn, ...skillCommands];
  }, [stableSkills]);

  // Detect when the typed message exactly matches a command (chip mode)
  const recognizedCommand = useMemo(() => {
    const trimmed = message.trim();
    if (!trimmed.startsWith('/')) return null;
    return slashCommands.find((c) => c.command === trimmed) || null;
  }, [message, slashCommands]);

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
      setCommandIndex(0);
      setShowCommands(matches.length > 0);
    } else {
      setShowCommands(false);
      setFilteredCommands([]);

      // Detect ``@<query>`` at the end of the textarea content. Opens the
      // unified mention picker (Agents / Apps / Connectors / Files). The
      // textarea remains the source of truth — when the user picks an
      // item we splice the trailing ``@<query>`` token out and replace it
      // with the chosen display token + record the structured mention in
      // ``mentions[]``.
      const atMatch = message.match(/@(\S*)$/);
      if (atMatch) {
        setMentionQuery(atMatch[1]);
        setShowMentionPicker(true);
      } else {
        setShowMentionPicker(false);
        setMentionQuery('');
      }
    }
  }, [message, slashCommands]);

  // Eagerly load mention sources on mount so auto-resolve of typed
  // @<slug> tokens works even when the user never opens the picker
  // (and so a fast typist who presses Enter before the picker's lazy
  // fetch completes still gets structured mentions in the request).
  // The cost is three small parallel GETs, swallowed individually by
  // mentionApi.search; cached for the component's lifetime.
  const mentionLoadedRef = useRef(false);
  useEffect(() => {
    if (mentionLoadedRef.current) return;
    let cancelled = false;
    setMentionLoading(true);
    (async () => {
      try {
        const result = await mentionApi.search();
        if (cancelled) return;
        setMentionAgents(result.agents);
        setMentionMcps(result.mcps);
        setMentionApps(result.apps);
        mentionLoadedRef.current = true;
      } catch {
        // mentionApi.search swallows per-category failures itself; this
        // catch handles a complete fetch crash. Leave lists empty so the
        // picker still renders project files.
      } finally {
        if (!cancelled) setMentionLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Project files for the picker's Files section. Lazy-loaded the first
  // time the picker opens — only when the chat is project-scoped.
  // Uses the same ``getFileTree`` source the legacy FilePickerDropdown
  // used, so existing file-reference behaviour is preserved.
  const filesLoadedRef = useRef(false);
  useEffect(() => {
    if (!showMentionPicker || filesLoadedRef.current || !projectSlug) return;
    let cancelled = false;
    (async () => {
      try {
        const tree = await projectsApi.getFileTree(projectSlug);
        if (cancelled) return;
        const rows: MentionPickerFile[] = (tree || [])
          .filter((f: { is_dir?: boolean }) => !f.is_dir)
          .slice(0, 200)
          .map((f: { path: string }) => ({
            kind: 'file' as const,
            path: f.path,
            display: f.path.split('/').pop() || f.path,
          }));
        setMentionFiles(rows);
        filesLoadedRef.current = true;
      } catch {
        // Project file listing is best-effort here.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [showMentionPicker, projectSlug]);

  // ---------------------------------------------------------------
  // Auto-resolve typed @-mentions
  // ---------------------------------------------------------------
  // The picker is the discovery affordance, but we don't want to
  // *require* an explicit click — users frequently type the slug
  // directly (e.g. ``@surfaces-mathkit``) and never interact with
  // the dropup. Without auto-resolve those typed-only mentions
  // never make it into the structured ``mentions[]`` array, so the
  // backend sends them as plain text and the agent has no
  // ``[mentions]`` block to read from.
  //
  // Strategy: index every loaded library item by slug, scan the
  // message for ``@<slug>`` tokens against that index, and reconcile
  // ``mentions[]`` to match. Keeps existing picker-driven mentions
  // intact (they have richer offset/display data) — we only ADD
  // entries not already present, and never remove the picker's
  // explicit choices unless their display token has been deleted
  // from the message.

  const mentionLibrary = useMemo(() => {
    const m = new Map<string, MentionItem>();
    for (const a of mentionAgents) if (a.slug) m.set(a.slug, a);
    for (const x of mentionMcps) if (x.slug) m.set(x.slug, x);
    for (const x of mentionApps) if (x.slug) m.set(x.slug, x);
    return m;
  }, [mentionAgents, mentionMcps, mentionApps]);

  useEffect(() => {
    // Pull every ``@<slug>`` occurrence; slugs are kebab-case + dots
    // for app reverse-DNS ids. Word boundary at the end keeps us from
    // greedily matching across whitespace.
    const matches = Array.from(
      message.matchAll(/(?:^|\s)@([a-zA-Z0-9_.\-]+)/g)
    );
    if (!matches.length && !mentions.length) return;

    let changed = false;
    const next = [...mentions];
    const seenRefs = new Set(next.map((m) => m.ref_id));

    for (const m of matches) {
      const slug = m[1];
      const item = mentionLibrary.get(slug);
      if (!item) continue;
      if (!item.enabled) continue;
      if (seenRefs.has(item.ref_id)) continue;
      const display = '@' + slug;
      // Anchor offset to where the match landed in the message body
      // so a future renderer can highlight the exact substring; the
      // ``@`` itself is one char before the slug.
      const baseIdx = m.index ?? 0;
      const offset =
        baseIdx + (m[0].startsWith('@') ? 0 : m[0].indexOf('@'));
      next.push({ kind: item.kind, ref_id: item.ref_id, display, offset });
      seenRefs.add(item.ref_id);
      changed = true;
    }

    // Drop mentions whose display token has been deleted from the
    // message body so the structured array stays in sync with what
    // the user actually typed.
    const filtered = next.filter((m) => message.includes(m.display));
    if (filtered.length !== next.length) changed = true;

    if (changed) setMentions(filtered);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message, mentionLibrary]);

  // ---------------------------------------------------------------
  // Inline mention highlighting
  // ---------------------------------------------------------------
  // The textarea is a real <textarea>, so we can't render React nodes
  // inside it. We use the standard textarea-highlighter trick: a div
  // with identical font + padding + wrapping sits BEHIND the textarea.
  // The overlay div renders the same text, but with each registered
  // @-mention's display token wrapped in a rounded colored <span>
  // whose background peeks through the textarea (textarea bg is
  // transparent). The overlay text itself is transparent so we don't
  // double-paint glyphs — only the colored pills are visible.
  //
  // Order matters: longest tokens first so '@foo-bar' isn't matched
  // by a shorter '@foo' that happens to share the prefix.

  // Overlay-only classes — bg + ring, no `text-…`. The overlay has
  // text-transparent at the parent level; if a pill class set a text
  // color it would override that and produce visible "ghost" glyphs
  // behind the textarea's real text (the "double text" bug).
  const MENTION_KIND_PILL: Record<string, string> = {
    agent:
      'bg-[var(--primary)]/20 ring-1 ring-inset ring-[var(--primary)]/40',
    app:
      'bg-[var(--status-purple)]/20 ring-1 ring-inset ring-[var(--status-purple)]/40',
    mcp:
      'bg-[var(--accent)]/20 ring-1 ring-inset ring-[var(--accent)]/40',
  };

  const messageParts = useMemo(() => {
    if (!mentions.length) return [{ text: message }] as Array<{
      text: string;
      kind?: ChatMention['kind'];
    }>;

    // Map display token -> kind. If two mentions reuse the same display
    // (rare; user @-mentioned the same handle twice), the latest entry
    // wins.
    const tokenMap = new Map<string, ChatMention['kind']>();
    for (const m of mentions) tokenMap.set(m.display, m.kind);

    const tokens = Array.from(tokenMap.keys()).sort(
      (a, b) => b.length - a.length
    );
    const escaped = tokens.map((t) =>
      t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    );
    const re = new RegExp(`(${escaped.join('|')})`, 'g');

    const parts: Array<{ text: string; kind?: ChatMention['kind'] }> = [];
    let last = 0;
    for (const m of message.matchAll(re)) {
      const idx = m.index ?? 0;
      if (idx > last) parts.push({ text: message.slice(last, idx) });
      parts.push({ text: m[0], kind: tokenMap.get(m[0]) });
      last = idx + m[0].length;
    }
    if (last < message.length) parts.push({ text: message.slice(last) });
    return parts;
  }, [message, mentions]);

  // Auto-resize textarea as user types
  // Note: This causes a reflow but it's unavoidable for auto-sizing textareas
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // In chip mode the textarea is visually hidden via `w-0`; measuring
    // scrollHeight on a zero-width element makes the text wrap per-character
    // and clamps to the 200px max, pushing the whole row huge.
    if (recognizedCommand) {
      textarea.style.height = 'auto';
      return;
    }

    // Reset height to get accurate scrollHeight, then set final height
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${newHeight}px`;
  }, [message, recognizedCommand]);

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
    } else if (cmd === '/undo') {
      if (onUndo) {
        onUndo();
        setMessage('');
      }
    } else if (cmd === '/retry') {
      if (onRetry) {
        onRetry();
        setMessage('');
      }
    } else if (cmd === '/effort') {
      // Set message to "/effort " so user can type the level
      setMessage('/effort ');
      return;
    } else if (cmd === '/compact') {
      // Call the compact API endpoint directly, then reload chat
      setMessage('');
      if (onCompact) {
        onCompact();
      }
    } else if (cmd === '/help') {
      const lines = slashCommands
        .filter((c) => !c.isSkill)
        .map((c) => `${c.command} — ${c.description}`)
        .join('\n');
      toast(lines, { duration: 8000, icon: '❓', style: { whiteSpace: 'pre-line' } });
      setMessage('');
    } else if (cmd === '/new') {
      commands.executeCommand('newChatSession');
      setMessage('');
    } else if (cmd === '/model') {
      // Bare /model opens the picker; "/model <name>" is handled in sendMessage.
      commands.executeCommand('switchModel');
      setMessage('');
    } else if (cmd === '/session') {
      // Bare /session triggers a rename prompt; "/session <name>" handled in sendMessage.
      commands.executeCommand('renameChatSession');
      setMessage('');
    }
  };

  const sendMessage = async () => {
    const hasContent = message.trim() || attachments.length > 0;
    if (hasContent && !disabled) {
      const trimmed = message.trim();
      // Check if it's a built-in slash command
      if (trimmed.startsWith('/')) {
        const baseCmd = trimmed.split(' ')[0];
        const isBuiltIn = ['/clear', '/plan', '/undo', '/retry', '/help', '/new'].includes(
          baseCmd
        );
        if (isBuiltIn) {
          executeCommand(baseCmd);
        } else if (baseCmd === '/effort') {
          // /effort [low|medium|high|xhigh] — change thinking effort in real-time
          const level = trimmed.split(' ')[1]?.toLowerCase() || '';
          const validLevels = ['low', 'medium', 'high', 'xhigh', 'off', ''];
          if (level && !validLevels.includes(level)) {
            toast.error('Invalid effort level. Use: low, medium, high, xhigh, or off');
          } else {
            // Send as regular message — agent handles it server-side
            setMessageHistory((prev) => [...prev, trimmed]);
            onSendMessage(trimmed);
          }
        } else if (baseCmd === '/compact') {
          // Call the compact API endpoint, then clear chat
          if (onCompact) {
            onCompact();
          }
        } else {
          // Skill slash commands are sent as regular messages to the agent
          setMessageHistory((prev) => [...prev, trimmed]);
          const serialized = await serializeForSend();
          // Drop mentions whose display token is no longer in the message
          // (the user may have manually deleted ``@x`` after picking it).
          const liveMentions = mentions.filter((m) => trimmed.includes(m.display));
          onSendMessage(
            trimmed,
            serialized.length > 0 ? serialized : undefined,
            liveMentions.length > 0 ? liveMentions : undefined
          );
        }
      } else {
        // Regular message
        setMessageHistory((prev) => [...prev, trimmed]);
        const serialized = await serializeForSend();
        const liveMentions = mentions.filter((m) => trimmed.includes(m.display));
        onSendMessage(
          trimmed,
          serialized.length > 0 ? serialized : undefined,
          liveMentions.length > 0 ? liveMentions : undefined
        );
      }
      setMessage('');
      setHistoryIndex(-1);
      clearAttachments();
      setMentions([]);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Only send if explicitly triggered, not on form submit
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // --- Command dropdown keyboard navigation ---
    if (showCommands && filteredCommands.length > 0 && !recognizedCommand) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setCommandIndex((i) => (i + 1) % filteredCommands.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setCommandIndex((i) => (i - 1 + filteredCommands.length) % filteredCommands.length);
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        const selected = filteredCommands[commandIndex];
        setMessage(selected.command);
        setShowCommands(false);
        // Keep focus on the textarea so Enter/Escape still land on it once
        // the input flips into the hidden-chip layout.
        requestAnimationFrame(() => textareaRef.current?.focus());
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowCommands(false);
        setMessage('');
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const selected = filteredCommands[commandIndex];
        const cmd = selected.command;
        const isBuiltIn = ['/clear', '/plan', '/undo', '/retry', '/effort', '/compact'].includes(
          cmd
        );
        if (isBuiltIn) {
          executeCommand(cmd);
        } else {
          setMessageHistory((prev) => [...prev, cmd]);
          onSendMessage(cmd);
        }
        setMessage('');
        setHistoryIndex(-1);
        setShowCommands(false);
        return;
      }
    }

    // --- Escape to dismiss chip mode ---
    if (e.key === 'Escape' && recognizedCommand) {
      e.preventDefault();
      setMessage('');
      return;
    }

    // --- Up arrow - navigate backwards through history ---
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
    setShowMentionPicker(false);
  };

  // Replace the trailing ``@<query>`` token in the textarea with the
  // selected mention's display token, and record the structured mention
  // for the eventual chat request. ``offset`` lets the backend (or a
  // later renderer) align the mention token to the message body.
  const handleMentionSelect = (mention: ChatMention, item: MentionItem) => {
    const display = mention.display || `@${item.slug || item.name}`;
    setMessage((prev) => {
      const updated = prev.replace(/@\S*$/, '');
      const offset = updated.length;
      // Avoid duplicate refs for the same target — replace if already present.
      setMentions((curr) => {
        const filtered = curr.filter((m) => m.ref_id !== mention.ref_id);
        return [...filtered, { ...mention, display, offset }];
      });
      return updated + display + ' ';
    });
    setShowMentionPicker(false);
    setMentionQuery('');
    textareaRef.current?.focus();
  };

  const handleMentionFileSelect = (file: MentionPickerFile) => {
    handleFileSelect(file.path, file.display);
  };

  const handleMentionDisabled = (item: MentionItem) => {
    // Surface a hint instead of inserting. We deliberately don't navigate
    // away — that would interrupt the user's typing flow. The label tells
    // them why it's greyed.
    const reason = item.state_label || 'disabled';
    toast(`${item.name} is ${reason}. Enable it in your library to use it.`, {
      icon: 'ℹ️',
    });
  };

  // Settings drop-up — rendered inline next to the trigger button so it
  // pops up directly above the gear / compact-menu button. The trigger's
  // wrapper provides the relative positioning context.
  const renderSettingsMenu = () => (
    <div
      ref={settingsRef}
      role="menu"
      className="absolute bottom-full right-0 mb-1.5 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg min-w-[200px] z-50"
    >
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

      {isCompact && (
        <>
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
  );

  return (
    <form
      ref={containerRef}
      className={`chat-input-wrapper flex-shrink-0 relative ${isDragging ? 'ring-2 ring-[var(--primary)]/40 rounded-[var(--radius-medium)]' : ''}`}
      onSubmit={handleSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Command autocomplete dropdown */}
      {showCommands && filteredCommands.length > 0 && !recognizedCommand && (
        <div ref={commandsRef} className="absolute bottom-full left-0 right-0 mb-2 px-3 z-20">
          <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1 shadow-lg backdrop-blur-sm">
            {/* Category label */}
            {filteredCommands.some((c) => !c.isSkill) && (
              <div className="px-3 pt-1.5 pb-1">
                <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text)]/30">
                  Commands
                </span>
              </div>
            )}
            {filteredCommands
              .filter((c) => !c.isSkill)
              .map((cmd) => {
                const realIdx = filteredCommands.indexOf(cmd);
                const isSelected = realIdx === commandIndex;
                const matchLen = message.length;
                return (
                  <div
                    key={cmd.command}
                    onClick={() => {
                      setMessage(cmd.command);
                      setShowCommands(false);
                    }}
                    className={`flex items-center gap-2.5 px-3 py-1.5 rounded-[var(--radius-small)] cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-[var(--primary)]/10 text-[var(--text)]'
                        : 'hover:bg-[var(--surface-hover)] text-[var(--text)]'
                    }`}
                  >
                    <span
                      className={`shrink-0 ${isSelected ? 'text-[var(--primary)]' : 'text-[var(--text)]/40'}`}
                    >
                      {COMMAND_ICONS[cmd.command] || <Lightning size={14} weight="bold" />}
                    </span>
                    <span className="font-mono text-xs">
                      <span className="font-semibold">{cmd.command.slice(0, matchLen)}</span>
                      <span className="text-[var(--text)]/50">{cmd.command.slice(matchLen)}</span>
                    </span>
                    <span className="text-[var(--text-muted)] text-xs truncate">
                      {cmd.description}
                    </span>
                    {isSelected && (
                      <span className="ml-auto shrink-0 flex items-center gap-1 text-[10px] text-[var(--text)]/30">
                        <kbd className="px-1 py-px rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                          ↵
                        </kbd>
                      </span>
                    )}
                  </div>
                );
              })}
            {/* Skill commands section */}
            {filteredCommands.some((c) => c.isSkill) && (
              <>
                <div className="px-3 pt-2 pb-1">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text)]/30">
                    Skills
                  </span>
                </div>
                {filteredCommands
                  .filter((c) => c.isSkill)
                  .map((cmd) => {
                    const realIdx = filteredCommands.indexOf(cmd);
                    const isSelected = realIdx === commandIndex;
                    const matchLen = message.length;
                    return (
                      <div
                        key={cmd.command}
                        onClick={() => {
                          setMessage(cmd.command);
                          setShowCommands(false);
                        }}
                        className={`flex items-center gap-2.5 px-3 py-1.5 rounded-[var(--radius-small)] cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-[var(--primary)]/10 text-[var(--text)]'
                            : 'hover:bg-[var(--surface-hover)] text-[var(--text)]'
                        }`}
                      >
                        <span
                          className={`shrink-0 ${isSelected ? 'text-amber-400' : 'text-[var(--text)]/40'}`}
                        >
                          <Lightning size={14} weight="fill" />
                        </span>
                        <span className="font-mono text-xs">
                          <span className="font-semibold">{cmd.command.slice(0, matchLen)}</span>
                          <span className="text-[var(--text)]/50">
                            {cmd.command.slice(matchLen)}
                          </span>
                        </span>
                        <span className="text-[var(--text-muted)] text-xs truncate">
                          {cmd.description}
                        </span>
                        {isSelected && (
                          <span className="ml-auto shrink-0 flex items-center gap-1 text-[10px] text-[var(--text)]/30">
                            <kbd className="px-1 py-px rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                              ↵
                            </kbd>
                          </span>
                        )}
                      </div>
                    );
                  })}
              </>
            )}
            {/* Footer hints */}
            <div className="flex items-center gap-3 mt-1 pt-1.5 pb-1 px-3 border-t border-[var(--border)]">
              <span className="flex items-center gap-1 text-[10px] text-[var(--text)]/30">
                <kbd className="px-1 py-px rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                  ↑↓
                </kbd>
                navigate
              </span>
              <span className="flex items-center gap-1 text-[10px] text-[var(--text)]/30">
                <kbd className="px-1 py-px rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                  Tab
                </kbd>
                complete
              </span>
              <span className="flex items-center gap-1 text-[10px] text-[var(--text)]/30">
                <kbd className="px-1 py-px rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                  Esc
                </kbd>
                dismiss
              </span>
            </div>
          </div>
        </div>
      )}

      {/* @-mention picker — dropup above the textarea. Anchored relative
          to the form so it sits flush above the input. Renders four
          sections (Agents / Apps / Connectors / Files) and is gated on
          `showMentionPicker` from the @-detect effect above. */}
      {showMentionPicker && (
        <div className="absolute left-2 right-2 bottom-full mb-1 z-50">
          <MentionPicker
            isOpen={showMentionPicker}
            query={mentionQuery}
            agents={mentionAgents}
            mcps={mentionMcps}
            apps={mentionApps}
            files={projectSlug ? mentionFiles : []}
            loading={mentionLoading}
            onSelectMention={handleMentionSelect}
            onSelectFile={handleMentionFileSelect}
            onDisabledSelect={handleMentionDisabled}
            onClose={() => setShowMentionPicker(false)}
          />
        </div>
      )}

      {/* Settings / menu dropdown is now anchored to the trigger button
          (gear / compact-menu) below — see the toolbar render. Keeping
          this comment as a navigation breadcrumb. */}

      {/* Two-row layout */}
      <div
        className={`flex flex-col bg-[var(--surface)] w-full ${isDocked ? '' : 'border border-[var(--border)] rounded-[var(--radius)] shadow-sm'}`}
      >
        {/* First row: Growing textarea / Command chip */}
        <div
          className={`px-3 flex items-center border-b transition-colors ${
            recognizedCommand
              ? 'border-[var(--primary)]/20 bg-[var(--primary)]/[0.03]'
              : 'border-[var(--border)]'
          }`}
          style={{ minHeight: '44px' }}
        >
          {viewerMode ? (
            <div className="flex items-center gap-2 w-full py-2">
              <span className="text-xs text-[var(--text-subtle)]">
                Viewer mode — chat is read-only
              </span>
            </div>
          ) : (
            <>
              {/* Command chip overlay — visible when a command is fully recognized */}
              {recognizedCommand && (
                <div
                  className="flex items-center gap-2.5 py-2 flex-1 min-w-0 cursor-text"
                  onClick={() => textareaRef.current?.focus()}
                >
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--primary)]/10 border border-[var(--primary)]/20 shrink-0">
                    <span className="text-[var(--primary)]">
                      {COMMAND_ICONS[recognizedCommand.command] || (
                        <Lightning size={14} weight="fill" />
                      )}
                    </span>
                    <span className="font-mono text-xs font-semibold text-[var(--primary)]">
                      {recognizedCommand.command}
                    </span>
                  </div>
                  <span className="text-xs text-[var(--text-muted)] truncate">
                    {recognizedCommand.description}
                  </span>
                  <div className="ml-auto shrink-0 flex items-center gap-1.5 text-[10px] text-[var(--text)]/30">
                    <kbd className="px-1.5 py-0.5 rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[9px]">
                      ↵
                    </kbd>
                    <span>execute</span>
                  </div>
                </div>
              )}
              <div className={`relative ${recognizedCommand ? 'w-0' : 'flex-1 w-full'}`}>
                {/* Inline mention-highlight overlay — renders the same
                    text geometry as the textarea so coloured pills sit
                    exactly behind the @<token> glyphs. ``aria-hidden``
                    keeps it out of the screen-reader tree.
                */}
                {!recognizedCommand && mentions.length > 0 && (
                  <div
                    aria-hidden
                    // ``[&_*]:!text-transparent`` forces every descendant
                    // (including the kind-pill spans) to inherit
                    // transparency — defence in depth so a future pill
                    // class that introduces ``text-…`` can't ever cause
                    // the "double text" overlap again.
                    className="pointer-events-none absolute inset-0 my-2 text-sm leading-relaxed whitespace-pre-wrap break-words text-transparent [&_*]:!text-transparent"
                  >
                    {messageParts.map((p, i) =>
                      p.kind ? (
                        <span
                          key={i}
                          className={`rounded-md ${MENTION_KIND_PILL[p.kind] ?? ''}`}
                        >
                          {p.text}
                        </span>
                      ) : (
                        <span key={i}>{p.text}</span>
                      )
                    )}
                    {/* Trailing newline so wrapping width matches the
                        textarea's content rect when message ends with
                        \n (textarea adds a phantom line for the caret).
                    */}
                    {'\n'}
                  </div>
                )}
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
                  className={`relative z-[1] chat-input bg-transparent border-none text-[var(--text)] text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40 resize-none overflow-hidden leading-relaxed my-2 ${
                    recognizedCommand ? 'w-0 opacity-0 p-0 m-0' : 'w-full'
                  }`}
                  style={{
                    minHeight: recognizedCommand ? '0' : '24px',
                    maxHeight: '200px',
                  }}
                />
              </div>
            </>
          )}
        </div>

        {/* Attachment chips */}
        {attachments.length > 0 && (
          <AttachmentStrip attachments={attachments} onRemove={removeAttachment} />
        )}

        {/* Second row toolbar.
            Layout (left → right):
              [+]  [edit-mode]  [gear]  [/]  ───spacer───  [agent]  [send]
            The "+" opens a drop-up with photos/files + connectors.
            The edit-mode chip opens a drop-up with the three edit modes,
            each annotated with a tooltip describing its behaviour. */}
        <div className="flex items-center gap-1.5 px-2 py-1.5 w-full min-w-0">
          {/* + (drop-up: add photos/files + connectors) */}
          <div className="flex-shrink-0">
            <PlusMenu
              onAddImages={(files) => files.forEach((f) => addImage(f))}
              disabled={disabled || viewerMode}
            />
          </div>

          {/* Edit Mode Status — icon-only when narrow */}
          {onModeChange && (
            <div className="flex-shrink-0">
              <EditModeStatus
                mode={editMode}
                onModeChange={onModeChange}
                compact={isEditModeCompact}
              />
            </div>
          )}

          {/* Desktop: 2 individual buttons */}
          {!isCompact && (
            <>
              {/* Settings gear — drop-up anchored to this button */}
              <div className="relative flex-shrink-0">
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
                {showSettings && renderSettingsMenu()}
              </div>

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
            <div className="relative flex-shrink-0">
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
              {showSettings && renderSettingsMenu()}
            </div>
          )}

          {/* Spacer pushes agent + send to the right edge */}
          <div className="flex-1 min-w-0" />

          {/* Agent selector — moved to the right */}
          <div className="min-w-0 shrink">
            <AgentSelector
              agents={agents}
              currentAgent={currentAgent}
              onSelectAgent={onSelectAgent}
              onModelChange={onModelChange}
              compact={isCompact}
            />
          </div>

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
