# Agent Types

OpenSail provides three agent implementations, each optimized for different use cases. All agents inherit from the `AbstractAgent` base class and can be instantiated via the factory pattern.

## AbstractAgent Base Class

**File**: `orchestrator/app/agent/base.py`

The abstract base that defines the common interface for all agents:

```python
class AbstractAgent(ABC):
    def __init__(self, system_prompt: str, tools: Optional[ToolRegistry] = None):
        self.system_prompt = system_prompt
        self.tools = tools

    def get_processed_system_prompt(self, context: Dict[str, Any]) -> str:
        """Get system prompt with {markers} substituted."""
        tool_names = list(self.tools._tools.keys()) if self.tools else None
        return substitute_markers(self.system_prompt, context, tool_names)

    @abstractmethod
    async def run(
        self,
        user_request: str,
        context: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the agent. Must be implemented by subclasses."""
        yield {}
```

### Key Methods

- **`__init__`**: Initialize with system prompt and optional tool registry
- **`get_processed_system_prompt`**: Substitute {markers} like {mode}, {project_name}
- **`run`**: Abstract method that all agents must implement

### Event Types

All agents yield events during execution:

```python
{'type': 'stream', 'content': '...'}  # Text chunks (StreamAgent)
{'type': 'agent_step', 'data': {...}}  # Tool execution step
{'type': 'file_ready', 'file_path': '...', 'content': '...'}
{'type': 'status', 'content': '...'}  # Status messages
{'type': 'complete', 'data': {...}}  # Task completion
{'type': 'error', 'content': '...'}  # Error messages
{'type': 'approval_required', 'data': {...}}  # Ask mode approval
{'type': 'text_chunk', 'data': {...}}  # Real-time LLM generation
```

## StreamAgent

**File**: `orchestrator/app/agent/stream_agent.py`

Simple agent that streams LLM responses directly to the user without tool calling.

### Architecture

```
User Request
    ↓
System Prompt + Context
    ↓
LLM API (streaming)
    ↓
Extract Code Blocks
    ↓
Save Files
    ↓
Return Streaming Response
```

### Use Cases

- Quick code generation
- Simple explanations
- One-shot file creation
- Prototyping without iteration

### Example Usage

```python
agent = StreamAgent(
    system_prompt="You are a React expert. Generate components.",
    tools=None  # StreamAgent doesn't use tools
)

async for event in agent.run("Create a Button component", context):
    if event['type'] == 'stream':
        print(event['content'], end='', flush=True)
    elif event['type'] == 'file_ready':
        print(f"\n✓ Saved: {event['file_path']}")
```

### Code Block Extraction

StreamAgent automatically extracts code blocks from the response:

```markdown
Here's a Button component:

```jsx
// File: src/components/Button.jsx
import React from 'react';

export function Button({ children, onClick }) {
  return <button onClick={onClick}>{children}</button>;
}
```
```

The agent detects these patterns:
- `// File: path` - Comment-style file marker
- `# File: path` - Python-style marker
- `<!-- File: path -->` - HTML comment marker

### Limitations

