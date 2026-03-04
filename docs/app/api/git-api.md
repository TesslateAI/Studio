# Git API

The Git API provides version control operations for projects, supporting multiple providers (GitHub, GitLab, Bitbucket).

**File**: `app/src/lib/git-api.ts`

## Overview

The Git API wraps the shared axios instance from `api.ts` and provides typed methods for all git operations:

```typescript
import api from './api';

export const gitApi = {
  // All git operations...
};
```

## Repository Initialization

### Initialize Repository

Create a new git repository in a project:

```typescript
init: async (projectId: number, repoUrl?: string): Promise<GitRepositoryResponse> => {
  const response = await api.post(`/api/projects/${projectId}/git/init`, {
    repo_url: repoUrl,
  } as GitInitRequest);
  return response.data;
}
```

### Clone Repository

Clone an existing repository into a project:

```typescript
clone: async (projectId: number, repoUrl: string, branch?: string): Promise<GitRepositoryResponse> => {
  const response = await api.post(`/api/projects/${projectId}/git/clone`, {
    repo_url: repoUrl,
    branch: branch || 'main',
  } as GitCloneRequest);
  return response.data;
}
```

### Get Repository Info

```typescript
getRepositoryInfo: async (projectId: number): Promise<GitRepositoryResponse> => {
  const response = await api.get(`/api/projects/${projectId}/git/info`);
  return response.data;
}
```

### Disconnect Repository

```typescript
disconnect: async (projectId: number): Promise<void> => {
  await api.delete(`/api/projects/${projectId}/git/disconnect`);
}
```

## Status and Diff

### Get Status

Get current repository status (staged, modified, untracked files):

```typescript
getStatus: async (projectId: number): Promise<GitStatusResponse> => {
  const response = await api.get(`/api/projects/${projectId}/git/status`);
  return response.data;
}
```

### Get Diff

Get diff for uncommitted changes:

```typescript
getDiff: async (projectId: number, filePath?: string): Promise<GitDiffResponse> => {
  const response = await api.get(`/api/projects/${projectId}/git/diff`, {
    params: filePath ? { file_path: filePath } : undefined,
  });
  return response.data;
}
```

## Commit Operations

### Create Commit

```typescript
commit: async (projectId: number, message: string, files?: string[]): Promise<GitCommitResponse> => {
  const response = await api.post(`/api/projects/${projectId}/git/commit`, {
    message,
    files,
  } as GitCommitRequest);
  return response.data;
}
```

Parameters:
- `message`: Commit message (required)
- `files`: Optional array of specific files to commit. If omitted, commits all staged changes.

### Get Commit History

```typescript
getCommitHistory: async (projectId: number, limit: number = 50): Promise<GitHistoryResponse> => {
  const response = await api.get(`/api/projects/${projectId}/git/commits`, {
    params: { limit },
  });
  return response.data;
}
```

## Remote Operations

### Push

Push commits to remote repository:

```typescript
push: async (
  projectId: number,
  branch?: string,
  remote?: string,
  force?: boolean
): Promise<GitPushResponse> => {
  const response = await api.post(`/api/projects/${projectId}/git/push`, {
    branch,
    remote,
    force,
  } as GitPushRequest);
  return response.data;
}
```

### Pull

Pull changes from remote:

```typescript
pull: async (projectId: number, branch?: string, remote?: string): Promise<GitPullResponse> => {
  const response = await api.post(`/api/projects/${projectId}/git/pull`, {
    branch,
    remote,
  } as GitPullRequest);
  return response.data;
}
```

## Branch Management

### List Branches

```typescript
getBranches: async (projectId: number): Promise<GitBranchesResponse> => {
  const response = await api.get(`/api/projects/${projectId}/git/branches`);
  return response.data;
}
```

### Create Branch

```typescript
createBranch: async (
  projectId: number,
  name: string,
  checkout: boolean = false
): Promise<void> => {
  await api.post(`/api/projects/${projectId}/git/branches`, {
    name,
    checkout,
  } as GitBranchRequest);
}
```

### Switch Branch

