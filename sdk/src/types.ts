// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface Project {
  id: string;
  name: string;
  description: string | null;
  slug: string;
  owner_id: string;
  network_name: string | null;
  created_at: string;
  updated_at: string | null;
  environment_status: string | null;
  hibernated_at: string | null;
  compute_tier: string;
}

export interface ProjectCreateOptions {
  name: string;
  description?: string;
  base_id?: string;
  source_type?: string;
  git_url?: string;
}

export interface ProjectCreateResult {
  project: Project;
  task_id: string;
  status_endpoint: string;
}

// ---------------------------------------------------------------------------
// Containers
// ---------------------------------------------------------------------------

export interface Container {
  id: string;
  name: string;
  project_id: string;
  base_image: string | null;
  startup_command: string | null;
  ports: Record<string, number> | null;
  status: string | null;
}

export interface ContainerStartResult {
  message: string;
  project_slug: string;
  containers: Record<string, unknown>;
  network: string | null;
  namespace: string | null;
  deployment_mode: string;
}

export interface ContainerStopResult {
  message: string;
  deployment_mode: string;
}

export interface ContainerCreateOptions {
  name: string;
  base_image?: string;
  startup_command?: string;
  ports?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

export interface FileTreeEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mod_time: number;
}

export interface FileTreeResult {
  status: string;
  files: FileTreeEntry[];
  message?: string;
}

export interface FileReadResult {
  status: string;
  path: string;
  content: string;
  size: number;
  message?: string;
}

export interface FileBatchReadResult {
  status: string;
  files: Array<{ path: string; content: string; size: number }>;
  errors: Array<{ path: string; error: string }>;
  message?: string;
}

export interface FileWriteResult {
  message: string;
  file_path: string;
  method: string;
}

export interface FileDeleteResult {
  message: string;
  file_path: string;
}

export interface FileRenameResult {
  message: string;
  old_path: string;
  new_path: string;
}

export interface FileMkdirResult {
  message: string;
  dir_path: string;
}

// ---------------------------------------------------------------------------
// Agent
// ---------------------------------------------------------------------------

export interface AgentInvokeOptions {
  project_id: string;
  message: string;
  container_id?: string;
  agent_id?: string;
  webhook_callback_url?: string;
}

export interface AgentInvokeResult {
  task_id: string;
  chat_id: string;
  events_url: string;
  status: string;
}

export interface AgentTaskStatus {
  task_id: string;
  status: string;
  final_response: string | null;
  iterations: number | null;
  tool_calls_made: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentEvent {
  type: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

export interface ShellSession {
  session_id: string;
  status: string;
  created_at: string;
}

export interface ShellCreateOptions {
  project_id: string;
  command?: string;
  container_name?: string;
}

export interface ShellWriteResult {
  success: boolean;
  bytes_written: number;
}

export interface ShellOutputResult {
  output: string;
  bytes: number;
  is_eof: boolean;
}

// ---------------------------------------------------------------------------
// Git
// ---------------------------------------------------------------------------

export interface GitStatus {
  branch: string;
  ahead: number;
  behind: number;
  staged_count: number;
  unstaged_count: number;
  untracked_count: number;
  has_conflicts: boolean;
  changes: Array<{
    file_path: string;
    status: string;
    staged: boolean;
  }>;
  remote_branch: string | null;
  last_commit: Record<string, unknown> | null;
}

export interface GitCommitResult {
  sha: string;
  message: string;
}

export interface GitPushResult {
  success: boolean;
  message: string;
}

export interface GitPullResult {
  success: boolean;
  conflicts: string[];
  message: string;
}

export interface GitBranchInfo {
  name: string;
  current: boolean;
  remote: boolean;
}

export interface GitBranchesResult {
  branches: GitBranchInfo[];
  current_branch: string | null;
}
