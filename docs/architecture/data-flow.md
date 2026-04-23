# Data Flow Documentation

This document provides detailed data flow patterns for OpenSail, including user request lifecycle, agent chat execution, file operations, container management, and git workflows.

**Visual Reference**: For flowchart diagrams, see:
- `diagrams/request-flow.mmd` - User request patterns (when created)
- `diagrams/agent-execution.mmd` - AI agent tool execution (when created)

## User Request Lifecycle

### Overview

All user interactions follow a consistent request/response pattern through the frontend → orchestrator → backend systems.

### General Request Flow

```
┌──────────┐
│  User    │
│ Browser  │
└────┬─────┘
     │
     │ 1. User interaction (click, type, etc.)
     ↓
┌────────────────┐
│   Frontend     │
│  (React App)   │
└────┬───────────┘
     │
     │ 2. HTTP/WebSocket request
     │    Authorization: Bearer {jwt} OR Cookie: {session}
     ↓
┌────────────────┐
│ Orchestrator   │
│ (FastAPI API)  │
└────┬───────────┘
     │
     │ 3. Validate authentication
     │    - Decode JWT token
     │    - Verify user session
     │    - Check permissions (RBAC)
     ↓
     │ 4. Query/update database
     ↓
┌────────────────┐
│  PostgreSQL    │
│   Database     │
└────┬───────────┘
     │
     │ 5. Database response
     ↓
┌────────────────┐
│ Orchestrator   │
│ (FastAPI API)  │
└────┬───────────┘
     │
     │ 6. Perform operation:
     │    - File operation → Container filesystem
     │    - Container operation → Docker/K8s API
     │    - AI chat → LiteLLM → AI provider
     │    - Deployment → Vercel/Netlify API
     ↓
     │ 7. Return JSON response
     ↓
┌────────────────┐
│   Frontend     │
│  (React App)   │
└────┬───────────┘
     │
     │ 8. Update UI with response data
     ↓
┌──────────┐
│  User    │
│ Browser  │
└──────────┘
```

### Example: Load Project Dashboard

**User Action**: Navigate to `/project/{id}`

**Frontend** (`app/src/pages/Project.tsx`):
```typescript
// 1. Component mounts, fetch project data
useEffect(() => {
  const loadProject = async () => {
    const project = await api.get(`/api/projects/${id}`);
    const files = await api.get(`/api/projects/${id}/files`);
    const containers = await api.get(`/api/projects/${id}/containers`);

    setProject(project);
    setFiles(files);
    setContainers(containers);
  };
  loadProject();
}, [id]);
```

**Orchestrator** (`orchestrator/app/routers/projects.py`):
```python
# 2. Endpoint receives request
@router.get("/{project_id}")
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user)
):
    # 3. Validate auth (current_user populated by dependency)
    # 4. Query database
    project = await db.get(Project, project_id)

    # 5. Check authorization (user owns project)
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # 6. Return project data
    return ProjectResponse.from_orm(project)
```

**Database** (`models.py`):
```python
# 4. ORM query translates to SQL:
# SELECT * FROM projects WHERE id = {project_id}
```

