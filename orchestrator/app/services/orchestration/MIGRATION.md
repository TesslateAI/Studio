# Orchestration Module Migration Guide

This document explains how to migrate from the old deployment mode checks to the new unified orchestration system.

## Overview

The new orchestration system provides:
1. **Type-safe deployment mode enum** instead of string comparisons
2. **Unified orchestrator interface** for feature parity
3. **Factory pattern** for clean instantiation
4. **Centralized file organization** under `services/orchestration/`

## File Structure

```
orchestrator/app/services/orchestration/
├── __init__.py           # Public exports
├── deployment_mode.py    # DeploymentMode enum
├── base.py               # BaseOrchestrator abstract class
├── factory.py            # OrchestratorFactory + get_orchestrator()
├── docker.py             # DockerOrchestrator implementation
├── kubernetes.py         # KubernetesOrchestrator implementation
├── kubernetes/           # Kubernetes-specific modules
│   ├── __init__.py       # Exports for K8s submodule
│   ├── client.py         # KubernetesClient - low-level K8s API
│   ├── helpers.py        # S3 storage helpers, manifest generators
│   └── manager.py        # KubernetesContainerManager - lifecycle
└── MIGRATION.md          # This file
```

## Migration Patterns

### Pattern 1: Simple Deployment Mode Checks

**Before:**
```python
from ..config import get_settings
settings = get_settings()

if settings.deployment_mode == "kubernetes":
    # K8s code
else:
    # Docker code
```

**After (Option A - Convenience functions):**
```python
from ..services.orchestration import is_kubernetes_mode, is_docker_mode

if is_kubernetes_mode():
    # K8s code
else:
    # Docker code
```

**After (Option B - Settings properties):**
```python
from ..config import get_settings
settings = get_settings()

if settings.is_kubernetes_mode:
    # K8s code
else:
    # Docker code
```

### Pattern 2: Orchestrator Instantiation

**Before:**
```python
if settings.deployment_mode == "kubernetes":
    from ..services.kubernetes_orchestrator import get_kubernetes_orchestrator
    orchestrator = get_kubernetes_orchestrator()
    result = await orchestrator.start_project(...)
else:
    from ..services.docker_compose_orchestrator import get_compose_orchestrator
    orchestrator = get_compose_orchestrator()
    result = await orchestrator.start_project(...)
```

**After:**
```python
from ..services.orchestration import get_orchestrator

orchestrator = get_orchestrator()  # Automatically selects based on config
result = await orchestrator.start_project(...)
```

### Pattern 3: File Operations

**Before (scattered across routers):**
```python
if settings.deployment_mode == "kubernetes":
    from ..k8s_client import get_k8s_manager
    k8s_manager = get_k8s_manager()
    content = await k8s_manager.read_file_from_pod(user_id, project_id, file_path)
else:
    # Direct filesystem access
    with open(f"/projects/{project_id}/{file_path}", 'r') as f:
        content = f.read()
```

**After:**
```python
from ..services.orchestration import get_orchestrator

orchestrator = get_orchestrator()
content = await orchestrator.read_file(user_id, project_id, container_name, file_path)
```

### Pattern 4: Shell Command Execution

**Before:**
```python
if settings.deployment_mode == "kubernetes":
    output = await k8s_manager.execute_command_in_pod(
        user_id, project_id, command, timeout, container_name
    )
else:
    # Docker exec
    process = await asyncio.create_subprocess_exec(
        'docker', 'exec', container_name, *command, ...
    )
```

**After:**
```python
from ..services.orchestration import get_orchestrator

orchestrator = get_orchestrator()
output = await orchestrator.execute_command(
    user_id, project_id, container_name, command, timeout
)
```

## Common Imports

Add these to your files as needed:

```python
# Full orchestration module
from ..services.orchestration import (
    get_orchestrator,
    is_docker_mode,
    is_kubernetes_mode,
    get_deployment_mode,
    DeploymentMode,
)

# Just the orchestrator (most common)
from ..services.orchestration import get_orchestrator

# Just the mode checks
from ..services.orchestration import is_docker_mode, is_kubernetes_mode
```

## BaseOrchestrator Interface

All orchestrators implement these methods:

