# Git Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/git.py` (607 lines)

The git router provides Git version control operations for projects, allowing users to commit, push, pull, and manage branches.

## Overview

Git integration enables:
- Repository initialization with remote URL
- Commit changes with messages
- Push to remote repositories
- Pull updates from remote
- Branch creation and switching
- Commit history viewing
- Status and diff viewing

Works with any Git hosting provider (GitHub, GitLab, Bitbucket, self-hosted).

## Base Path

All endpoints are mounted at `/api/projects/{project_id}/git`

## Repository Management

### Initialize Repository

```
POST /api/projects/{project_id}/git/init
```

Initializes a Git repository in the project directory.

**Request Body**:
```json
{
  "remote_url": "https://github.com/user/repo.git",
  "default_branch": "main"  // Optional, defaults to "main"
}
```

**Response**:
```json
{
  "message": "Git repository initialized successfully"
}
```

**Behind the Scenes**:
```bash
cd /projects/user-id/project-id
git init
git remote add origin https://github.com/user/repo.git
git branch -M main
```

### Clone Repository

```
POST /api/projects/{project_id}/git/clone
```

Clones an existing repository into the project (replaces existing files).

**Request Body**:
```json
{
  "repo_url": "https://github.com/user/repo.git",
  "branch": "main"  // Optional
}
```

**Response**:
```json
{
  "message": "Repository cloned successfully"
}
```

**Warning**: This replaces all existing project files!

## Git Operations

### Get Status

```
GET /api/projects/{project_id}/git/status
```

Returns the current Git status (modified files, branch, remote sync).

**Response**:
```json
{
  "branch": "main",
  "status": "clean|modified|ahead|behind",
  "changes_count": 3,
  "ahead": 2,
  "behind": 0,
  "last_commit": {
    "sha": "a3f2b1c8",
    "message": "Add user authentication",
    "author": "John Doe",
    "date": "2025-01-09T10:00:00Z"
  },
  "modified_files": [
    {
      "path": "src/app/page.tsx",
      "status": "modified"
    }
  ]
}
```

### Commit Changes

```
POST /api/projects/{project_id}/git/commit
```

Stages all changes and creates a commit.

**Request Body**:
```json
{
  "message": "Add dark mode toggle",
  "author_name": "John Doe",       // Optional, uses user's name
  "author_email": "john@example.com"  // Optional, uses user's email
}
```

**Response**:
```json
{
  "message": "Changes committed successfully",
  "commit": {
    "sha": "b4e3c2d9",
    "message": "Add dark mode toggle"
  }
}
```

**Behind the Scenes**:
```bash
git add .
git commit -m "Add dark mode toggle"
```

### Push to Remote

```
POST /api/projects/{project_id}/git/push
```

Pushes commits to the remote repository.

**Request Body**:
```json
{
  "branch": "main",      // Optional, pushes current branch if not specified
  "force": false         // Optional, dangerous!
}
```

**Response**:
```json
{
  "message": "Pushed 2 commits to remote",
  "commits_pushed": 2
}
```

**Authentication**: Uses stored Git credentials (OAuth token or personal access token).

### Pull from Remote

```
POST /api/projects/{project_id}/git/pull
```

Pulls updates from the remote repository.

**Request Body**:
```json
{
  "branch": "main"  // Optional
}
```

**Response**:
```json
{
  "message": "Pulled updates from remote",
  "files_updated": 5,
  "conflicts": []
}
```

**Merge Conflicts**: If conflicts occur, the endpoint returns conflict details:
```json
{
  "message": "Pull completed with conflicts",
  "files_updated": 3,
  "conflicts": [
    {
      "file": "src/app/page.tsx",
      "reason": "Both modified"
    }
  ]
}
```

User must resolve conflicts manually and commit.

## Branch Management

### List Branches

```
GET /api/projects/{project_id}/git/branches
```

Returns all branches (local and remote).

**Response**:
```json
{
  "current_branch": "main",
  "branches": [
    {
      "name": "main",
      "is_current": true,
      "is_remote": true,
      "last_commit": {
        "sha": "a3f2b1c8",
        "message": "Latest commit",
        "date": "2025-01-09T10:00:00Z"
      }
    },
    {
      "name": "feature/dark-mode",
      "is_current": false,
      "is_remote": false
    }
  ]
}
```

### Create Branch

```
POST /api/projects/{project_id}/git/branches
```

Creates a new branch.

**Request Body**:
```json
{
  "branch_name": "feature/user-profiles",
  "from_branch": "main"  // Optional, creates from current branch if not specified
}
```

**Response**:
```json
{
  "message": "Branch created successfully",
  "branch": {
    "name": "feature/user-profiles"
  }
}
```

### Switch Branch

```
POST /api/projects/{project_id}/git/branches/switch
```

Switches to a different branch (git checkout).

**Request Body**:
```json
{
  "branch_name": "feature/dark-mode"
}
```

**Response**:
```json
{
  "message": "Switched to branch feature/dark-mode",
  "branch": "feature/dark-mode"
}
```

**Warning**: Uncommitted changes must be stashed or committed first.

## History and Logs

### Get Commit History

```
GET /api/projects/{project_id}/git/history
```

Returns commit history for the current branch.

**Query Parameters**:
- `limit`: Max commits to return (default: 50, max: 100)
- `skip`: Pagination offset (default: 0)

**Response**:
```json
{
  "commits": [
    {
      "sha": "a3f2b1c8",
      "message": "Add user authentication",
      "author": "John Doe",
      "email": "john@example.com",
      "date": "2025-01-09T10:00:00Z",
      "files_changed": 5
    }
  ],
  "total": 127
}
```

