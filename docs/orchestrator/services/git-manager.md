# Git Manager - Version Control in Containers

**File**: `orchestrator/app/services/git_manager.py` (684 lines)

Manages Git operations inside user project containers. Executes Git commands via orchestrator's `execute_command()` method, supporting both Docker and Kubernetes deployments.

## Overview

The Git Manager provides a high-level API for Git operations that work across deployment modes. All Git commands run **inside the user's container**, not on the host.

## Architecture

```
Git Manager Flow
┌──────────────────────────────────────────────┐
│ GitManager(user_id, project_id)             │
│   ↓                                          │
│ _execute_git_command(["status"])            │
│   ↓                                          │
│ orchestrator.execute_command()               │
│   ├─ Docker: docker exec {container} git    │
│   └─ K8s: kubectl exec {pod} -- git         │
│   ↓                                          │
│ Return: stdout + stderr                      │
└──────────────────────────────────────────────┘
```

## Key Operations

### Initialize Repository

```python
git_manager = GitManager(user_id=user.id, project_id=project.id)

await git_manager.initialize_repository(
    remote_url="https://github.com/user/repo.git",
    default_branch="main"
)
# Runs: git init -b main
#       git config user.name "Tesslate User"
#       git config user.email "user@tesslate.com"
#       git remote add origin <url>
```

### Clone Repository

```python
await git_manager.clone_repository(
    repo_url="https://github.com/user/repo.git",
    branch="develop",  # Optional
    auth_token="ghp_..."  # Injected into URL for private repos
)
# Clones to /tmp/git-clone, then moves to /app
```

### Get Status

```python
status = await git_manager.get_status()
# Returns: {
#   'branch': 'main',
#   'status': 'modified',  # or 'clean', 'ahead', 'behind', 'diverged'
#   'changes': [
#       {'path': 'src/App.tsx', 'type': 'modified', 'staged': False},
#       {'path': 'README.md', 'type': 'added', 'staged': True}
#   ],
#   'changes_count': 2,
#   'ahead': 0,
#   'behind': 0,
#   'last_commit': {
#       'sha': 'abc123...',
#       'author_name': 'John Doe',
#       'message': 'Add feature',
#       'timestamp': 1704067200
#   }
# }
```

### Commit Changes

```python
commit_sha = await git_manager.commit(
    message="Add new feature",
    files=["src/App.tsx", "README.md"]  # Or None for all changes
)
# Runs: git add <files> (or git add .)
#       git commit -m "message"
#       git rev-parse HEAD
# Returns: "abc123..."
```

### Push to Remote

```python
await git_manager.push(
    branch="main",  # Or None for current
    remote="origin",
    force=False
)
# Runs: git push origin main
```

### Pull from Remote

```python
result = await git_manager.pull(
    branch="main",
    remote="origin"
)
# Returns: {
#   'success': True,
#   'conflicts': [],  # Or ['src/App.tsx'] if conflicts
#   'message': 'Pull completed successfully'
# }
```

## Additional Operations

### Commit History

```python
commits = await git_manager.get_commit_history(limit=50)
# Returns list of commit dicts with sha, author, message, timestamp
```

### Branches

```python
branches = await git_manager.list_branches()
# Returns: [{'name': 'main', 'current': True, 'remote': False}, ...]

await git_manager.create_branch("feature-x", checkout=True)
await git_manager.switch_branch("develop")
```

### Diff

```python
diff = await git_manager.get_diff(
    file_path="src/App.tsx",  # Or None for all
    staged=False  # Or True for staged changes
)
# Returns: unified diff string
```

## Implementation Details

### Command Execution

All Git operations use `_execute_git_command()`:

```python
async def _execute_git_command(
    self,
    git_args: List[str],
    timeout: int = 120
) -> str:
    """Execute Git command in container."""

    # Both Docker and K8s mount to /app
    project_path = "/app"

    command = [
        "/bin/sh", "-c",
        f"cd {project_path} && git {' '.join(shlex.quote(arg) for arg in git_args)}"
    ]

    orchestrator = get_orchestrator()
    output = await orchestrator.execute_command(
        user_id=self.user_id,
        project_id=self.project_id,
        container_name=None,  # Use default
        command=command,
        timeout=timeout
    )

    return output.strip()
```