```typescript
switchBranch: async (projectId: number, branch: string): Promise<void> => {
  await api.put(`/api/projects/${projectId}/git/branches/switch`, {
    branch,
  } as GitSwitchBranchRequest);
}
```

## Type Definitions

From `app/src/types/git.ts`:

```typescript
interface GitRepositoryResponse {
  initialized: boolean;
  remote_url?: string;
  current_branch?: string;
  provider?: 'github' | 'gitlab' | 'bitbucket';
}

interface GitStatusResponse {
  staged: string[];
  modified: string[];
  untracked: string[];
  deleted: string[];
  current_branch: string;
  ahead: number;
  behind: number;
}

interface GitCommitRequest {
  message: string;
  files?: string[];
}

interface GitCommitResponse {
  commit_hash: string;
  message: string;
  author: string;
  timestamp: string;
}

interface GitPushRequest {
  branch?: string;
  remote?: string;
  force?: boolean;
}

interface GitPushResponse {
  success: boolean;
  message: string;
  commits_pushed: number;
}

interface GitPullRequest {
  branch?: string;
  remote?: string;
}

interface GitPullResponse {
  success: boolean;
  message: string;
  commits_pulled: number;
  conflicts?: string[];
}

interface GitHistoryResponse {
  commits: {
    hash: string;
    message: string;
    author: string;
    timestamp: string;
    files_changed: number;
  }[];
}

interface GitBranchesResponse {
  current: string;
  branches: {
    name: string;
    is_remote: boolean;
    last_commit: string;
  }[];
}

interface GitBranchRequest {
  name: string;
  checkout?: boolean;
}

interface GitSwitchBranchRequest {
  branch: string;
}

interface GitCloneRequest {
  repo_url: string;
  branch?: string;
}

interface GitInitRequest {
  repo_url?: string;
}

interface GitDiffResponse {
  files: {
    path: string;
    status: 'added' | 'modified' | 'deleted';
    diff: string;
  }[];
}
```

## Usage Examples

### Complete Git Workflow

```typescript
// 1. Initialize or clone repository
if (hasExistingRepo) {
  await gitApi.clone(projectId, 'https://github.com/user/repo', 'main');
} else {
  await gitApi.init(projectId);
}

// 2. Check status
const status = await gitApi.getStatus(projectId);
console.log('Modified files:', status.modified);

// 3. View diff
const diff = await gitApi.getDiff(projectId);
diff.files.forEach(file => {
  console.log(`${file.status}: ${file.path}`);
});

// 4. Commit changes
const commit = await gitApi.commit(projectId, 'Add new feature');
console.log('Created commit:', commit.commit_hash);

// 5. Push to remote
const pushResult = await gitApi.push(projectId);
console.log(`Pushed ${pushResult.commits_pushed} commits`);
```

### Branch Operations

```typescript
// List branches
const branches = await gitApi.getBranches(projectId);
console.log('Current branch:', branches.current);

// Create and switch to new branch
await gitApi.createBranch(projectId, 'feature/new-feature', true);

// Or switch to existing branch
await gitApi.switchBranch(projectId, 'develop');
```

### Pull with Conflict Handling

```typescript
const pullResult = await gitApi.pull(projectId);

if (pullResult.conflicts && pullResult.conflicts.length > 0) {
  console.log('Conflicts detected in:', pullResult.conflicts);
  // Show conflict resolution UI
} else {
  console.log(`Pulled ${pullResult.commits_pulled} commits`);
}
```

### Getting Commit History

```typescript
// Get last 20 commits
const history = await gitApi.getCommitHistory(projectId, 20);

history.commits.forEach(commit => {
  console.log(`${commit.hash.slice(0, 7)} - ${commit.message}`);
  console.log(`  by ${commit.author} on ${commit.timestamp}`);
});
```

## Multi-Provider Support

The Git API supports multiple providers through the unified interface:

| Provider | Clone URL Format |
|----------|------------------|
| GitHub | `https://github.com/user/repo` |
| GitLab | `https://gitlab.com/user/repo` |
| Bitbucket | `https://bitbucket.org/user/repo` |

The backend automatically detects the provider from the URL and handles authentication accordingly.