**Response Flow**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My App",
  "slug": "my-app-k3x8n2",
  "owner_id": "123e4567-e89b-12d3-a456-426614174000",
  "created_at": "2026-01-09T12:00:00Z",
  "status": "running",
  "containers": [...]
}
```

## Agent Chat Flow

### Overview

AI agent chat is the most complex data flow, involving LLM calls, tool execution, and real-time streaming to the frontend.

### Detailed Flow

```
┌──────────┐
│  User    │ 1. Types message in chat UI
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/chat/stream
│  (ChatUI)      │    Body: { project_id, message, chat_id }
└────┬───────────┘    EventSource (Server-Sent Events)
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/chat.py                          │
│                                                        │
│ 3. Load chat history from database                     │
│    - Get previous messages                             │
│    - Build conversation context                        │
│                                                        │
│ 4. Create agent instance                               │
│    agent = await create_agent_from_db_model(           │
│        project=project,                                │
│        agent_model=marketplace_agent,                  │
│        db=db                                           │
│    )                                                   │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: agent/factory.py                         │
│                                                        │
│ 5. Instantiate StreamAgent with:                       │
│    - System prompt (agent personality)                 │
│    - Available tools (read_file, write_file, etc.)     │
│    - LLM model (claude-3.5-sonnet, gpt-4, etc.)        │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: agent/stream_agent.py                    │
│                                                        │
│ 6. StreamAgent.run(user_message)                       │
│                                                        │
│    LOOP (until agent decides to stop):                 │
│                                                        │
│    ┌──────────────────────────────────────┐           │
│    │ 7. Call LLM (via LiteLLM)            │           │
│    │    Input: system + history + message  │           │
│    │    Output: assistant response         │           │
│    └──────┬───────────────────────────────┘           │
│           ↓                                            │
│    ┌──────────────────────────────────────┐           │
│    │ 8. LLM returns tool calls?            │           │
│    │    Example:                           │           │
│    │    {                                  │           │
│    │      "name": "write_file",            │           │
│    │      "args": {                        │           │
│    │        "path": "index.html",          │           │
│    │        "content": "<html>..."         │           │
│    │      }                                │           │
│    │    }                                  │           │
│    └──────┬───────────────────────────────┘           │
│           ↓                                            │
│    ┌──────────────────────────────────────┐           │
│    │ 9. Execute tools                      │           │
│    │    - agent/tools/read_write.py        │           │
│    │    - agent/tools/bash.py              │           │
│    │    - agent/tools/session.py           │           │
│    │    - etc.                             │           │
│    └──────┬───────────────────────────────┘           │
│           ↓                                            │
│    ┌──────────────────────────────────────┐           │
│    │ 10. Stream event to frontend          │           │
│    │     data: {                           │           │
│    │       "type": "tool_execution",       │           │
│    │       "tool": "write_file",           │           │
│    │       "status": "success",            │           │
│    │       "result": "File written"        │           │
│    │     }                                 │           │
│    └──────┬───────────────────────────────┘           │
│           ↓                                            │
│    ┌──────────────────────────────────────┐           │
│    │ 11. Call LLM with tool results        │           │
│    │     Input: previous + tool outputs    │           │
│    │     Output: next action OR final msg  │           │
│    └──────────────────────────────────────┘           │
│                                                        │
│    END LOOP                                            │
│                                                        │
│    ┌──────────────────────────────────────┐           │
│    │ 12. Stream final response             │           │
│    │     data: {                           │           │
│    │       "type": "message",              │           │
│    │       "content": "Done! I created..." │           │
│    │     }                                 │           │
│    └──────────────────────────────────────┘           │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 13. Display streaming events in real-time
│  (ChatUI)      │     - Tool executions
└────┬───────────┘     - Agent thoughts
     ↓                 - Final response
┌──────────┐
│  User    │ 14. Sees agent's work in real-time
└──────────┘
```

### Agent Tool Execution Example

**User**: "Create a React component for a todo list"

**Agent Execution**:

1. **LLM Call 1** (System prompt + user message):
   ```
   Output: Tool call - write_file("src/TodoList.tsx", "import React...")
   ```

2. **Tool Execution** (write_file):
   - Docker mode: Write to `users/{user_id}/{project_slug}/src/TodoList.tsx`
   - K8s mode: Exec into file-manager pod, write to `/app/src/TodoList.tsx`

3. **Stream Event** → Frontend:
   ```json
   {
     "type": "tool_execution",
     "tool": "write_file",
     "args": { "path": "src/TodoList.tsx" },
     "result": "File created successfully"
   }
   ```

4. **LLM Call 2** (with tool result):
   ```
   Output: "I've created a TodoList component in src/TodoList.tsx..."
   ```

5. **Stream Event** → Frontend:
   ```json
   {
     "type": "message",
     "content": "I've created a TodoList component..."
   }
   ```

**Key Files**:
- Chat router: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/chat.py`
- Stream agent: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/stream_agent.py`
- Agent factory: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/factory.py`
- Tools: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/tools/`

## File Operations Flow

### Read File

```
┌──────────┐
│  User    │ 1. Click file in file browser
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. GET /api/projects/{id}/files/{path}
│  (FileTree)    │
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/projects.py                      │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Check deployment mode                               │
│    if is_docker_mode():                                │
│        # Direct filesystem access                      │
│        file_path = f"users/{user_id}/{slug}/{path}"    │
│        content = open(file_path).read()                │
│        return {"content": content}                     │
│                                                        │
│    elif is_kubernetes_mode():                          │
│        # Exec into file-manager pod                    │
│        orchestrator = get_orchestrator()               │
│        content = await orchestrator.read_file(         │
│            project_id, path                            │
│        )                                               │
│        return {"content": content}                     │
└────┬───────────────────────────────────────────────────┘
     │
     │ (Kubernetes mode only)
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: kubernetes_orchestrator.py               │
│                                                        │
│ 5. Execute command in file-manager pod:                │
│    namespace = f"proj-{project_id}"                    │
│    pod_name = "file-manager-{project_id}"              │
│                                                        │
│    response = await k8s_client.exec_in_pod(            │
│        namespace=namespace,                            │
│        pod_name=pod_name,                              │
│        container="file-manager",                       │
│        command=["cat", f"/app/{path}"]                 │
│    )                                                   │
│                                                        │
│ 6. Return file content                                 │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 7. Display in Monaco editor
│  (Editor)      │
└────┬───────────┘
     ↓