### Get Diff

```
GET /api/projects/{project_id}/git/diff
```

Returns diff of uncommitted changes.

**Query Parameters**:
- `file_path`: Diff for specific file (optional)

**Response**:
```json
{
  "diff": "diff --git a/src/app/page.tsx b/src/app/page.tsx\nindex a3f2b1c..b4e3c2d 100644\n--- a/src/app/page.tsx\n+++ b/src/app/page.tsx\n@@ -1,5 +1,6 @@\n export default function Home() {\n+  const [darkMode, setDarkMode] = useState(false);\n   return (\n",
  "files_changed": 3
}
```

## Git Credentials

Git operations require authentication to push/pull from private repositories.

### Credential Storage

Credentials are stored in the `GitRepository` model:
```python
class GitRepository(Base):
    project_id: UUID
    user_id: UUID
    repo_url: str
    auth_method: str  # "oauth", "pat", "ssh", "none"
    credentials: dict  # Encrypted
```

### Credential Types

1. **OAuth**: GitHub/GitLab OAuth token (preferred)
   - Stored after OAuth flow
   - Automatically refreshed

2. **Personal Access Token (PAT)**: User-provided token
   - Stored encrypted
   - User manages expiration

3. **SSH Key**: SSH key pair (future)
   - Public key uploaded to Git provider
   - Private key stored encrypted

4. **None**: Public repositories only

### Using Credentials

```python
from ..services.git_manager import GitManager

git_manager = GitManager(user_id, project_id)
await git_manager.push(
    branch="main",
    auth_token=access_token  # Fetched from GitRepository
)
```

## Auto-Push Feature

Projects can enable auto-push to automatically push after every commit:

```
PATCH /api/projects/{project_id}/git/auto-push
```

**Request Body**:
```json
{
  "enabled": true
}
```

**Behavior**:
- Agent commits code → Auto-pushed to remote
- Manual file edits → Auto-pushed after save (if auto-commit enabled)
- Reduces manual push operations

**Use Cases**:
- Continuous deployment workflows
- Team collaboration (always up-to-date)
- Backup (every change preserved remotely)

## Git Providers

Tesslate supports multiple Git providers via the `git_providers` module:

### GitHub

- OAuth: Via GitHub App
- Repo URL formats:
  - `https://github.com/user/repo`
  - `https://github.com/user/repo.git`
  - `git@github.com:user/repo.git`

### GitLab

- OAuth: Via GitLab OAuth2
- Repo URL formats:
  - `https://gitlab.com/user/repo`
  - `git@gitlab.com:user/repo.git`

### Bitbucket

- OAuth: Via Bitbucket OAuth2
- Repo URL formats:
  - `https://bitbucket.org/user/repo`
  - `git@bitbucket.org:user/repo.git`

### Self-Hosted

- Any Git server (Gitea, Gogs, etc.)
- Requires PAT or SSH authentication

## Git Manager Service

The `GitManager` service (`c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_manager.py`) handles Git operations:

```python
class GitManager:
    def __init__(self, user_id: UUID, project_id: str):
        self.user_id = user_id
        self.project_id = project_id
        self.project_path = get_project_path(user_id, project_id)

    async def initialize_repository(self, remote_url: str, default_branch: str = "main"):
        # git init, add remote

    async def commit(self, message: str, author_name: str = None):
        # git add ., git commit

    async def push(self, branch: str = None, auth_token: str = None):
        # git push (with auth)

    async def pull(self, branch: str = None):
        # git pull

    async def get_status(self) -> dict:
        # git status, git diff

    async def get_history(self, limit: int = 50) -> list:
        # git log
```

## Example Workflows

### Setting Up Git for New Project

1. **Create project**:
   ```
   POST /api/projects/
   {"name": "My App"}
   ```

2. **Initialize Git**:
   ```
   POST /api/projects/{id}/git/init
   {
     "remote_url": "https://github.com/user/my-app.git",
     "default_branch": "main"
   }
   ```

3. **Make initial commit**:
   ```
   POST /api/projects/{id}/git/commit
   {"message": "Initial commit"}
   ```

4. **Push to remote**:
   ```
   POST /api/projects/{id}/git/push
   ```

5. **Project now synced with GitHub**

### Agent-Driven Development with Git

1. **User asks agent to add feature**:
   ```
   "Add user authentication"
   ```

2. **Agent writes code**:
   - Creates `src/components/Login.tsx`
   - Modifies `src/app/page.tsx`
   - Creates `src/lib/auth.ts`

3. **Agent commits changes**:
   ```python
   # Via shell_execute tool or direct API call
   await git_manager.commit("Add user authentication components")
   ```

4. **Auto-push (if enabled)**:
   ```python
   if project.git_repo.auto_push:
       await git_manager.push()
   ```

5. **Changes appear on GitHub immediately**

### Collaborative Development

1. **Developer A makes changes locally**:
   - Pushes to GitHub

2. **Developer B uses Tesslate**:
   ```
   POST /api/projects/{id}/git/pull
   ```

3. **Files updated in Tesslate**:
   - Database synced
   - Dev container reloaded

4. **Developer B's agent uses latest code**

## Security

1. **Credential Encryption**: Tokens stored encrypted in database
2. **Repository Validation**: URLs validated before cloning
3. **Access Control**: Only project owner can perform Git operations
4. **Audit Logging**: All Git operations logged
5. **Rate Limiting**: Git operations rate-limited to prevent abuse

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_manager.py` - Git operations
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/git_providers.py` - Multi-provider support
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - GitRepository model
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/credential_manager.py` - Credential encryption