### Project Lifecycle
- `start_project(project, containers, connections, user_id, db)` -> Dict
- `stop_project(project_slug, project_id, user_id)` -> None
- `restart_project(project, containers, connections, user_id, db)` -> Dict
- `get_project_status(project_slug, project_id)` -> Dict

### Container Management
- `start_container(project, container, all_containers, connections, user_id, db)` -> Dict
- `stop_container(project_slug, project_id, container_name, user_id)` -> None
- `get_container_status(project_slug, project_id, container_name, user_id)` -> Dict

### File Operations
- `read_file(user_id, project_id, container_name, file_path)` -> Optional[str]
- `write_file(user_id, project_id, container_name, file_path, content)` -> bool
- `delete_file(user_id, project_id, container_name, file_path)` -> bool
- `list_files(user_id, project_id, container_name, directory)` -> List[Dict]

### Shell Operations
- `execute_command(user_id, project_id, container_name, command, timeout, working_dir)` -> str
- `is_container_ready(user_id, project_id, container_name)` -> Dict

### Activity & Cleanup
- `track_activity(user_id, project_id, container_name)` -> None
- `cleanup_idle_environments(idle_timeout_minutes)` -> List[str]

## Backward Compatibility

**IMPORTANT: The old files have been removed.** All code has been migrated to use the new unified orchestration system.

### Removed Files (December 2025)
- `deprecated_k8s_client.py` - Replaced by `orchestration/kubernetes/client.py`
- `deprecated_k8s_client_helpers.py` - Replaced by `orchestration/kubernetes/helpers.py`
- `deprecated_k8s_container_manager.py` - Replaced by `orchestration/kubernetes/manager.py`
- `services/deprecated_docker_compose_orchestrator.py` - Replaced by `orchestration/docker.py`
- `services/deprecated_kubernetes_orchestrator.py` - Replaced by `orchestration/kubernetes.py`

Use the new unified interface through `get_orchestrator()` for all operations.

## Testing

The factory clears its cache in tests:

```python
from app.services.orchestration import OrchestratorFactory

def test_something():
    OrchestratorFactory.clear_cache()
    # Your test code
```

## Migration Progress

### ✅ Migration Complete (December 2025)

All files have been migrated to use the new unified orchestration system.

### Migrated Files

| File | Changes | Notes |
|------|---------|-------|
| `main.py` | 1 | Startup initialization |
| `agent/prompts.py` | 1 | Agent context building |
| `agent/stream_agent.py` | 2 | Stream agent file/command operations |
| `agent/tools/file_ops/read_write.py` | 2 | File read/write with fallbacks |
| `agent/tools/file_ops/edit.py` | 4 | File editing operations |
| `services/container_initializer.py` | 1 | Container initialization |
| `services/git_manager.py` | 2 | Git command execution |
| `services/shell_session_manager.py` | 4 | Shell session management |
| `services/pty_broker.py` | 1 | PTY management |
| `services/deployment/builder.py` | 1 | Build operations |
| `routers/chat.py` | 2 | Chat context and file ops |
| `routers/agent.py` | 1 | Agent command execution |
| `routers/projects.py` | ~15 | Project lifecycle, container management |

### Verification

Run this command to verify no old patterns remain:
```bash
grep -r 'from.*docker_compose_orchestrator import\|from.*kubernetes_orchestrator import' orchestrator/app --include="*.py" | grep -v "__pycache__" | grep -v "orchestration/"
```

Expected output: Only `services/__init__.py` (backward compatibility) should match.

### Notes

1. **Complete Migration**: All deprecated files have been removed. The new orchestration module
   is the single source of truth for all container/orchestration operations.

2. **Unified Interface**: `services/orchestration/docker.py` and `kubernetes.py` now contain
   the complete implementations, not wrappers around deprecated code.

3. **Deployment Provider Modes**: Some `deployment_mode` checks like `"external"` or `"source"`
   are for *deployment provider modes* (Vercel/Netlify), NOT orchestrator deployment modes.
   These are unrelated to this migration.

## Additional Methods

Both orchestrators also support:
- `glob_files(user_id, project_id, container_name, pattern, directory)` -> List[Dict]
- `grep_files(user_id, project_id, container_name, pattern, directory, file_pattern, case_sensitive, max_results)` -> List[Dict]
- `scale_deployment(user_id, project_id, container_name, replicas)` -> None (K8s only)
