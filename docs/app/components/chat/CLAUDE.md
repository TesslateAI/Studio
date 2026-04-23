# Chat Components

Every chat UI surface lives in `app/src/components/chat/`. The chat system spans standalone chat (`pages/Chat.tsx`) and the project-builder sidebar (`ChatContainer.tsx`).

## File Index

| File | Purpose |
|------|---------|
| `chat/ChatContainer.tsx` | Project-builder chat. Owns the WebSocket, agent-step rendering, approval flow, edit mode (ask/allow/plan), message persistence, mobile sheet layout. Uses `isMountedRef` to guard against orphaned SSE/WS callbacks |
| `chat/ChatMessage.tsx` | Single user/AI bubble with copy, regenerate (ArrowClockwise), markdown + GFM rendering (ReactMarkdown + remark-gfm), attachments strip, action row |
| `chat/ChatMessageList.tsx` | Scrollable message list. Auto-scroll logic with `isUserScrollingRef` to respect manual scrolling. Renders `ChatMessage`, `AgentMessage`, `ApprovalRequestCard` |
| `chat/ChatInput.tsx` | Message input with attachment picker, slash-command dropdown, model/agent pills, edit-mode button, file-picker (`@filename`) dropdown, history (up/down arrows), chip-mode when exact command match |
| `chat/ChatTopBar.tsx` | Standalone chat top bar (sidebar toggle, home link, session title, `ProjectConnector`) |
| `chat/ChatSessionSidebar.tsx` | Standalone chat left sidebar: session list, new session, rename, delete, collapse/expand |
| `chat/ChatSessionPopover.tsx` | Project-builder session switcher popover: list, search, create, rename, delete for the active project's sessions |
| `chat/ChatSessionModal.tsx` | Full-screen session management modal (larger alternative to popover) |
| `chat/AgentSelector.tsx` | Dropdown for switching the active agent. Shows icon, name, model; search filter; navigate to library button |
| `chat/ModelSelector.tsx` | Model picker portal (rendered via createPortal). Search, caret, check for active model. Populated from `marketplaceApi.getModels` |
| `chat/ApprovalRequestCard.tsx` | Rendered in-line when agent requests approval. Buttons: `Allow Once` / `Allow All` / `Stop`. Shows tool name, parameters, description |
| `chat/EditModeStatus.tsx` | Pill with three states: `ask` (approve every dangerous op), `allow` (auto-approve), `plan` (generate plan without executing) |
| `chat/ToolDropdown.tsx` | Dropdown of tools/actions (attach file, paste file, add image, etc.). Category: `actions` / `tools` |
| `chat/ToolDebugModal.tsx` | Developer tool for invoking tools manually with JSON parameters; shows result, timing, errors. Rendered via createPortal |
| `chat/TypingIndicator.tsx` | Animated three-dot indicator for streaming state |
| `chat/UsageRibbon.tsx` | Top-of-chat banner showing credits remaining + "Get More" CTA |
| `chat/AttachmentChip.tsx` | Single attachment pill with preview, filename, remove-button; handles both `ChatAttachment` (pre-upload) and `SerializedAttachment` (persisted) |
| `chat/AttachmentStrip.tsx` | Horizontal row of `AttachmentChip`s above the input |
| `chat/FilePickerDropdown.tsx` | `@filename` autocomplete dropdown. Debounced search via `projectsApi.searchFiles` |
| `chat/CitationCard.tsx` | MCP tool-result citation card (MCP spec 2025-06-18+); renders `_mcp_structured.citation` with external-link icon |
| `chat/ReauthBanner.tsx` | Yellow banner when an MCP tool returns `_mcp_reauth_required`; CTA to `/settings/connectors` |
| `chat/ProjectConnector.tsx` | Standalone-chat widget to attach/detach a session to a project; search, select, remove |
| `chat/index.ts` | Barrel export |

## Streaming Event Types (WebSocket + SSE)

| Event | Purpose |
|-------|---------|
| `text_delta` | Real-time token-by-token streaming between tool calls |
| `agent_step` | A completed agent iteration (tool calls + result summary) |
| `agent_task_started` | Execution kicked off (from another origin like API) |
| `agent_task_completed` | Final response ready |
| `agent_task_error` | Execution failed |
| `approval_required` | Show `ApprovalRequestCard` |
| `approval_response` | (client -> server) Reply to approval |
| `complete` | Stream finished |

## Key Invariants

1. `text_delta` creates a streaming message with id `${thinkingMessageId}-stream` inserted before the thinking indicator; subsequent deltas append.
2. Tool iteration messages use id `${thinkingMessageId}-iter-${iteration}` to deduplicate parallel tool calls within one iteration.
3. `chatApi.undoLastExchange(chatId)` powers both `/undo` and `/retry` (retry re-sends the returned `last_user_message`).
4. `isMountedRef` guards every setState inside WS/SSE callbacks; the backend keeps running even after navigation.
5. When metadata `steps_table: true` is present, fetch steps separately via `chatApi.getMessageSteps(messageId)`.

## Built-in Slash Commands

| Command | Action |
|---------|--------|
| `/clear` | Delete all messages in session |
| `/undo` | Undo last user+AI exchange |
| `/retry` | `/undo` then re-send the removed user message |

Installed skills (e.g., `/docker-dev`) appear as slash commands too. All are disabled while agent is `running` / `waiting_approval`.

## Related Docs

- `docs/app/hooks/CLAUDE.md` – `useAgentChat`, `useChatSessions`, `useAttachments`
- `docs/app/pages/CLAUDE.md` – standalone `Chat.tsx` and project-builder integration
- `docs/app/api/chat-api.md` – chatApi walkthrough