### Authentication

For private repos, inject token into URL:

```python
# Convert SSH to HTTPS
if repo_url.startswith("git@github.com:"):
    repo_url = repo_url.replace("git@github.com:", "https://github.com/")

# Inject token
if auth_token and "github.com" in repo_url:
    repo_url = repo_url.replace(
        "https://github.com/",
        f"https://{auth_token}@github.com/"
    )
```

## Git Providers Integration

The `git_providers/` directory provides OAuth and API integration:

- **OAuth**: Get access tokens (GitHub, GitLab, Bitbucket)
- **API**: Create repos, webhooks, deploy keys
- **Credentials**: Store encrypted tokens in database

```python
from services.git_providers import get_git_provider_manager

manager = get_git_provider_manager()

# Get provider (GitHub, GitLab, Bitbucket)
provider = manager.get_provider("github", access_token="ghp_...")

# Create repository
repo = await provider.create_repository(
    name="my-project",
    private=True,
    description="Created from Tesslate"
)

# Add deploy key
await provider.add_deploy_key(
    repo_name="my-project",
    title="Tesslate Deploy Key",
    key=public_key,
    read_only=False
)
```

## Usage Examples

### Example 1: AI Agent Commits

```python
# agent/tools/git.py
from services.git_manager import GitManager

async def agent_commit_changes(user_id: UUID, project_id: str, message: str):
    """AI agent commits changes."""
    git = GitManager(user_id=user_id, project_id=project_id)

    # Check for changes
    status = await git.get_status()
    if status['changes_count'] == 0:
        return "No changes to commit"

    # Commit all changes
    commit_sha = await git.commit(message=message)

    return f"Created commit {commit_sha[:8]}: {message}"
```

### Example 2: Import GitHub Repo

```python
from services.git_manager import GitManager

async def import_github_repo(user_id: UUID, project_id: str, repo_url: str, token: str):
    """Import GitHub repository into project."""
    git = GitManager(user_id=user_id, project_id=project_id)

    # Clone repository with authentication
    await git.clone_repository(
        repo_url=repo_url,
        branch=None,  # Default branch
        auth_token=token
    )

    # Verify
    status = await git.get_status()
    return {"branch": status['branch'], "commit": status['last_commit']['sha']}
```

### Example 3: Sync with Remote

```python
async def sync_project(user_id: UUID, project_id: str):
    """Pull latest changes from remote."""
    git = GitManager(user_id=user_id, project_id=project_id)

    # Pull changes
    result = await git.pull()

    if result['success']:
        return "Project synced successfully"
    elif result['conflicts']:
        return f"Merge conflicts in: {', '.join(result['conflicts'])}"
    else:
        return f"Sync failed: {result['message']}"
```

## Error Handling

Git Manager raises `RuntimeError` with detailed context:

```python
try:
    await git_manager.push()
except RuntimeError as e:
    # Example: "Git command failed: fatal: Authentication failed"
    logger.error(f"Push failed: {e}")
    # Show user-friendly error message
```

## Configuration

Git config is set per-repository during initialization:

```python
# Default config (can be customized per user)
await _execute_git_command(["config", "user.name", "Tesslate User"])
await _execute_git_command(["config", "user.email", "user@tesslate.com"])
```

## Troubleshooting

**Problem**: "fatal: not a git repository"
- Repository not initialized
- Call `initialize_repository()` first

**Problem**: "Authentication failed" on clone/push
- Check auth_token is valid
- Verify token has required scopes (repo access)

**Problem**: Command timeout
- Large repos may need longer timeout
- Pass `timeout=300` for 5-minute limit

## Related Documentation

- [git_providers/](./git-providers.md) - OAuth and API integration
- [orchestration.md](./orchestration.md) - Command execution details
- [../routers/git.md](../routers/git.md) - Git API endpoints
