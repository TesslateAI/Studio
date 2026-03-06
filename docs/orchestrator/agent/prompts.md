# System Prompts

**File**: `orchestrator/app/agent/prompts.py`

System prompts are the core instructions that teach language models how to behave as agents. Tesslate uses a sophisticated prompt system with marker substitution, mode-specific instructions, and context injection.

## Overview

The prompt system consists of:

1. **Base System Prompt**: Agent's core instructions (stored in database)
2. **Marker Substitution**: Dynamic placeholders like `{mode}`, `{project_name}`
3. **Mode Instructions**: Behavior for Allow/Ask/Plan modes
4. **Context Wrapper**: Environment info, file listings, git status

## Marker Substitution

### substitute_markers Function

**Signature**:
```python
def substitute_markers(
    system_prompt: str,
    context: Dict[str, Any],
    tool_names: Optional[list] = None
) -> str
```

Replaces `{marker}` placeholders with runtime values.

### Available Markers

| Marker | Replacement | Example |
|--------|-------------|---------|
| `{mode}` | Current edit mode | `"allow"`, `"ask"`, `"plan"` |
| `{mode_instructions}` | Full mode instructions | See below |
| `{project_name}` | Project display name | `"MyApp"` |
| `{project_description}` | Project description | `"React application"` |
| `{timestamp}` | Current ISO timestamp | `"2024-01-15T10:30:00"` |
| `{user_name}` | User's name | `"John Doe"` |
| `{project_path}` | Container project path | `"/app"` |
| `{git_branch}` | Current git branch | `"feature/auth"` |
| `{tool_list}` | Comma-separated tools | `"read_file, write_file, bash_exec"` |

### Example Usage

```python
# System prompt with markers
system_prompt = """
You are working in {mode} mode. {mode_instructions}

Project: {project_name}
Path: {project_path}
Branch: {git_branch}

Available tools: {tool_list}
"""

# Substitute at runtime
context = {
    "edit_mode": "ask",
    "project_context": {
        "project_name": "E-commerce Site",
        "git_context": {"branch": "main"}
    }
}
tool_names = ["read_file", "write_file", "bash_exec"]

result = substitute_markers(system_prompt, context, tool_names)
```

Result:
```
You are working in ask mode. [ASK BEFORE EDIT MODE]
You can propose file modifications and shell commands, but they require user approval.
The user will be prompted to approve each dangerous operation before execution.
Read operations proceed without approval.

Project: E-commerce Site
Path: /app
Branch: main

Available tools: read_file, write_file, bash_exec
```

## Mode-Specific Instructions

### get_mode_instructions Function

**Signature**:
```python
def get_mode_instructions(mode: str) -> str
```

Returns instructions for each edit mode.

### Allow Mode (edit_mode='allow')

```
[FULL EDIT MODE]
You have full access to all tools including file modifications and shell commands.
Execute changes directly as needed to accomplish the user's goals.
```

**Behavior**:
- All tools execute immediately
- No user approval required
- Full autonomy

### Ask Mode (edit_mode='ask')

```
[ASK BEFORE EDIT MODE]
You can propose file modifications and shell commands, but they require user approval.
The user will be prompted to approve each dangerous operation before execution.
Read operations proceed without approval.
```

**Behavior**:
- Dangerous tools (write_file, bash_exec, etc.) require approval
- Read operations (read_file, get_project_info) execute immediately
- User can "Allow Once", "Allow All", or "Stop"

### Plan Mode (edit_mode='plan')

```
[PLAN MODE ACTIVE]
You are in read-only planning mode. You MUST NOT execute any file modifications or shell commands.
Instead, create a detailed markdown plan explaining what changes you would make.
All read operations (read_file, get_project_info, etc.) are allowed and encouraged for gathering context.
Format your plan clearly with headings, bullet points, and code examples where helpful.
```

**Behavior**:
- All dangerous tools blocked
- Read operations allowed
- Agent creates markdown plan instead of executing

## Context Wrapper

### get_user_message_wrapper Function

**Signature**:
```python
async def get_user_message_wrapper(
    user_request: str,
    project_context: Optional[dict] = None,
    include_environment: bool = True,
    include_file_listing: bool = True
) -> str
```

