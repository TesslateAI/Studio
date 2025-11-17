# Agent Tool Management System

## Overview

The Tool Management System allows users to customize which tools are available for each agent and modify tool descriptions and examples. This enables:

- **Tool Selection**: Enable/disable specific tools for each agent
- **Custom Tool Prompts**: Edit tool descriptions that agents see in their system prompts
- **Custom Examples**: Add agent-specific examples for better tool usage
- **Agent Duplication**: Fork agents with different tool configurations
- **Scalable Design**: Works for unlimited agents and agent types

## Architecture

### Database Schema

#### MarketplaceAgent Model Extensions

```python
# orchestrator/app/models.py (line 259-260)
tools = Column(JSON, nullable=True)  # List of enabled tool names
tool_configs = Column(JSON, nullable=True)  # Custom tool prompts
```

**tools** structure:
```json
["read_file", "write_file", "bash_exec", "web_fetch"]
```

**tool_configs** structure:
```json
{
  "read_file": {
    "description": "Read and analyze project files",
    "examples": ["Read package.json", "Check configuration files"]
  },
  "write_file": {
    "description": "Create or modify files in the project",
    "examples": ["Create new component", "Update README"]
  }
}
```

### Backend Implementation

#### 1. Tool Registry with Custom Configurations

**File**: `orchestrator/app/agent/tools/registry.py`

```python
def create_scoped_tool_registry(
    tool_names: List[str],
    tool_configs: Optional[Dict[str, Dict[str, Any]]] = None
) -> ToolRegistry:
    """
    Creates a ToolRegistry with only specified tools and custom configs.

    Args:
        tool_names: List of tool names to include
        tool_configs: Custom descriptions and examples per tool

    Returns:
        Scoped ToolRegistry with customized tools
    """
```

**How it works**:
1. Loads global tool registry
2. Creates scoped registry with only selected tools
3. Applies custom descriptions and examples if provided
4. Returns customized tool registry for agent

#### 2. Agent Factory Integration

**File**: `orchestrator/app/agent/factory.py` (lines 89-95)

```python
if agent_model.tools:
    # Pass custom tool configurations if available
    tool_configs = agent_model.tool_configs if hasattr(agent_model, 'tool_configs') else None
    if tool_configs:
        logger.info(f"Applying custom tool configurations for {len(tool_configs)} tools")
    tools = create_scoped_tool_registry(agent_model.tools, tool_configs)
```

#### 3. API Endpoints

**File**: `orchestrator/app/routers/agents.py`

**Get Available Tools**:
```python
@router.get("/tools/available")
async def get_available_tools():
    """Returns all available tools with descriptions, parameters, and examples"""
```

**Response**:
```json
[
  {
    "name": "read_file",
    "description": "Read the contents of a file",
    "category": "file_operations",
    "parameters": { /* JSON schema */ },
    "examples": ["Read package.json", "Check main.py"]
  }
]
```

**Update Agent** (marketplace.py):
```python
@router.patch("/agents/{agent_id}")
async def update_custom_agent(agent_id, update_data):
    """
    Updates agent configuration including tools and tool_configs.
    For open source agents, creates a fork with the changes.
    """
```

### Frontend Implementation

#### 1. ToolManagement Component

**File**: `app/src/components/ToolManagement.tsx`

**Features**:
- Browse tools by category (file_operations, shell_commands, etc.)
- Search tools by name/description
- Select/deselect tools with checkboxes
- Bulk select/deselect by category
- Edit tool descriptions
- Add/edit/remove tool examples
- Visual indicators for customized tools
- Expandable/collapsible categories

**Key Functions**:
```typescript
interface ToolManagementProps {
  selectedTools: string[];                    // List of enabled tool names
  toolConfigs: Record<string, ToolConfig>;    // Custom configs per tool
  onToolsChange: (                            // Callback when tools change
    tools: string[],
    configs: Record<string, ToolConfig>
  ) => void;
}
```

#### 2. Library Integration

**File**: `app/src/pages/Library.tsx` (lines 1727-1738)

The ToolManagement component is integrated into the EditAgentModal:

```typescript
{/* Tool Management */}
<div className="mt-6 p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
  <ToolManagement
    selectedTools={tools}
    toolConfigs={toolConfigs}
    onToolsChange={(newTools, newConfigs) => {
      setTools(newTools);
      setToolConfigs(newConfigs);
    }}
    availableModels={availableModels}
  />
</div>
```

## User Workflows

### 1. Customize Tools for Existing Agent

1. Navigate to **Library** page
2. Click **Edit** on an agent card
3. Scroll to **Tool Configuration** section
4. Use search or browse categories to find tools
5. Check/uncheck tools to enable/disable
6. Click pencil icon on a tool to customize:
   - Edit the description (what the agent sees in system prompt)
   - Add/edit examples specific to your use case
7. Click **Save Changes**

**Result**:
- If you own the agent: Updates directly
- If it's an open source agent: Creates a custom fork

### 2. Fork Agent with Different Tools

1. Go to **Marketplace** or **Library**
2. Find an open source agent
3. Click **Edit** (from library) or **Add to Library** then **Edit**
4. Modify name, description, system prompt
5. Customize tool selection and configurations
6. Click **Save Changes**

**Result**: Creates a forked agent with:
- Custom name (e.g., "Frontend Builder - Fork")
- Your selected tools
- Your custom tool descriptions
- Marked as "Custom" or "Forked" in library

### 3. Duplicate and Specialize Agents

**Example**: Create specialized agents from one base agent

**Base Agent**: "Full Stack Builder" (has all tools)

**Specialized Agents**:
- **Frontend Specialist**:
  - Tools: `read_file`, `write_file`, `patch_file`, `web_fetch`
  - Custom descriptions focused on React/CSS