┌──────────┐
│  User    │ 8. Edit file content
└──────────┘
```

### Write File

```
┌──────────┐
│  User    │ 1. Edit file in Monaco editor
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. PUT /api/projects/{id}/files/{path}
│  (Editor)      │    Body: { content: "..." }
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/projects.py                      │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Check deployment mode                               │
│    if is_docker_mode():                                │
│        # Direct filesystem write                       │
│        file_path = f"users/{user_id}/{slug}/{path}"    │
│        open(file_path, 'w').write(content)             │
│        return {"status": "success"}                    │
│                                                        │
│    elif is_kubernetes_mode():                          │
│        # Write via file-manager pod                    │
│        orchestrator = get_orchestrator()               │
│        await orchestrator.write_file(                  │
│            project_id, path, content                   │
│        )                                               │
│        return {"status": "success"}                    │
└────┬───────────────────────────────────────────────────┘
     │
     │ (Kubernetes mode only)
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: kubernetes_orchestrator.py               │
│                                                        │
│ 5. Execute write command in file-manager pod:          │
│    - Create temp file with content                     │
│    - Copy to pod: kubectl cp temp /app/{path}          │
│    OR                                                  │
│    - Echo content into file via exec                   │
│                                                        │
│ 6. Update project.last_activity (database)             │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 7. Update editor state (saved)
│  (Editor)      │
└────┬───────────┘
     ↓
┌──────────┐
│  User    │ 8. See "Saved" indicator
└──────────┘
```

**Key Files**:
- Projects router: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/projects.py`
- K8s orchestrator: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

## Container Operations Flow

### Start Project Containers

