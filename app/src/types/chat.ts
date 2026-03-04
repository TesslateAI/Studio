/** Lightweight agent representation used across chat UI components */
export interface ChatAgent {
  id: string;
  name: string;
  icon: string; // Emoji string from backend
  avatar_url?: string; // Uploaded logo URL
  active?: boolean;
  backendId?: number; // Link to backend agent ID
  mode?: 'stream' | 'agent';
  model?: string;
  selectedModel?: string | null;
  sourceType?: 'open' | 'closed';
  isCustom?: boolean;
}