- **Backend Specialist**:
  - Tools: `read_file`, `write_file`, `bash_exec`, `shell_open`
  - Custom descriptions focused on APIs/databases

- **DevOps Specialist**:
  - Tools: `bash_exec`, `shell_open`, `read_file`, `write_file`
  - Custom descriptions focused on Docker/deployment

## Available Tools (Default Set)

### File Operations
- `read_file`: Read file contents
- `write_file`: Create or overwrite files
- `patch_file`: Apply patches to existing files
- `multi_edit`: Edit multiple files at once

### Shell Commands
- `bash_exec`: Execute bash commands
- `shell_open`: Open interactive shell session
- `shell_exec`: Execute command in existing shell
- `shell_close`: Close shell session

### Project Operations
- `get_project_info`: Get project metadata and structure

### Planning Operations
- `todo_read`: Read current todo list
- `todo_write`: Update todo list

### Web Operations
- `web_fetch`: Fetch content from URLs

## Technical Details

### Tool Description Flow

1. **Default Tool Description**: Defined in tool implementation
2. **Custom Description**: Stored in `tool_configs.tool_name.description`
3. **System Prompt Generation**:
   - Agent factory creates scoped registry
   - Custom descriptions replace defaults
   - Registry generates system prompt section
   - Agent receives customized tool documentation

### Custom Examples Flow

1. **Default Examples**: Defined in tool implementation
2. **Custom Examples**: Stored in `tool_configs.tool_name.examples`
3. **System Prompt**: Examples are appended to tool description
4. **Agent Behavior**: More specific examples = better tool usage

### Forking Behavior

When editing an open source agent you don't own:

1. **Check Ownership**: `forked_by_user_id == current_user.id`
2. **Not Owner**: Create fork automatically
3. **Fork Properties**:
   - New slug: `{original-slug}-fork-{user_id}-{timestamp}`
   - Parent ID: Points to original agent
   - User ID: `forked_by_user_id` = current user
   - Active: Only fork is active in your library
   - Published: False (private to you)

4. **Fork Includes**:
   - Modified name, description, system_prompt
   - Custom tool selection
   - Custom tool configurations
   - Selected model

## Migration

**File**: `scripts/migrations/add_tool_configs_column.py`

Adds `tool_configs` JSON column to `marketplace_agents` table.

**Run migration**:
```bash
docker exec tesslate-orchestrator python -c "
import asyncio
from sqlalchemy import text
from app.database import engine

async def add_column():
    async with engine.begin() as conn:
        await conn.execute(text('ALTER TABLE marketplace_agents ADD COLUMN tool_configs JSON'))

asyncio.run(add_column())
"
```

## Benefits

### For Users
- **Specialization**: Create focused agents for specific tasks
- **Better Prompts**: Customize tool descriptions for your workflow
- **Examples**: Add context-specific examples
- **Experimentation**: Try different tool combinations
- **Organization**: Maintain library of specialized agents

### For Agents
- **Clarity**: Custom descriptions improve tool usage
- **Context**: Relevant examples guide better decisions
- **Focus**: Fewer tools = less confusion, better performance
- **Precision**: Tool descriptions match actual use cases

### For Platform
- **Scalability**: Works for unlimited agents
- **Flexibility**: Users can adapt pre-built agents
- **Marketplace**: Enables community-created specialized agents
- **Differentiation**: Unique selling point for platform

## Future Enhancements

1. **Parameter Customization**: Allow editing tool parameter schemas
2. **Tool Presets**: Save common tool combinations
3. **Sharing**: Publish custom tool configurations
4. **Templates**: "Frontend", "Backend", "DevOps" tool sets
5. **Analytics**: Track which tools are most used/customized
6. **Validation**: Ensure tool dependencies are met
7. **Recommendations**: Suggest tools based on agent type

## Code References

### Backend Files
- [orchestrator/app/models.py:260](orchestrator/app/models.py#L260) - tool_configs column
- [orchestrator/app/agent/tools/registry.py:258](orchestrator/app/agent/tools/registry.py#L258) - create_scoped_tool_registry
- [orchestrator/app/agent/factory.py:89](orchestrator/app/agent/factory.py#L89) - Tool config application
- [orchestrator/app/routers/agents.py:85](orchestrator/app/routers/agents.py#L85) - Get available tools endpoint
- [orchestrator/app/routers/marketplace.py:1050](orchestrator/app/routers/marketplace.py#L1050) - Update agent endpoint

### Frontend Files
- [app/src/components/ToolManagement.tsx](app/src/components/ToolManagement.tsx) - Tool management UI
- [app/src/pages/Library.tsx:1727](app/src/pages/Library.tsx#L1727) - Integration in edit modal
- [app/src/lib/api.ts:452](app/src/lib/api.ts#L452) - API client types

## Testing

### Manual Testing Steps

1. **Test Tool Selection**:
   - Edit an agent in Library
   - Select/deselect tools
   - Save and verify agent uses only selected tools

2. **Test Custom Descriptions**:
   - Edit a tool's description
   - Save agent
   - Chat with agent and verify it references custom description

3. **Test Examples**:
   - Add custom examples to a tool
   - Observe agent using examples as guidance

4. **Test Forking**:
   - Edit an open source agent
   - Verify fork is created
   - Check original remains unchanged

5. **Test Persistence**:
   - Reload page after saving
   - Verify tool configs are preserved

## Summary

The Tool Management System provides a comprehensive solution for customizing agent capabilities. Users can:

✅ Select which tools each agent can use
✅ Customize tool descriptions and examples
✅ Create specialized agents through duplication
✅ Fork open source agents with custom configurations
✅ Manage unlimited agents with different tool sets

This system scales infinitely and works across all agent types, making Tesslate Studio's agents highly customizable and adaptable to any workflow.
