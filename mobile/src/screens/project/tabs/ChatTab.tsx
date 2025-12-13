import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../../theme/ThemeContext';
import { chatApi, marketplaceApi } from '../../../lib/api';
import Toast from 'react-native-toast-message';
import type { DBMessage, AgentStep } from '../../../types/agent';

const ChatTab: React.FC = () => {
  const route = useRoute();
  const { theme } = useTheme();
  const { projectSlug } = route.params as { projectSlug: string };

  const [messages, setMessages] = useState<DBMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [showAgentPicker, setShowAgentPicker] = useState(false);

  const flatListRef = useRef<FlatList>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchMessages();
    fetchAgents();
  }, []);

  const fetchMessages = async () => {
    try {
      const data = await chatApi.getProjectMessages(projectSlug);
      setMessages(data);
    } catch (error) {
      console.error('Failed to fetch messages:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchAgents = async () => {
    try {
      const data = await marketplaceApi.getProjectAgents(projectSlug);
      setAgents(data);
      if (data.length > 0 && !selectedAgentId) {
        setSelectedAgentId(data[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch agents:', error);
    }
  };

  const handleSendMessage = async () => {
    if (!inputText.trim() || isSending) return;

    const userMessage = inputText.trim();
    setInputText('');
    setIsSending(true);

    // Add user message optimistically
    const tempUserMessage: DBMessage = {
      id: `temp-${Date.now()}`,
      chat_id: projectSlug,
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMessage]);

    // Scroll to bottom
    setTimeout(() => {
      flatListRef.current?.scrollToEnd({ animated: true });
    }, 100);

    try {
      // Create abort controller
      abortControllerRef.current = new AbortController();

      // Prepare request
      const request = {
        project_id: projectSlug,
        message: userMessage,
        agent_id: selectedAgentId || undefined,
      };

      // Add assistant message placeholder
      const tempAssistantMessage: DBMessage = {
        id: `temp-assistant-${Date.now()}`,
        chat_id: projectSlug,
        role: 'assistant',
        content: '',
        message_metadata: {
          agent_mode: true,
          steps: [],
          iterations: 0,
          tool_calls_made: 0,
          completion_reason: 'in_progress',
        },
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, tempAssistantMessage]);

      // Stream response
      let currentSteps: AgentStep[] = [];
      let finalResponse = '';

      await chatApi.sendAgentMessageStreaming(
        request,
        (event) => {
          if (event.type === 'iteration') {
            const step: AgentStep = event.data;
            currentSteps = [...currentSteps, step];

            // Update assistant message with current progress
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === tempAssistantMessage.id
                  ? {
                      ...msg,
                      content: step.response_text || '',
                      message_metadata: {
                        ...msg.message_metadata,
                        steps: currentSteps,
                        iterations: step.iteration,
                      },
                    }
                  : msg
              )
            );

            // Scroll to bottom
            setTimeout(() => {
              flatListRef.current?.scrollToEnd({ animated: true });
            }, 100);
          } else if (event.type === 'complete') {
            finalResponse = event.data.final_response;

            // Update assistant message with final result
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === tempAssistantMessage.id
                  ? {
                      ...msg,
                      content: finalResponse,
                      message_metadata: {
                        ...msg.message_metadata,
                        completion_reason: event.data.completion_reason,
                        tool_calls_made: event.data.tool_calls_made,
                      },
                    }
                  : msg
              )
            );
          } else if (event.type === 'error') {
            Toast.show({
              type: 'error',
              text1: 'Error',
              text2: event.data.error || 'Failed to get response',
            });

            // Remove temp assistant message
            setMessages((prev) =>
              prev.filter((msg) => msg.id !== tempAssistantMessage.id)
            );
          }
        },
        abortControllerRef.current.signal
      );

      // Fetch updated messages from server
      await fetchMessages();
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('Request aborted');
      } else {
        console.error('Failed to send message:', error);
        Toast.show({
          type: 'error',
          text1: 'Error',
          text2: 'Failed to send message',
        });
      }
    } finally {
      setIsSending(false);
      abortControllerRef.current = null;
    }
  };

  const handleCancelRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsSending(false);
      Toast.show({
        type: 'info',
        text1: 'Cancelled',
        text2: 'Request cancelled',
      });
    }
  };

  const renderMessage = ({ item }: { item: DBMessage }) => {
    const isUser = item.role === 'user';

    return (
      <View
        style={[
          styles.messageContainer,
          isUser ? styles.userMessageContainer : styles.assistantMessageContainer,
        ]}
      >
        <View
          style={[
            styles.messageBubble,
            {
              backgroundColor: isUser ? theme.primary : theme.card,
              borderColor: theme.border,
            },
          ]}
        >
          <Text
            style={[
              styles.messageText,
              { color: isUser ? '#FFFFFF' : theme.text },
            ]}
          >
            {item.content}
          </Text>

          {/* Show agent steps */}
          {!isUser && item.message_metadata?.steps && item.message_metadata.steps.length > 0 && (
            <View style={styles.stepsContainer}>
              {item.message_metadata.steps.map((step, index) => (
                <View key={index} style={[styles.stepItem, { borderLeftColor: theme.primary }]}>
                  <Text style={[styles.stepLabel, { color: theme.textSecondary }]}>
                    Iteration {step.iteration}
                  </Text>
                  {step.thought && (
                    <Text style={[styles.stepThought, { color: theme.textSecondary }]}>
                      💭 {step.thought}
                    </Text>
                  )}
                  {step.tool_calls && step.tool_calls.length > 0 && (
                    <View style={styles.toolCalls}>
                      {step.tool_calls.map((tool, toolIndex) => (
                        <View key={toolIndex} style={[styles.toolCall, { backgroundColor: theme.backgroundSecondary }]}>
                          <Text style={[styles.toolName, { color: theme.primary }]}>
                            🔧 {tool.name}
                          </Text>
                          {tool.result && (
                            <Text
                              style={[
                                styles.toolResult,
                                {
                                  color: tool.result.success ? theme.success : theme.error,
                                },
                              ]}
                            >
                              {tool.result.success ? '✓' : '✗'}{' '}
                              {tool.result.success ? 'Success' : 'Failed'}
                            </Text>
                          )}
                        </View>
                      ))}
                    </View>
                  )}
                </View>
              ))}
            </View>
          )}

          <Text style={[styles.messageTime, { color: isUser ? '#FFFFFF99' : theme.textTertiary }]}>
            {new Date(item.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: theme.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 100 : 0}
    >
      {/* Messages List */}
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          data={messages}
          renderItem={renderMessage}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.messagesList}
          onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
          onLayout={() => flatListRef.current?.scrollToEnd({ animated: true })}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="chatbubbles-outline" size={64} color={theme.textTertiary} />
              <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                Start a conversation with your AI agent
              </Text>
            </View>
          }
        />
      )}

      {/* Agent Selector */}
      {agents.length > 0 && (
        <View style={[styles.agentSelector, { backgroundColor: theme.backgroundSecondary }]}>
          <TouchableOpacity
            style={styles.agentButton}
            onPress={() => setShowAgentPicker(!showAgentPicker)}
          >
            <Ionicons name="person-circle" size={20} color={theme.primary} />
            <Text style={[styles.agentName, { color: theme.text }]}>
              {agents.find((a) => a.id === selectedAgentId)?.name || 'Select Agent'}
            </Text>
            <Ionicons
              name={showAgentPicker ? 'chevron-up' : 'chevron-down'}
              size={16}
              color={theme.textTertiary}
            />
          </TouchableOpacity>

          {showAgentPicker && (
            <View style={[styles.agentPicker, { backgroundColor: theme.card, borderColor: theme.border }]}>
              {agents.map((agent) => (
                <TouchableOpacity
                  key={agent.id}
                  style={[
                    styles.agentOption,
                    selectedAgentId === agent.id && { backgroundColor: theme.primaryLight },
                  ]}
                  onPress={() => {
                    setSelectedAgentId(agent.id);
                    setShowAgentPicker(false);
                  }}
                >
                  <Text style={[styles.agentOptionName, { color: theme.text }]}>
                    {agent.name}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          )}
        </View>
      )}

      {/* Input Area */}
      <View style={[styles.inputContainer, { backgroundColor: theme.card, borderTopColor: theme.border }]}>
        <TextInput
          style={[styles.input, { color: theme.text, backgroundColor: theme.backgroundSecondary }]}
          placeholder="Type a message..."
          placeholderTextColor={theme.textTertiary}
          value={inputText}
          onChangeText={setInputText}
          multiline
          maxLength={2000}
          editable={!isSending}
        />
        {isSending ? (
          <TouchableOpacity style={styles.sendButton} onPress={handleCancelRequest}>
            <Ionicons name="stop-circle" size={28} color={theme.error} />
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={styles.sendButton}
            onPress={handleSendMessage}
            disabled={!inputText.trim()}
          >
            <Ionicons
              name="send"
              size={24}
              color={inputText.trim() ? theme.primary : theme.textTertiary}
            />
          </TouchableOpacity>
        )}
      </View>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  messagesList: {
    padding: 16,
  },
  messageContainer: {
    marginBottom: 16,
  },
  userMessageContainer: {
    alignItems: 'flex-end',
  },
  assistantMessageContainer: {
    alignItems: 'flex-start',
  },
  messageBubble: {
    maxWidth: '80%',
    padding: 12,
    borderRadius: 16,
    borderWidth: 1,
  },
  messageText: {
    fontSize: 15,
    lineHeight: 22,
  },
  messageTime: {
    fontSize: 11,
    marginTop: 6,
  },
  stepsContainer: {
    marginTop: 12,
    gap: 8,
  },
  stepItem: {
    borderLeftWidth: 3,
    paddingLeft: 12,
    paddingVertical: 4,
  },
  stepLabel: {
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 4,
  },
  stepThought: {
    fontSize: 13,
    marginBottom: 6,
    fontStyle: 'italic',
  },
  toolCalls: {
    gap: 6,
  },
  toolCall: {
    padding: 8,
    borderRadius: 8,
  },
  toolName: {
    fontSize: 13,
    fontWeight: '600',
  },
  toolResult: {
    fontSize: 12,
    marginTop: 4,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 80,
  },
  emptyText: {
    fontSize: 16,
    marginTop: 16,
    textAlign: 'center',
  },
  agentSelector: {
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  agentButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
  },
  agentName: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
  },
  agentPicker: {
    marginTop: 8,
    borderRadius: 8,
    borderWidth: 1,
    overflow: 'hidden',
  },
  agentOption: {
    padding: 12,
  },
  agentOptionName: {
    fontSize: 14,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 12,
    borderTopWidth: 1,
  },
  input: {
    flex: 1,
    maxHeight: 100,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 20,
    fontSize: 15,
  },
  sendButton: {
    marginLeft: 8,
    padding: 8,
  },
});

export default ChatTab;
