// Client
export { TesslateClient } from "./client.js";
export type { TesslateClientOptions } from "./client.js";

// Errors
export {
  TesslateApiError,
  TesslateAuthError,
  TesslateError,
  TesslateForbiddenError,
  TesslateNotFoundError,
} from "./errors.js";

// Types
export type {
  AgentEvent,
  AgentInvokeOptions,
  AgentInvokeResult,
  AgentTaskStatus,
  Container,
  ContainerCreateOptions,
  ContainerStartResult,
  ContainerStopResult,
  FileBatchReadResult,
  FileDeleteResult,
  FileMkdirResult,
  FileReadResult,
  FileRenameResult,
  FileTreeEntry,
  FileTreeResult,
  FileWriteResult,
  GitBranchesResult,
  GitBranchInfo,
  GitCommitResult,
  GitPullResult,
  GitPushResult,
  GitStatus,
  Project,
  ProjectCreateOptions,
  ProjectCreateResult,
  ShellCreateOptions,
  ShellOutputResult,
  ShellSession,
  ShellWriteResult,
} from "./types.js";

// Resources (for advanced composition)
export { AgentResource } from "./resources/agent.js";
export { ContainersResource } from "./resources/containers.js";
export { FilesResource } from "./resources/files.js";
export { GitResource } from "./resources/git.js";
export { ProjectsResource } from "./resources/projects.js";
export { ShellResource } from "./resources/shell.js";

// Utilities
export { parseSSE } from "./sse.js";
