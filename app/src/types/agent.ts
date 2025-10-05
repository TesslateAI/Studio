export interface AgentStep {
  iteration: number;
  thought?: string;
  tool_calls: string[];
  response_text: string;
  is_complete: boolean;
  timestamp: string;
}

export interface AgentChatRequest {
  project_id: number;
  message: string;
  max_iterations?: number;
  minimal_prompts?: boolean;
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
}
