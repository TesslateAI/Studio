export interface ToolCallDetail {
  name: string;
  parameters: Record<string, unknown>;
  result?: {
    success: boolean;
    tool: string;
    result?: unknown;
    error?: string;
  };
}

export interface AgentStep {
  iteration: number;
  thought?: string;
  tool_calls: ToolCallDetail[];
  tool_results?: Array<{
    success: boolean;
    tool: string;
    result?: unknown;
    error?: string;
  }>;
  response_text: string;
  is_complete: boolean;
  timestamp: string;
  _debug?: {
    full_response?: string;
    context_messages_count?: number;
    context_messages?: Array<{ role: string; content: string }>;
    raw_tool_calls?: Array<{ name: string; params: Record<string, unknown> }>;
    raw_thought?: string;
    is_complete?: boolean;
    conversational_text?: string;
    display_text?: string;
  };
}

export interface AgentChatRequest {
  project_id?: string;
  message: string;
  agent_id?: string; // ID of the agent to use
  container_id?: string; // If set, agent is scoped to this container (files at root)
  chat_id?: string; // Target a specific chat session
  max_iterations?: number;
  minimal_prompts?: boolean;
  edit_mode?: 'allow' | 'ask' | 'plan'; // Edit control mode
  view_context?: string; // UI view context: 'graph', 'builder', 'terminal', 'kanban'
  attachments?: SerializedAttachment[];
}

export interface AgentChatResponse {
  success: boolean;
  iterations: number;
  final_response: string;
  tool_calls_made: number;
  completion_reason: string;
  steps: AgentStep[];
  error?: string;
}

export interface AgentMessageData {
  steps: AgentStep[];
  iterations: number;
  tool_calls_made: number;
  completion_reason: string;
  currentThinking?: string;
}

export interface DBMessage {
  id: string;
  chat_id: string;
  role: 'user' | 'assistant';
  content: string;
  message_metadata?: {
    agent_mode?: boolean;
    agent_type?: string;
    steps?: AgentStep[];
    iterations?: number;
    tool_calls_made?: number;
    completion_reason?: string;
    attachments?: SerializedAttachment[];
  };
  created_at: string;
}

export interface ApprovalRequestData {
  approval_id: string;
  tool_name: string;
  tool_parameters: Record<string, unknown>;
  tool_description: string;
}

export interface ApprovalMessage {
  id: string;
  type: 'approval_request';
  approvalId: string;
  toolName: string;
  toolParameters: Record<string, unknown>;
  toolDescription: string;
}

export interface Agent {
  id: string;
  name: string;
  slug: string;
  description?: string;
  system_prompt?: string;
  icon: string;
  mode: 'stream' | 'agent';
  agent_type?: string; // StreamAgent, IterativeAgent, etc.
  category?: string;
  features?: string[];
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AgentCreate {
  name: string;
  slug: string;
  description?: string;
  system_prompt: string;
  icon?: string;
  mode?: 'stream' | 'agent';
  is_active?: boolean;
}

export type AttachmentType = 'image' | 'pasted_text' | 'file_reference';

export interface ChatAttachment {
  id: string;
  type: AttachmentType;
  file?: File;
  previewUrl?: string;
  mimeType?: string;
  text?: string;
  lineCount?: number;
  filePath?: string;
  fileName?: string;
}

export interface SerializedAttachment {
  type: AttachmentType;
  content?: string;
  mime_type?: string;
  file_path?: string;
  label?: string;
}