```
┌──────────┐
│  User    │ 1. Click "Start" button
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/projects/{id}/start
│  (ProjectUI)   │
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/projects.py                      │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Check project status                                │
│    if project.status == "running":                     │
│        return {"error": "Already running"}             │
│                                                        │
│ 5. Background task: start_project_containers()         │
│    (non-blocking, returns immediately)                 │
│                                                        │
│ 6. Return {"status": "starting"}                       │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 7. Poll GET /api/projects/{id}/status
│  (ProjectUI)   │    (every 2 seconds)
└────┬───────────┘
     │
     │ Meanwhile, background task executes:
     ↓
┌────────────────────────────────────────────────────────┐
│ Background Task: start_project_containers()            │
│                                                        │
│ 8. Get orchestrator (K8s or Docker)                    │
│    orchestrator = get_orchestrator()                   │
│                                                        │
│ 9. Call orchestrator.start_project()                   │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Kubernetes Mode: kubernetes_orchestrator.py            │
│                                                        │
│ 10. Create namespace (if not exists)                   │
│     namespace = f"proj-{project_id}"                   │
│     k8s_client.create_namespace(namespace)             │
│                                                        │
│ 11. Create PVC (shared storage)                        │
│     pvc_manifest = create_pvc_manifest(...)            │
│     k8s_client.create_pvc(namespace, pvc_manifest)     │
│                                                        │
│ 12. Hydrate from S3 (if project exists)                │
│     if s3_manager.project_exists(project_id):          │
│         # Download from S3 to PVC                      │
│         await s3_manager.hydrate_project(project_id)   │
│     else:                                              │
│         # Use template (new project)                   │
│         # Copy base files to PVC                       │
│                                                        │
│ 13. Create file-manager pod (always running)           │
│     deployment = create_file_manager_deployment(...)   │
│     k8s_client.create_deployment(namespace, deployment)│
│                                                        │
│ 14. For each container in project:                     │
│     a. Create Deployment                               │
│        deployment = create_container_deployment(...)   │
│        k8s_client.create_deployment(namespace, deploy) │
│                                                        │
│     b. Create Service                                  │
│        service = create_service_manifest(...)          │
│        k8s_client.create_service(namespace, service)   │
│                                                        │
│     c. Create Ingress                                  │
│        ingress = create_ingress_manifest(...)          │
│        k8s_client.create_ingress(namespace, ingress)   │
│                                                        │
│ 15. Create NetworkPolicy (isolation)                   │
│     policy = create_network_policy_manifest(...)       │
│     k8s_client.create_network_policy(namespace, policy)│
│                                                        │
│ 16. Update project status in database                  │
│     project.status = "running"                         │
│     await db.commit()                                  │
│                                                        │
│ 17. Return container URLs                              │
│     [{                                                 │
│       "name": "frontend",                              │
│       "url": "https://frontend.proj-{id}.your-domain.com" │
│     }]                                                 │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 18. Status poll detects "running"
│  (ProjectUI)   │     Display container URLs
└────┬───────────┘     Enable live preview
     ↓
┌──────────┐
│  User    │ 19. Access project at URL
└──────────┘     See live preview in iframe
```

### Stop Project Containers

```
┌──────────┐
│  User    │ 1. Click "Stop" button OR navigate away
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/projects/{id}/stop
│  (ProjectUI)   │
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/projects.py                      │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Background task: stop_project_containers()          │
│    (non-blocking)                                      │
│                                                        │
│ 5. Return {"status": "stopping"}                       │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Background Task: stop_project_containers()             │
│                                                        │
│ 6. Get orchestrator                                    │
│    orchestrator = get_orchestrator()                   │
│                                                        │
│ 7. Call orchestrator.stop_project()                    │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Kubernetes Mode: kubernetes_orchestrator.py            │
│                                                        │
│ 8. Dehydrate to S3 (save project state)                │
│    namespace = f"proj-{project_id}"                    │
│    await s3_manager.dehydrate_project(                 │
│        project_id, namespace                           │
│    )                                                   │
│                                                        │
│ 9. Delete namespace (cascades to all resources)        │
│    k8s_client.delete_namespace(namespace)              │
│    # Deletes:                                          │
│    # - Deployments (file-manager, dev containers)      │
│    # - Services                                        │
│    # - Ingress                                         │
│    # - PVC (ephemeral storage)                         │
│    # - NetworkPolicy                                   │
│                                                        │
│ 10. Update project status in database                  │
│     project.status = "stopped"                         │
│     await db.commit()                                  │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 11. Status poll detects "stopped"
│  (ProjectUI)   │     Disable live preview
└────┬───────────┘     Show "Start" button
     ↓
┌──────────┐
│  User    │ 12. Project stopped, files saved to S3
└──────────┘
```

**Key Files**:
- Projects router: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/projects.py`
- K8s orchestrator: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`
- K8s helpers: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py`
- S3 manager: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/s3_manager.py`

## Git Operations Flow

### Clone Repository

