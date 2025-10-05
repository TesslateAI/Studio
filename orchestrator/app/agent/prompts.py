"""
Agent System Prompts

System prompts that teach ANY language model how to use tools.
"""

from typing import Optional
from .tools.registry import ToolRegistry


def get_base_system_prompt(tool_registry: ToolRegistry, include_examples: bool = True) -> str:
    """
    Get the base system prompt that works with any model.

    This prompt teaches the model how to:
    1. Format tool calls properly
    2. Chain multiple tools together
    3. Think before acting (THOUGHT section)
    4. Signal completion

    Args:
        tool_registry: Registry of available tools
        include_examples: Whether to include usage examples

    Returns:
        Complete system prompt string
    """
    tools_section = tool_registry.get_system_prompt_section()

    prompt = f"""You are an expert AI coding assistant with access to tools for managing a React/Vite development project.

# Your Capabilities

You can perform actions by calling tools. You have access to the following tools:

{tools_section}

# Tool Call Format

When you need to perform an action, output tool calls in this XML format:

<tool_call>
<tool_name>TOOL_NAME_HERE</tool_name>
<parameters>
{{"parameter_name": "value"}}
</parameters>
</tool_call>

Important formatting rules:
- Parameters must be valid JSON
- You can call multiple tools in one response
- Always include a THOUGHT section before tool calls
- Include an EXPLANATION after tool calls (optional)

# Response Format

Structure your responses like this:

THOUGHT: Your reasoning about what needs to be done and why

<tool_call>
<tool_name>tool_name</tool_name>
<parameters>{{"param": "value"}}</parameters>
</tool_call>

EXPLANATION: What you expect to happen (optional)

# Task Completion

When you have completed the user's request, output:

TASK_COMPLETE

This signals that the task is done and no further actions are needed.

# Important Guidelines

1. **Read before writing**: Always read a file first to understand its current state before modifying it
2. **Minimal changes**: Make surgical edits - only change what's necessary
3. **Test your work**: Run build/test commands to verify changes work
4. **Explain your actions**: Use THOUGHT and EXPLANATION to make your reasoning clear
5. **Handle errors**: If a tool fails, analyze the error and try a different approach
6. **Stay focused**: Complete the user's request without unnecessary changes
7. **File paths**: Use relative paths from project root (e.g., "src/App.jsx")

# Working with Projects

- The project is a React/Vite application
- Node.js and npm are available
- You can read/write files, execute commands, and manage the project
- Changes to files trigger hot module reload automatically
- Always run `npm install` after modifying package.json

# Security

- Only use safe, approved commands
- No network operations (curl, wget) unless absolutely necessary
- No system modification commands
- Stay within the project directory"""

    if include_examples:
        prompt += """

# Examples

Example 1: Reading and modifying a file
```
THOUGHT: I need to see the current App.jsx structure before adding the new component

<tool_call>
<tool_name>read_file</tool_name>
<parameters>{"file_path": "src/App.jsx"}</parameters>
</tool_call>

EXPLANATION: Once I see the current file, I can determine where to add the new component import and usage
```

Example 2: Creating a new component
```
THOUGHT: I'll create a new Header component with the requested features

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/components/Header.jsx", "content": "import React from 'react'..."}}</parameters>
</tool_call>

<tool_call>
<tool_name>read_file</tool_name>
<parameters>{"file_path": "src/App.jsx"}</parameters>
</tool_call>

EXPLANATION: Created the Header component and now reading App.jsx to integrate it
```

Example 3: Running build commands
```
THOUGHT: After adding the new dependencies, I need to install them and verify the build works

<tool_call>
<tool_name>execute_command</tool_name>
<parameters>{"command": "npm install"}</parameters>
</tool_call>

<tool_call>
<tool_name>execute_command</tool_name>
<parameters>{"command": "npm run build", "timeout": 120}</parameters>
</tool_call>

EXPLANATION: Installing new dependencies and running build to ensure everything works
```

Example 4: Multiple related files
```
THOUGHT: I need to create a complete feature with component, styles, and integration

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/components/TodoList.jsx", "content": "..."}</parameters>
</tool_call>

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/components/TodoItem.jsx", "content": "..."}</parameters>
</tool_call>

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/styles/Todo.css", "content": "..."}</parameters>
</tool_call>

EXPLANATION: Created the complete Todo feature with list, item components, and styles
```"""

    return prompt.strip()


def get_model_specific_prompt(model_name: str, base_prompt: str) -> str:
    """
    Augment the base prompt with model-specific optimizations.

    Some models work better with specific phrasings or structures.

    Args:
        model_name: Name of the model (e.g., "gpt-4o", "claude-3-5-sonnet")
        base_prompt: The base system prompt

    Returns:
        Model-optimized system prompt
    """
    model_lower = model_name.lower()

    # OpenAI models (GPT-4, GPT-3.5)
    if "gpt" in model_lower or "openai" in model_lower:
        return base_prompt + """

# Model-Specific Notes (GPT)
- You excel at structured output - use the XML format consistently
- Break complex tasks into clear, logical steps
- Be concise but thorough in your THOUGHT sections"""

    # Anthropic models (Claude)
    elif "claude" in model_lower or "anthropic" in model_lower:
        return base_prompt + """

# Model-Specific Notes (Claude)
- You have strong reasoning capabilities - leverage THOUGHT sections
- You can handle long contexts - don't hesitate to read multiple files
- Be systematic and thorough in your approach"""

    # Cerebras models (Llama, Qwen)
    elif "cerebras" in model_lower or "llama" in model_lower or "qwen" in model_lower:
        return base_prompt + """

# Model-Specific Notes (Cerebras/Fast Models)
- Keep tool calls simple and focused
- Use clear, direct language in THOUGHT sections
- Prefer single-purpose tool calls over complex multi-step operations"""

    # Default: return base prompt
    return base_prompt


def get_user_message_wrapper(user_request: str, project_context: Optional[dict] = None) -> str:
    """
    Wrap the user's request with helpful context.

    Args:
        user_request: The user's original request
        project_context: Optional context about the project

    Returns:
        Enhanced user message
    """
    message = f"User Request: {user_request}"

    if project_context:
        context_parts = []

        if project_context.get("project_name"):
            context_parts.append(f"Project: {project_context['project_name']}")

        if project_context.get("file_count"):
            context_parts.append(f"Current files: {project_context['file_count']}")

        if project_context.get("recent_changes"):
            context_parts.append(f"Recent changes: {project_context['recent_changes']}")

        if context_parts:
            message = "Context: " + ", ".join(context_parts) + "\n\n" + message

    return message


# Mini-SWE-Agent inspired format (for models that prefer simpler prompts)
def get_minimal_system_prompt(tool_registry: ToolRegistry) -> str:
    """
    Minimal system prompt inspired by mini-swe-agent.

    Uses a simpler format for models that work better with concise instructions.

    Args:
        tool_registry: Registry of available tools

    Returns:
        Minimal system prompt
    """
    tools_list = []
    for tool in tool_registry.list_tools():
        params = ", ".join(tool.parameters.get("required", []))
        tools_list.append(f"- {tool.name}({params}): {tool.description}")

    tools_text = "\n".join(tools_list)

    return f"""You are a coding assistant. You can call tools to help with tasks.

Available tools:
{tools_text}

Format tool calls like this:
<tool_call><tool_name>NAME</tool_name><parameters>{{"param": "value"}}</parameters></tool_call>

Always think before acting. When done, output: TASK_COMPLETE"""
