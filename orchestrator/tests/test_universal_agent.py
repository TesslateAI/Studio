"""
Test script for Universal Agent System

Tests the agent's ability to parse tool calls and work with different models.
"""

import sys
import os

# Add parent directory (orchestrator) to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.agent.parser import AgentResponseParser
from app.agent.tools.registry import get_tool_registry
from app.agent.prompts import get_base_system_prompt


def test_parser():
    """Test the response parser with various formats."""
    print("=" * 80)
    print("TESTING AGENT RESPONSE PARSER")
    print("=" * 80)

    parser = AgentResponseParser()

    test_cases = [
        (
            "XML Format",
            """
THOUGHT: I need to read the package.json file first

<tool_call>
<tool_name>read_file</tool_name>
<parameters>{"file_path": "package.json"}</parameters>
</tool_call>

EXPLANATION: This will show me the current dependencies
            """,
            1
        ),
        (
            "Multiple Tools",
            """
THOUGHT: I'll create the component and then read App.jsx

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/Header.jsx", "content": "import React..."}</parameters>
</tool_call>

<tool_call>
<tool_name>read_file</tool_name>
<parameters>{"file_path": "src/App.jsx"}</parameters>
</tool_call>
            """,
            2
        ),
        (
            "Bash Format",
            """
THOUGHT: I'll install the dependencies

```bash
npm install
```
            """,
            1
        ),
        (
            "Completion Signal",
            """
I've completed all the requested changes.

TASK_COMPLETE
            """,
            0
        ),
        (
            "No Tools",
            """
THOUGHT: Let me analyze the current situation

Based on the error, the issue is with the import statement. You need to update
the import to use the correct path.
            """,
            0
        ),
        (
            "TASK_COMPLETE Removal Test",
            """
I've successfully created all the requested components and updated the routing.

TASK_COMPLETE
            """,
            0
        )
    ]

    passed = 0
    failed = 0

    for name, response, expected_tools in test_cases:
        tool_calls = parser.parse(response)
        is_complete = parser.is_complete(response)

        success = len(tool_calls) == expected_tools

        if success:
            print(f"\n[PASS] {name}")
            passed += 1
        else:
            print(f"\n[FAIL] {name}")
            failed += 1

        print(f"  Expected {expected_tools} tool calls, got {len(tool_calls)}")
        if tool_calls:
            for tc in tool_calls:
                print(f"    - {tc.name}: {tc.parameters}")
        print(f"  Complete: {is_complete}")

    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("=" * 80)

    return failed == 0


def test_conversational_text_extraction():
    """Test that conversational text extraction removes TASK_COMPLETE and tool calls."""
    print("\n" + "=" * 80)
    print("TESTING CONVERSATIONAL TEXT EXTRACTION")
    print("=" * 80)

    parser = AgentResponseParser()

    test_cases = [
        (
            "TASK_COMPLETE Removal",
            """
I've successfully created the Header component with all the requested features.

TASK_COMPLETE
            """,
            "I've successfully created the Header component with all the requested features."
        ),
        (
            "Tool Call Removal",
            """
THOUGHT: I need to read the file first

<tool_call>
<tool_name>read_file</tool_name>
<parameters>{"file_path": "src/App.jsx"}</parameters>
</tool_call>

Let me check the current structure.
            """,
            "THOUGHT: I need to read the file first\n\nLet me check the current structure."
        ),
        (
            "Mixed Content",
            """
I've analyzed the code and found the issue.

<tool_call>
<tool_name>write_file</tool_name>
<parameters>{"file_path": "src/fix.js", "content": "fixed code"}</parameters>
</tool_call>

The fix has been applied successfully.

TASK_COMPLETE
            """,
            "I've analyzed the code and found the issue.\n\nThe fix has been applied successfully."
        )
    ]

    passed = 0
    failed = 0

    for name, response, expected_output in test_cases:
        conversational_text = parser.get_conversational_text(response)

        # Normalize whitespace for comparison
        conversational_text = conversational_text.strip()
        expected_output = expected_output.strip()

        success = conversational_text == expected_output

        if success:
            print(f"\n[PASS] {name}")
            passed += 1
        else:
            print(f"\n[FAIL] {name}")
            print(f"  Expected: {repr(expected_output)}")
            print(f"  Got:      {repr(conversational_text)}")
            failed += 1

    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("=" * 80)

    return failed == 0


def test_tool_registry():
    """Test the tool registry."""
    print("\n" + "=" * 80)
    print("TESTING TOOL REGISTRY")
    print("=" * 80)

    registry = get_tool_registry()

    print(f"\nRegistered {len(registry._tools)} tools:")
    for category in ["file_operations", "shell_commands", "project_management"]:
        from app.agent.tools.registry import ToolCategory
        try:
            cat = ToolCategory(category)
            tools = registry.list_tools(cat)
            if tools:
                print(f"\n  {category.replace('_', ' ').title()}:")
                for tool in tools:
                    params = ", ".join(tool.parameters.get("required", []))
                    print(f"    - {tool.name}({params}): {tool.description[:60]}...")
        except:
            pass

    print("\n" + "=" * 80)
    return True


