/* eslint-disable react-refresh/only-export-components */
/**
 * Chat Position Context
 *
 * Manages the user's preference for where the chat panel appears in the builder.
 * Supports: 'left', 'center' (default), 'right'
 *
 * Features:
 * - Non-blocking initialization (defaults to 'center' while loading)
 * - Optimistic updates (UI updates immediately, persists to API asynchronously)
 * - Error recovery (reverts to previous value on API failure)
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { usersApi, type ChatPosition } from '../lib/api';

interface ChatPositionContextValue {
  chatPosition: ChatPosition;
  setChatPosition: (position: ChatPosition) => Promise<void>;
  isLoading: boolean;
}

const ChatPositionContext = createContext<ChatPositionContextValue | null>(null);

export function ChatPositionProvider({ children }: { children: ReactNode }) {
  const [chatPosition, setPositionState] = useState<ChatPosition>('center');
  const [isLoading, setIsLoading] = useState(true);

  // Load user's chat position preference on mount
  useEffect(() => {
    const loadPreferences = async () => {
      try {
        const prefs = await usersApi.getPreferences();
        if (prefs.chat_position) {
          setPositionState(prefs.chat_position);
        }
      } catch (error) {
        // Silently fail - user might not be authenticated yet
        console.debug('Failed to load chat position preference:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadPreferences();
  }, []);

  // Update chat position with optimistic update
  const setChatPosition = useCallback(
    async (position: ChatPosition) => {
      const previousPosition = chatPosition;

      // Optimistic update - change UI immediately
      setPositionState(position);

      try {
        await usersApi.updatePreferences({ chat_position: position });
      } catch (error) {
        // Revert on failure
        console.error('Failed to save chat position preference:', error);
        setPositionState(previousPosition);
        throw error;
      }
    },
    [chatPosition]
  );

  return (
    <ChatPositionContext.Provider
      value={{
        chatPosition,
        setChatPosition,
        isLoading,
      }}
    >
      {children}
    </ChatPositionContext.Provider>
  );
}

export function useChatPosition() {
  const context = useContext(ChatPositionContext);
  if (!context) {
    throw new Error('useChatPosition must be used within ChatPositionProvider');
  }
  return context;
}

// Export type for convenience
export type { ChatPosition };