- No tool calling (can't execute shell commands)
- No iterative refinement (one-shot generation)
- No error recovery
- Limited to code block extraction

### When to Use

Use StreamAgent when:
- User wants quick code generation
- Task is simple and doesn't require iteration
- No shell commands needed
- Speed is more important than accuracy

## IterativeAgent

**File**: `orchestrator/app/agent/iterative_agent.py`

Advanced agent with think-act-reflect loop and full tool calling support.

### Architecture

```
User Request
    ↓
System Prompt + Tool Info + Context
    ↓
┌─────────────────────┐
│   Iteration Loop    │
│                     │
│  1. LLM thinks      │
│  2. Parses tool     │
│     calls from JSON │
│  3. Executes tools  │
│  4. Feeds results   │
│     back to LLM     │
│                     │
│  Repeat until       │
│  TASK_COMPLETE      │
└─────────────────────┘
    ↓
Final Response
```

### Tool Calling Format

IterativeAgent expects tools in pure JSON format:

```python
# Single tool call
THOUGHT: I need to read the file to understand the current implementation.

{
  "tool_name": "read_file",
  "parameters": {
    "file_path": "src/App.jsx"
  }
}

# Multiple tool calls
THOUGHT: I'll read the file and check dependencies.

[
  {
    "tool_name": "read_file",
    "parameters": {"file_path": "src/App.jsx"}
  },
  {
    "tool_name": "bash_exec",
    "parameters": {"command": "cat package.json"}
  }
]
```

### Execution Tracking

The agent tracks its progress:

```python
class AgentStep:
    iteration: int
    thought: Optional[str]  # Extracted THOUGHT section
    tool_calls: List[ToolCall]  # Parsed tool calls
    tool_results: List[Dict[str, Any]]  # Tool execution results
    response_text: str  # Display text for user
    timestamp: datetime
    is_complete: bool
```

### Error Recovery

IterativeAgent automatically retries on errors:

```python
# If tool execution fails:
if self.last_step_had_errors:
    # Force retry with instruction
    retry_instruction = (
        "\n\nThe previous tool calls had errors. "
        "You MUST retry the failed operations with corrected parameters. "
        "Do NOT give up - fix the errors and try again."
    )
    self.messages.append({"role": "user", "content": retry_instruction})
    continue  # Force next iteration
```

### Resource Limits

Prevents infinite loops:

```python
from orchestrator.app.agent.resource_limits import get_resource_limits

limits = get_resource_limits()
limits.add_iteration(run_id)  # Raises ResourceLimitExceeded if over limit
```

Default limits:
- Max iterations: 25
- Max tool calls: 100

### Example Usage

```python
from orchestrator.app.agent.models import get_model_adapter

model = await get_model_adapter(model_name="gpt-4", user_id=user.id, db=db)

agent = IterativeAgent(
    system_prompt="You are a full-stack developer.",
    tools=get_tool_registry(),
    model=model
)

async for event in agent.run("Add authentication to the app", context):
    if event['type'] == 'agent_step':
        step = event['data']
        print(f"Iteration {step['iteration']}")
        print(f"Thought: {step['thought']}")
        print(f"Tools: {[t['name'] for t in step['tool_calls']]}")
    elif event['type'] == 'complete':
        print(f"✓ Completed in {event['data']['iterations']} iterations")
```

### When to Use

Use IterativeAgent when:
- Task requires multiple steps
- Need to execute shell commands
- Want automatic error recovery
- Task complexity is moderate to high
- Need reliable file operations

## ReActAgent

**File**: `orchestrator/app/agent/react_agent.py`

Agent that explicitly implements the ReAct (Reasoning + Acting) paradigm with structured thought-action-observation cycles.

### Architecture

```
User Request
    ↓
System Prompt + ReAct Instructions + Context
    ↓
┌──────────────────────┐
│   ReAct Loop         │
│                      │
│  THOUGHT (Reasoning) │
│     ↓                │
│  ACTION (Tool calls) │
│     ↓                │
│  OBSERVATION (Results)│
│     ↓                │
│  Repeat until done   │
└──────────────────────┘
    ↓
Final Response
```

### ReAct Methodology

Based on the paper "ReAct: Synergizing Reasoning and Acting in Language Models" (https://arxiv.org/abs/2210.03629).

Key principles:
1. **Explicit Reasoning**: Every action must be preceded by a THOUGHT section
2. **Structured Observations**: Tool results are formatted as observations
3. **Iterative Refinement**: Loop continues until reasoning concludes task is complete

### Tool Calling Format

Same as IterativeAgent, but with stronger emphasis on reasoning:

```python
THOUGHT: The user wants authentication, so I need to first understand the current
project structure. I'll read the main App.jsx file to see how routing is set up,
then check if any authentication libraries are already installed.

[
  {
    "tool_name": "read_file",
    "parameters": {"file_path": "src/App.jsx"}
  },
  {
    "tool_name": "bash_exec",
    "parameters": {"command": "cat package.json"}
  }
]
```

### Observation Formatting

Tool results are formatted as observations to reinforce the ReAct pattern:

```
Observation:

1. read_file: ✓ Success
   message: Read 245 bytes from 'src/App.jsx'
   content:
   | import React from 'react';
   | import { BrowserRouter, Routes, Route } from 'react-router-dom';
   | ...

2. bash_exec: ✓ Success
   message: Executed 'cat package.json'
   output:
   | {
   |   "dependencies": {
   |     "react": "^18.0.0",
   |     "react-router-dom": "^6.0.0"
   |   }
   | }
```

### Differences from IterativeAgent

| Feature | IterativeAgent | ReActAgent |
|---------|----------------|------------|
| Reasoning Emphasis | Optional | Mandatory (enforced in prompt) |
| Result Format | Tool Results | Observations |
| Use Case | General tasks | Complex reasoning tasks |
| Prompt Style | Action-focused | Thought-focused |

### Example Usage

```python
agent = ReActAgent(
    system_prompt="You are an expert at debugging complex issues.",
    tools=get_tool_registry(),
    model=model
)

async for event in agent.run(
    "The app crashes on startup. Find and fix the issue.",
    context
):
    if event['type'] == 'agent_step':
        step = event['data']
        print(f"\n=== Iteration {step['iteration']} ===")
        print(f"Thought: {step['thought']}")

        if step['tool_calls']:
            print("Actions:")
            for tc in step['tool_calls']:
                print(f"  - {tc['name']}")
```

### When to Use

Use ReActAgent when:
- Task requires complex reasoning
- Need explicit thought process (for debugging)
- Working on architecture decisions
- Solving bugs or investigating issues
- Want to audit agent's reasoning

## Comparison Table

| Aspect | StreamAgent | IterativeAgent | ReActAgent |
|--------|-------------|----------------|------------|
| **Tool Support** | ❌ No | ✅ Yes | ✅ Yes |
| **Iteration** | ❌ Single pass | ✅ Multi-step | ✅ Multi-step |
| **Error Recovery** | ❌ No | ✅ Automatic retry | ✅ Automatic retry |
| **Reasoning** | ❌ Implicit | ⚠️ Optional | ✅ Explicit/Required |
| **Speed** | ⚡ Fast | 🐢 Slower | 🐢 Slower |
| **Token Usage** | 💰 Low | 💰💰 Medium | 💰💰💰 High |
| **Best For** | Quick generation | General tasks | Complex reasoning |
| **Approval Mode** | ❌ N/A | ✅ Supported | ✅ Supported |

## Choosing the Right Agent

### Use StreamAgent when:
- User wants instant results
- Task is straightforward (create component, generate config)
- No shell commands needed
- Cost optimization is important

### Use IterativeAgent when:
- Task has multiple steps (install packages → create files → run tests)
- Need reliable error recovery
- Working with existing codebase
- General-purpose development tasks

### Use ReActAgent when:
- Task requires careful reasoning (debugging, architecture)
- Need to audit agent's thought process
- Complex problem-solving
- Educational purposes (showing reasoning)

## Creating Custom Agents

To create a custom agent type:

### 1. Subclass AbstractAgent

```python
from orchestrator.app.agent.base import AbstractAgent

class MyCustomAgent(AbstractAgent):
    def __init__(self, system_prompt: str, tools: Optional[ToolRegistry] = None):
        super().__init__(system_prompt, tools)
        # Custom initialization

    async def run(
        self,
        user_request: str,
        context: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        # Custom execution logic
        yield {'type': 'status', 'content': 'Starting...'}

        # Use self.get_processed_system_prompt(context) for marker substitution
        system_prompt = self.get_processed_system_prompt(context)

        # Your agent logic here

        yield {'type': 'complete', 'data': {'result': '...'}}
```

### 2. Register in Factory

```python
# orchestrator/app/agent/factory.py

from .my_custom_agent import MyCustomAgent

AGENT_CLASS_MAP = {
    "StreamAgent": StreamAgent,
    "IterativeAgent": IterativeAgent,
    "ReActAgent": ReActAgent,
    "MyCustomAgent": MyCustomAgent,  # Add your agent
}
```

### 3. Create Marketplace Entry

```sql
INSERT INTO marketplace_agents (agent_type, ...)
VALUES ('MyCustomAgent', ...);
```

Now your agent can be instantiated via `create_agent_from_db_model`.