```
┌──────────┐
│  User    │ 1. Click "Import from GitHub"
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/git/clone
│  (ImportModal) │    Body: { repo_url, project_id }
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/git.py                           │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Background task: clone_repository()                 │
│    (non-blocking)                                      │
│                                                        │
│ 5. Return {"status": "cloning"}                        │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Background Task: clone_repository()                    │
│                                                        │
│ 6. Check deployment mode                               │
│                                                        │
│    if is_kubernetes_mode():                            │
│        # Generate git clone script                     │
│        script = generate_git_clone_script(repo_url)    │
│                                                        │
│        # Execute in file-manager pod                   │
│        orchestrator.exec_in_pod(                       │
│            command=["bash", "-c", script]              │
│        )                                               │
│                                                        │
│    elif is_docker_mode():                              │
│        # Clone directly to filesystem                  │
│        import subprocess                               │
│        subprocess.run([                                │
│            "git", "clone", repo_url,                   │
│            f"users/{user_id}/{project_slug}"           │
│        ])                                              │
│                                                        │
│ 7. Update project.last_activity                        │
│                                                        │
│ 8. Return {"status": "cloned"}                         │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 9. Poll detects "cloned"
│  (ProjectUI)   │    Refresh file tree
└────┬───────────┘
     ↓
┌──────────┐
│  User    │ 10. See cloned files in project
└──────────┘
```

### Commit & Push

```
┌──────────┐
│  User    │ 1. Agent makes changes, user clicks "Commit"
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/git/commit
│  (GitPanel)    │    Body: { message, project_id }
└────┬───────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/git.py                           │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Check deployment mode                               │
│                                                        │
│    if is_kubernetes_mode():                            │
│        # Execute git commands in file-manager pod      │
│        orchestrator.exec_in_pod([                      │
│            "git", "config", "user.name", user.name     │
│        ])                                              │
│        orchestrator.exec_in_pod([                      │
│            "git", "config", "user.email", user.email   │
│        ])                                              │
│        orchestrator.exec_in_pod([                      │
│            "git", "add", "."                           │
│        ])                                              │
│        orchestrator.exec_in_pod([                      │
│            "git", "commit", "-m", message              │
│        ])                                              │
│        orchestrator.exec_in_pod([                      │
│            "git", "push"                               │
│        ])                                              │
│                                                        │
│    elif is_docker_mode():                              │
│        # Execute git commands on filesystem            │
│        os.chdir(f"users/{user_id}/{project_slug}")     │
│        subprocess.run(["git", "add", "."])             │
│        subprocess.run(["git", "commit", "-m", message])│
│        subprocess.run(["git", "push"])                 │
│                                                        │
│ 5. Return {"status": "pushed", "commit_hash": "..."}   │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 6. Display success message
│  (GitPanel)    │    Show commit hash
└────┬───────────┘
     ↓
┌──────────┐
│  User    │ 7. Changes pushed to GitHub
└──────────┘
```

**Key Files**:
- Git router: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/git.py`
- Git helpers: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py` (generate_git_clone_script)

## Deployment Flow (External Providers)

### Deploy to Vercel

```
┌──────────┐
│  User    │ 1. Click "Deploy to Vercel"
└────┬─────┘
     ↓
┌────────────────┐
│   Frontend     │ 2. POST /api/deployments
│  (DeployModal) │    Body: {
└────┬───────────┘      provider: "vercel",
     │                  project_id,
     │                  config: { framework: "react" }
     ↓                }
┌────────────────────────────────────────────────────────┐
│ Orchestrator: routers/deployments.py                   │
│                                                        │
│ 3. Validate auth, get project                          │
│                                                        │
│ 4. Get Vercel OAuth token from DeploymentCredential    │
│    credential = await db.get(DeploymentCredential,     │
│        user_id=user.id, provider="vercel"              │
│    )                                                   │
│    access_token = decrypt(credential.access_token)     │
│                                                        │
│ 5. Background task: deploy_to_vercel()                 │
│    (non-blocking)                                      │
│                                                        │
│ 6. Return {"status": "deploying", "deployment_id"}     │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────────────────────────────────────────────┐
│ Background Task: deploy_to_vercel()                    │
│                                                        │
│ 7. Build project locally                               │
│    - npm install                                       │
│    - npm run build                                     │
│                                                        │
│ 8. Push to git (if not already)                        │
│    - Create/update GitHub repo                         │
│    - git push                                          │
│                                                        │
│ 9. Create Vercel deployment via API                    │
│    POST https://api.vercel.com/v13/deployments         │
│    Headers: { Authorization: Bearer {access_token} }   │
│    Body: {                                             │
│      name: project.slug,                               │
│      gitSource: { repo: "...", ref: "main" }           │
│    }                                                   │
│                                                        │
│ 10. Poll Vercel API for deployment status              │
│     GET https://api.vercel.com/v13/deployments/{id}    │
│     Wait until state = "READY"                         │
│                                                        │
│ 11. Save deployment record to database                 │
│     deployment = Deployment(                           │
│         project_id=project.id,                         │
│         provider="vercel",                             │
│         url="https://{project}.vercel.app",            │
│         status="deployed"                              │
│     )                                                  │
│     await db.commit()                                  │
│                                                        │
│ 12. Send webhook to frontend (WebSocket)               │
│     { type: "deployment_complete", url: "..." }        │
└────┬───────────────────────────────────────────────────┘
     ↓
┌────────────────┐
│   Frontend     │ 13. Receive webhook, display success
│  (DeployModal) │     Show live URL
└────┬───────────┘
     ↓
┌──────────┐
│  User    │ 14. Click URL to visit deployed app
└──────────┘
```

