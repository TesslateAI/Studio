import { useRef, useEffect } from 'react';
import { ChatMessage } from './ChatMessage';
import AgentMessage from '../AgentMessage';
import { ApprovalRequestCard } from './ApprovalRequestCard';
import { BuilderReviewCard } from './BuilderReviewCard';
import type { ChatMessage as ChatMessageType } from '../../hooks/useAgentChat';

interface ChatMessageListProps {
  messages: ChatMessageType[];
  isExecuting: boolean;
  onApproval?: (
    approvalId: string,
    response:
      | 'allow_once'
      | 'allow_all'
      | 'stop'
      | 'publish_and_activate'
      | 'save_draft'
      | 'cancel',
    toolName: string
  ) => void;
  emptyState?: React.ReactNode;
  toolCallsCollapsed?: boolean;
  onRetry?: () => void;
}

export function ChatMessageList({
  messages,
  isExecuting,
  onApproval,
  emptyState,
  toolCallsCollapsed,
  onRetry,
}: ChatMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrollingRef = useRef(false);

  // Track scroll position
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      isUserScrollingRef.current = scrollHeight - scrollTop - clientHeight > 100;
    };
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    if (!containerRef.current || !messagesEndRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
    const lastMessage = messages[messages.length - 1];
    const isNewUserMessage = lastMessage?.type === 'user';

    if (isNewUserMessage || !isUserScrollingRef.current || isNearBottom) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
      isUserScrollingRef.current = false;
    }
  }, [messages]);

  if (messages.length === 0 && !isExecuting) {
    return (
      <div ref={containerRef} className="flex-1 overflow-y-auto flex items-center justify-center">
        {emptyState || (
          <div className="text-center px-6">
            <img src="/favicon.svg" alt="" className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-xs text-[var(--text-muted)]">Start a conversation</p>
            <p className="text-[10px] text-[var(--text-subtle)] mt-1">
              Ask anything — connect a project for file access
            </p>
          </div>
        )}
      </div>
    );
  }

  const lastAiId = messages.findLast((m) => m.type === 'ai')?.id;

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto">
      <div className="w-full px-3 sm:px-4 py-3 sm:py-4 space-y-3">
        {messages.map((msg) => {
          if (msg.type === 'approval_request') {
            return (
              <ApprovalRequestCard
                key={msg.id}
                approvalId={msg.approvalId || ''}
                toolName={msg.toolName || 'Unknown'}
                toolDescription={msg.toolDescription || ''}
                toolParameters={msg.toolParameters || {}}
                onRespond={(approvalId, response, toolName) =>
                  onApproval?.(approvalId, response, toolName)
                }
              />
            );
          }

          if (msg.type === 'builder_review_request') {
            return (
              <BuilderReviewCard
                key={msg.id}
                approvalId={msg.approvalId || ''}
                summary={msg.builderReviewSummary || { name: 'Draft agent' }}
                onRespond={(approvalId, response) =>
                  onApproval?.(approvalId, response, 'request_review')
                }
              />
            );
          }

          if (msg.type === 'ai' && msg.agentData) {
            return (
              <AgentMessage
                key={msg.id}
                agentData={msg.agentData}
                finalResponse={msg.content}
                agentAvatarUrl={msg.agentAvatarUrl}
                toolCallsCollapsed={toolCallsCollapsed}
              />
            );
          }

          return (
            <ChatMessage
              key={msg.id}
              type={msg.type as 'user' | 'ai'}
              content={msg.content}
              attachments={msg.attachments}
              onRetry={onRetry}
              showRetry={msg.type === 'ai' && msg.id === lastAiId && !isExecuting}
            />
          );
        })}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