def test_system_prompt():
    """Test system prompt generation."""
    print("\n" + "=" * 80)
    print("TESTING SYSTEM PROMPT GENERATION")
    print("=" * 80)

    registry = get_tool_registry()
    prompt = get_base_system_prompt(registry, include_examples=True)

    print(f"\nGenerated system prompt ({len(prompt)} characters)")
    print("\nFirst 500 characters:")
    print(prompt[:500])
    print("...")
    print("\nLast 500 characters:")
    print("..." + prompt[-500:])

    # Check for key sections
    required_sections = [
        "tool_call",
        "parameters",
        "THOUGHT",
        "TASK_COMPLETE",
        "read_file",
        "write_file",
        "execute_command"
    ]

    print("\nChecking for required sections:")
    all_found = True
    for section in required_sections:
        found = section in prompt
        status = "[OK]" if found else "[MISSING]"
        print(f"  {status} {section}")
        if not found:
            all_found = False

    print("\n" + "=" * 80)
    return all_found


def print_usage_guide():
    """Print usage guide for the agent API."""
    print("\n" + "=" * 80)
    print("UNIVERSAL AGENT API USAGE GUIDE")
    print("=" * 80)

    print("""
# Agent Chat Endpoint

POST /api/chat/agent
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "project_id": 123,
  "message": "Create a new Header component with a logo and navigation menu",
  "max_iterations": 20,
  "minimal_prompts": false
}

Response:
{
  "success": true,
  "iterations": 5,
  "final_response": "I've created the Header component...",
  "tool_calls_made": 8,
  "completion_reason": "task_complete_signal",
  "steps": [
    {
      "iteration": 1,
      "thought": "I need to read the current App.jsx structure",
      "tool_calls": ["read_file"],
      "response_text": "...",
      "is_complete": false,
      "timestamp": "2025-01-15T10:30:00"
    },
    ...
  ],
  "error": null
}


# Example curl command:

# 1. Get token
TOKEN=$(curl -X POST http://localhost:8000/api/auth/token \\
  -d "username=testuser&password=testpass" | jq -r .access_token)

# 2. Send agent request
curl -X POST http://localhost:8000/api/chat/agent \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "project_id": 123,
    "message": "Add a todo list feature to the app",
    "max_iterations": 15
  }'


# What the Agent Can Do:

1. File Operations
   - Read files from the project
   - Write/create new files
   - List directory contents
   - Delete files

2. Shell Commands
   - Execute npm commands (install, build, test)
   - Run git commands
   - Execute other safe shell commands
   - Multiple commands in sequence

3. Project Management
   - Get project information
   - View file tree structure
   - Get file summaries


# Model Compatibility:

The agent works with ANY model - just set OPENAI_MODEL in your environment:

- Cerebras: OPENAI_MODEL=cerebras/llama3.1-8b (default)
- OpenAI: OPENAI_MODEL=gpt-4o
- Claude: Set OPENAI_MODEL=claude-3-5-sonnet-20241022 (requires Anthropic API key)

The agent uses prompt engineering (not function calling APIs) so it works with
all models that can follow instructions and output structured text.


# Testing Locally:

1. Start the orchestrator:
   cd orchestrator && uv run uvicorn app.main:app --reload

2. Create a test project and get its ID

3. Send an agent request with curl or Postman

4. Watch the agent:
   - Read files to understand the codebase
   - Generate new code
   - Write files
   - Run build commands
   - Complete the task autonomously


# Advantages over Regular Chat:

- Autonomous: Agent decides what tools to use and when
- Iterative: Can read, modify, test in a loop
- Auditable: Full execution trace with all tool calls
- Model-agnostic: Works with any LLM
- Deterministic: Clear tool execution, not just code generation
- Debuggable: See each step's thought process and actions


# When to Use Agent vs Regular Chat:

Use Agent when:
- Task requires multiple steps (read, modify, test)
- Need to execute commands automatically
- Want full autonomy with tool use
- Need detailed execution log

Use Regular Chat when:
- Just generating code snippets
- Real-time streaming preferred
- Simpler, single-shot generation
- Don't need tool execution
""")

    print("=" * 80)


if __name__ == "__main__":
    print("\n")
    print("Testing Universal Agent System")
    print("\n")

    # Run tests
    parser_ok = test_parser()
    conversational_ok = test_conversational_text_extraction()
    registry_ok = test_tool_registry()
    prompt_ok = test_system_prompt()

    # Print usage guide
    print_usage_guide()

    # Summary
    if parser_ok and conversational_ok and registry_ok and prompt_ok:
        print("\n[SUCCESS] All tests passed! Universal Agent is ready.")
        print("\nNext steps:")
        print("1. Start orchestrator: cd orchestrator && uv run uvicorn app.main:app --reload")
        print("2. Test agent endpoint: POST /api/chat/agent")
        print("3. Try tasks like: 'Create a todo list component'")
        sys.exit(0)
    else:
        print("\n[FAILED] Some tests failed.")
        sys.exit(1)