**Key Files**:
- Deployments router: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployments.py`
- Deployment OAuth: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployment_oauth.py`
- Deployment credentials: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployment_credentials.py`

## WebSocket Streaming Patterns

### Server-Sent Events (Agent Chat)

**Frontend** (EventSource):
```typescript
const eventSource = new EventSource('/api/chat/stream', {
  body: JSON.stringify({ message, project_id }),
  method: 'POST'
});

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case 'tool_execution':
      displayToolExecution(data.tool, data.args);
      break;
    case 'message':
      displayAgentMessage(data.content);
      break;
    case 'error':
      displayError(data.error);
      break;
  }
};
```

**Backend** (FastAPI StreamingResponse):
```python
async def stream_agent_response(project_id, message):
    async for event in agent.run(message):
        yield f"data: {json.dumps(event)}\n\n"

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        stream_agent_response(request.project_id, request.message),
        media_type="text/event-stream"
    )
```

## Performance Optimizations

### Non-Blocking Operations

**Pattern**: Return immediately, execute in background

**Example** (Project creation):
```python
# ❌ BAD - Blocks for 30+ seconds
@router.post("/")
async def create_project(data: ProjectCreate):
    project = await db_create_project(data)
    await setup_containers(project)  # BLOCKS HERE
    return project

# ✅ GOOD - Returns immediately
@router.post("/")
async def create_project(data: ProjectCreate):
    project = await db_create_project(data)
    background_tasks.add_task(setup_containers, project)
    return project  # Frontend polls /status
```

### Database Query Optimization

**Pattern**: Minimize joins, use async queries

**Example** (Load project with containers):
```python
# ❌ BAD - Multiple sequential queries
project = await db.get(Project, project_id)
containers = await db.execute(
    select(Container).where(Container.project_id == project_id)
)
connections = await db.execute(
    select(ContainerConnection).where(...)
)

# ✅ GOOD - Single query with joined loading
project = await db.execute(
    select(Project)
    .options(
        selectinload(Project.containers),
        selectinload(Project.containers).selectinload(Container.connections)
    )
    .where(Project.id == project_id)
)
```

### Frontend Polling vs. WebSockets

**Polling** (Simple, stateless):
```typescript
// Use for: Status checks, periodic updates
const pollStatus = async () => {
  const status = await api.get(`/api/projects/${id}/status`);
  if (status.state !== 'running') {
    setTimeout(pollStatus, 2000);  // Poll every 2s
  }
};
```

**WebSockets** (Real-time, bidirectional):
```typescript
// Use for: Chat streaming, live logs
const ws = new WebSocket(`wss://api/logs/${containerId}`);
ws.onmessage = (event) => {
  appendLog(event.data);
};
```

## Related Documentation

- **[system-overview.md](./system-overview.md)** - High-level architecture
- **[deployment-modes.md](./deployment-modes.md)** - Docker vs. Kubernetes
- **[CLAUDE.md](./CLAUDE.md)** - AI agent context for architecture
- **[../orchestrator/CLAUDE.md](../orchestrator/CLAUDE.md)** - Backend implementation
- **[../app/CLAUDE.md](../app/CLAUDE.md)** - Frontend implementation