Wraps user request with helpful context.

### Context Structure

```
[CONTEXT]

=== ENVIRONMENT CONTEXT ===
Time: 2024-01-15 10:30:00 UTC
Deployment Mode: kubernetes
Pod: proj-abc123-frontend
Namespace: tesslate-user-environments
Current Working Directory: /app
Project Path: users/user-id/project-id/

=== FILE LISTING (CWD: /app) ===
total 48
drwxr-xr-x 5 root root 4096 Jan 15 10:00 .
drwxr-xr-x 3 root root 4096 Jan 15 09:00 ..
-rw-r--r-- 1 root root  123 Jan 15 10:00 package.json
drwxr-xr-x 2 root root 4096 Jan 15 10:00 src
-rw-r--r-- 1 root root  456 Jan 15 10:00 vite.config.js

=== TESSLATE.md ===
[Project-specific agent instructions from TESSLATE.md file]

=== Git Repository ===
Branch: main
Status: Clean
Last Commit: feat: Add user authentication (2 hours ago)

=== User Request ===
Add a dark mode toggle to the settings page
```

### Environment Context

**Function**: `get_environment_context(user_id, project_id)`

Provides runtime environment information:

```python
async def get_environment_context(user_id: UUID, project_id: str) -> str:
    context_parts = ["\n=== ENVIRONMENT CONTEXT ===\n"]

    # Time
    now = datetime.now()
    context_parts.append(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Deployment mode
    deployment_mode = get_deployment_mode()
    context_parts.append(f"Deployment Mode: {deployment_mode.value}")

    # Container/Pod info
    if is_kubernetes_mode():
        pod_name = get_container_name(user_id, project_id, mode="kubernetes")
        namespace = "tesslate-user-environments"
        context_parts.append(f"Pod: {pod_name}")
        context_parts.append(f"Namespace: {namespace}")
    else:
        container_name = get_container_name(user_id, project_id, mode="docker")
        context_parts.append(f"Container: {container_name}")

    context_parts.append(f"Current Working Directory: /app")

    return "\n".join(context_parts)
```

### File Listing Context

**Function**: `get_file_listing_context(user_id, project_id, max_lines=50)`

Shows current directory contents:

```python
async def get_file_listing_context(...) -> Optional[str]:
    if is_kubernetes_mode():
        # Execute ls in pod
        cmd = f"kubectl exec -n {namespace} {pod_name} -- ls -lah /app"
    else:
        # List local directory
        cmd = f"ls -lah {project_dir}"

    # Run command and return output
    output = await run_command(cmd)
    return "\n=== FILE LISTING (CWD: /app) ===\n\n" + output
```

Helps agents:
- Understand file structure
- See available files before reading
- Know what exists before creating

## Complete System Prompt Example

### Agent Definition (Database)

```sql
INSERT INTO marketplace_agents (
    name,
    slug,
    agent_type,
    system_prompt
) VALUES (
    'React Developer',
    'react-dev',
    'IterativeAgent',
    'You are an expert React developer specializing in TypeScript and modern best practices.

Your capabilities:
- Create functional components with proper TypeScript types
- Implement hooks (useState, useEffect, useContext)
- Follow accessibility standards (ARIA, semantic HTML)
- Write clean, maintainable code

{mode_instructions}

Current project: {project_name}
Available tools: {tool_list}

Always read files before modifying them to understand the current implementation.'
);
```

### Runtime Processing

When agent runs, the system:

1. **Loads base prompt** from database
2. **Substitutes markers** using current context
3. **Appends tool information** (for IterativeAgent/ReActAgent)
4. **Wraps user message** with environment context

Final prompt sent to LLM:

```
You are an expert React developer specializing in TypeScript and modern best practices.

Your capabilities:
- Create functional components with proper TypeScript types
- Implement hooks (useState, useEffect, useContext)
- Follow accessibility standards (ARIA, semantic HTML)
- Write clean, maintainable code

[ASK BEFORE EDIT MODE]
You can propose file modifications and shell commands, but they require user approval.
The user will be prompted to approve each dangerous operation before execution.
Read operations proceed without approval.

Current project: E-commerce Dashboard
Available tools: read_file, write_file, patch_file, bash_exec

Always read files before modifying them to understand the current implementation.

=== TOOL USAGE AND FORMATTING ===

Your actions are communicated through pure JSON format. You must include a THOUGHT section before every tool call to explain your reasoning.

CRITICAL: Tool calls must be VALID JSON objects or arrays.

JSON Formatting Rules (MUST FOLLOW):
1. ALL quotes inside string values MUST be escaped with backslash: \"
2. Newlines must be escaped as \n, tabs as \t, backslashes as \\
3. Use only double quotes for JSON strings, never single quotes
4. Ensure proper JSON syntax: commas between properties, matching braces

Available Tools:

read_file: Read the contents of a file from the project directory.
  Parameters:
  - file_path (string, required): Path to the file relative to project root

write_file: Write complete file content (creates if doesn't exist).
  Parameters:
  - file_path (string, required): Path to the file relative to project root
  - content (string, required): Complete content to write

[... more tools ...]

---

[CONTEXT]

=== ENVIRONMENT CONTEXT ===
Time: 2024-01-15 10:30:00 UTC
Deployment Mode: kubernetes
Current Working Directory: /app

=== FILE LISTING (CWD: /app) ===
[file listing output]

=== User Request ===
Add a dark mode toggle to the settings page
```

## Best Practices

### 1. Keep Base Prompts Mode-Agnostic

```python
# ❌ Bad: Hard-coding mode behavior
system_prompt = "You have full edit access. Modify files directly."

# ✅ Good: Using mode markers
system_prompt = "{mode_instructions}\n\nYour task: ..."
```

### 2. Use Markers for Dynamic Content

```python
# ❌ Bad: Static content
system_prompt = "Project: Unknown Project"

# ✅ Good: Dynamic markers
system_prompt = "Project: {project_name}\nDescription: {project_description}"
```

### 3. Provide Clear Guidelines

```python
system_prompt = """
You are a backend API developer.

Guidelines:
1. Use RESTful conventions (GET/POST/PUT/DELETE)
2. Validate all input data
3. Return appropriate HTTP status codes
4. Write comprehensive error messages
5. Include API documentation in comments

{mode_instructions}
"""
```

### 4. Leverage Context Wrapper

```python
# Always use get_user_message_wrapper for IterativeAgent/ReActAgent
user_message = await get_user_message_wrapper(
    user_request="Add authentication",
    project_context={
        "user_id": user.id,
        "project_id": project.id,
        "project_name": project.name,
        "tesslate_context": tesslate_md_content,  # Project-specific instructions
        "git_context": git_info  # Branch, status, etc.
    }
)

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_message}  # Includes full context
]
```

### 5. Test Marker Substitution

```python
# Test that markers are properly replaced
system_prompt = "Mode: {mode}, Project: {project_name}"

result = substitute_markers(
    system_prompt,
    {"edit_mode": "allow", "project_context": {"project_name": "Test"}},
    None
)

assert "{mode}" not in result  # All markers should be replaced
assert "Mode: allow" in result
assert "Project: Test" in result
```

## Debugging Prompts

### Logging

Enable debug logging to see final prompts:

```python
import logging
logging.getLogger("orchestrator.app.agent").setLevel(logging.DEBUG)

# Logs will show:
# [IterativeAgent] Context sent to LLM (iteration 1):
#   Message 0 [system]: <full system prompt>
#   Message 1 [user]: <context + user request>
```

### Viewing in Response

IterativeAgent includes debug data in agent_step events:

```python
async for event in agent.run(user_request, context):
    if event['type'] == 'agent_step':
        debug = event['data']['_debug']
        print("Full context:", debug['context_messages'])
        print("System prompt:", debug['context_messages'][0]['content'])
```

## Related Files

- `orchestrator/app/agent/base.py` - AbstractAgent.get_processed_system_prompt()
- `orchestrator/app/agent/iterative_agent.py` - Uses prompts.py functions
- `orchestrator/app/agent/react_agent.py` - Uses prompts.py functions
- `orchestrator/app/routers/chat.py` - Builds execution context
