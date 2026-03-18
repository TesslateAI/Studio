export interface LibraryAgent {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  mode: string;
  agent_type: string;
  model: string;
  selected_model?: string | null;
  source_type: 'open' | 'closed';
  is_forkable: boolean;
  icon: string;
  avatar_url?: string | null;
  pricing_type: string;
  features: string[];
  tools?: string[] | null;
  tool_configs?: Record<
    string,
    { description?: string; examples?: string[]; system_prompt?: string }
  > | null;
  purchase_date: string;
  purchase_type: string;
  expires_at: string | null;
  is_custom: boolean;
  parent_agent_id: string | null;
  system_prompt?: string;
  config?: {
    features?: Record<string, boolean>;
    [key: string]: unknown;
  };
  is_enabled?: boolean;
  is_published?: boolean;
  usage_count?: number;
  creator_type?: 'official' | 'community';
  creator_name?: string;
  creator_username?: string | null;
  creator_avatar_url?: string | null;
  created_by_user_id?: string | null;
  forked_by_user_id?: string | null;
}

export interface SubagentItem {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  model: string;
  is_builtin: boolean;
}

export const FEATURE_FLAGS = [
  { key: 'streaming', label: 'Streaming', description: 'SSE token streaming' },
  { key: 'subagents', label: 'Subagents', description: 'Invoke specialized subagents' },
  { key: 'plan_mode', label: 'Plan Mode', description: 'save_plan / update_plan tools' },
  { key: 'web_search', label: 'Web Search', description: 'web_fetch tool' },
  { key: 'apply_patch', label: 'Apply Patch', description: 'Unified diff patches' },
] as const;
