"""
Unit tests for AgentResponseParser.

Tests tool call parsing, completion detection, thought extraction,
and pure JSON-format tool calls.
"""

import pytest
from app.agent.parser import AgentResponseParser, ToolCall


@pytest.mark.unit
class TestAgentResponseParser:
    """Test suite for AgentResponseParser."""

    @pytest.fixture
    def parser(self):
        """Create a parser instance for testing."""
        return AgentResponseParser()

    def test_parse_json_single_tool_call(self, parser):
        """Test parsing a single JSON-format tool call."""
        response = """
THOUGHT: I need to read the App.jsx file.

{
  "tool_name": "read_file",
  "parameters": {
    "file_path": "src/App.jsx"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].parameters == {"file_path": "src/App.jsx"}

    def test_parse_json_multiple_tool_calls(self, parser):
        """Test parsing multiple JSON-format tool calls (array)."""
        response = """
[
  {
    "tool_name": "write_file",
    "parameters": {
      "file_path": "src/Header.jsx",
      "content": "import React from 'react';"
    }
  },
  {
    "tool_name": "write_file",
    "parameters": {
      "file_path": "src/Footer.jsx",
      "content": "import React from 'react';"
    }
  }
]
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 2
        assert tool_calls[0].name == "write_file"
        assert tool_calls[0].parameters["file_path"] == "src/Header.jsx"
        assert tool_calls[1].name == "write_file"
        assert tool_calls[1].parameters["file_path"] == "src/Footer.jsx"

    def test_parse_bash_code_block(self, parser):
        """Test that bash code blocks are NOT parsed (JSON-only)."""
        response = """
I'll run this command:

```bash
ls -la src/
```
"""
        tool_calls = parser.parse(response)

        # Bash blocks should not be parsed - only JSON format is supported
        assert len(tool_calls) == 0

    def test_parse_no_tool_calls(self, parser):
        """Test parsing response with no tool calls."""
        response = "This is just a conversational response with no tools."

        tool_calls = parser.parse(response)

        assert len(tool_calls) == 0

    def test_parse_json_with_escaped_quotes(self, parser):
        """Test parsing JSON with escaped quotes."""
        response = """
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "content": "const message = \\"Hello World\\";"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert '"Hello World"' in tool_calls[0].parameters["content"]

    def test_parse_error_invalid_json(self, parser):
        """Test handling of invalid JSON."""
        response = """
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "test.js",
    "content": "broken json with "unescaped quotes"
  }
}
"""
        tool_calls = parser.parse(response)

        # Invalid JSON should fail to parse and return empty list
        assert len(tool_calls) == 0

    def test_is_complete_task_complete_signal(self, parser):
        """Test detection of TASK_COMPLETE signal."""
        response = """
All changes have been made successfully.

TASK_COMPLETE
"""
        assert parser.is_complete(response) is True

    def test_is_complete_alternative_signal(self, parser):
        """Test detection of alternative completion signals."""
        signals = [
            "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
            "<task_complete>",
            "<!-- TASK COMPLETE -->"
        ]

        for signal in signals:
            response = f"Done. {signal}"
            assert parser.is_complete(response) is True, f"Failed to detect: {signal}"

    def test_is_complete_no_signal(self, parser):
        """Test that non-complete responses return False."""
        response = "I'm working on the task, will complete soon."

        assert parser.is_complete(response) is False

    def test_extract_thought(self, parser):
        """Test extraction of THOUGHT section."""
        response = """
THOUGHT: I need to understand the current file structure before making changes.

{
  "tool_name": "bash_exec",
  "parameters": {
    "command": "ls src/"
  }
}
"""
        thought = parser.extract_thought(response)

        assert thought is not None
        assert "understand the current file structure" in thought

    def test_extract_thought_not_present(self, parser):
        """Test thought extraction when no THOUGHT section exists."""
        response = "Just a simple response."

        thought = parser.extract_thought(response)

        assert thought is None

    def test_get_conversational_text(self, parser):
        """Test extraction of conversational text (without tool calls)."""
        response = """
I'll create a new button component for you.

{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/Button.jsx",
    "content": "..."
  }
}

The button component has been created successfully!
"""
        conversational = parser.get_conversational_text(response)

        assert "I'll create a new button component" in conversational
        assert "successfully" in conversational
        assert "tool_name" not in conversational
        assert "write_file" not in conversational

    def test_parse_with_whitespace_variations(self, parser):
        """Test parsing handles whitespace variations in JSON."""
        response = """
{
  "tool_name":  "read_file"  ,
  "parameters":  {
    "file_path": "test.js"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].parameters == {"file_path": "test.js"}

    def test_parse_case_sensitive_json_keys(self, parser):
        """Test that JSON keys are case-sensitive."""
        response = """
{
  "Tool_Name": "read_file",
  "Parameters": {
    "file_path": "test.js"
  }
}
"""
        tool_calls = parser.parse(response)

        # Wrong case should not be recognized
        assert len(tool_calls) == 0

    def test_parse_multiline_json_parameters(self, parser):
        """Test parsing multi-line JSON with escaped newlines."""
        response = """
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/config.js",
    "content": "const config = {\\n  api: 'https://api.example.com',\\n  timeout: 5000\\n};"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "write_file"
        assert "config" in tool_calls[0].parameters["content"]

    def test_parse_empty_parameters(self, parser):
        """Test parsing tool call with empty parameters object."""
        response = """
{
  "tool_name": "get_project_info",
  "parameters": {}
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_project_info"
        assert tool_calls[0].parameters == {}

    def test_parse_with_explanation(self, parser):
        """Test parsing response with EXPLANATION section."""
        response = """
THOUGHT: I need to modify the button color.

EXPLANATION: The current button uses blue, but we want green for better visibility.

{
  "tool_name": "patch_file",
  "parameters": {
    "file_path": "src/Button.jsx",
    "search": "bg-blue-500",
    "replace": "bg-green-500"
  }
}
"""
        tool_calls = parser.parse(response)
        explanation = parser.extract_explanation(response)

        assert len(tool_calls) == 1
        assert explanation is not None
        assert "better visibility" in explanation

    def test_parse_mixed_formats(self, parser):
        """Test that parser only parses JSON (bash blocks are ignored)."""
        response = """
{
  "tool_name": "read_file",
  "parameters": {
    "file_path": "test.js"
  }
}

```bash
ls -la
```
"""
        tool_calls = parser.parse(response)

        # Should only parse JSON - bash blocks are ignored
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"

    @pytest.mark.parametrize("invalid_json", [
        '{"tool_name": "test", "parameters": {"key": value}}',  # Missing quotes
        '{"tool_name": "test", "parameters": {"key": "value"',  # Missing closing brace
        '{tool_name: "test", parameters: {key: "value"}}',  # Unquoted keys
    ])
    def test_parse_various_json_errors(self, parser, invalid_json):
        """Test handling of various JSON syntax errors."""
        response = invalid_json
        tool_calls = parser.parse(response)

        # Invalid JSON should fail to parse
        assert len(tool_calls) == 0

    def test_tool_call_dataclass(self):
        """Test ToolCall dataclass attributes."""
        tool_call = ToolCall(
            name="test_tool",
            parameters={"param1": "value1"},
            raw_text='{"tool_name": "test_tool", ...}'
        )

        assert tool_call.name == "test_tool"
        assert tool_call.parameters["param1"] == "value1"
        assert tool_call.raw_text == '{"tool_name": "test_tool", ...}'

    def test_parse_nested_json_objects(self, parser):
        """Test parsing tool calls with nested JSON in string values."""
        response = """
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "config.json",
    "content": "{\\"database\\": {\\"host\\": \\"localhost\\", \\"port\\": 5432}}"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert "database" in tool_calls[0].parameters["content"]
        assert "localhost" in tool_calls[0].parameters["content"]

    def test_parse_unicode_content(self, parser):
        """Test parsing tool calls with Unicode characters."""
        response = """
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "test.txt",
    "content": "Hello 世界 🌍"
  }
}
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert "世界" in tool_calls[0].parameters["content"]
        assert "🌍" in tool_calls[0].parameters["content"]

    def test_get_conversational_text_removes_think_tags(self, parser):
        """Test that <think> tags are removed from conversational text."""
        response = """
<think>
This is internal reasoning that should not be shown to the user.
I'm analyzing the problem and planning my approach.
</think>

I'll create a coffee shop website for you.

{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "index.html",
    "content": "..."
  }
}

The website has been created successfully!

TASK_COMPLETE
"""
        conversational = parser.get_conversational_text(response)

        # Should contain user-facing text
        assert "I'll create a coffee shop website" in conversational
        assert "successfully" in conversational

        # Should NOT contain internal reasoning
        assert "<think>" not in conversational
        assert "</think>" not in conversational
        assert "internal reasoning" not in conversational
        assert "analyzing the problem" not in conversational

        # Should NOT contain tool calls or completion signals
        assert "tool_name" not in conversational
        assert "TASK_COMPLETE" not in conversational

    def test_parse_complex_multi_edit_stress_test(self, parser):
        """Stress test: Complex multi_edit tool call with lots of code and nested structures."""
        response = """
THOUGHT: I need to refactor this React component with multiple edits to add TypeScript, state management, and API integration.

{
  "tool_name": "multi_edit",
  "parameters": {
    "file_path": "src/components/Dashboard.jsx",
    "edits": [
      {
        "search": "import React from 'react';",
        "replace": "import React, { useState, useEffect } from 'react';\\nimport { fetchUserData, updateUserProfile } from '../api/users';"
      },
      {
        "search": "export default function Dashboard() {\\n  return (\\n    <div>Dashboard</div>\\n  );\\n}",
        "replace": "interface User {\\n  id: string;\\n  name: string;\\n  email: string;\\n  settings: {\\n    theme: 'light' | 'dark';\\n    notifications: boolean;\\n    preferences: {\\n      language: string;\\n      timezone: string;\\n    };\\n  };\\n}\\n\\nexport default function Dashboard() {\\n  const [user, setUser] = useState<User | null>(null);\\n  const [loading, setLoading] = useState(true);\\n  const [error, setError] = useState<string | null>(null);\\n\\n  useEffect(() => {\\n    async function loadUser() {\\n      try {\\n        const data = await fetchUserData();\\n        setUser(data);\\n      } catch (err) {\\n        setError(err instanceof Error ? err.message : 'Unknown error');\\n      } finally {\\n        setLoading(false);\\n      }\\n    }\\n    loadUser();\\n  }, []);\\n\\n  const handleUpdateProfile = async (updates: Partial<User>) => {\\n    if (!user) return;\\n    try {\\n      const updated = await updateUserProfile(user.id, updates);\\n      setUser(updated);\\n    } catch (err) {\\n      console.error('Failed to update profile:', err);\\n    }\\n  };\\n\\n  if (loading) {\\n    return <div className=\\"spinner\\">Loading...</div>;\\n  }\\n\\n  if (error) {\\n    return (\\n      <div className=\\"error-container\\">\\n        <h2>Error</h2>\\n        <p>{error}</p>\\n      </div>\\n    );\\n  }\\n\\n  return (\\n    <div className=\\"dashboard\\">\\n      <header>\\n        <h1>Welcome, {user?.name || 'Guest'}</h1>\\n        <p>{user?.email}</p>\\n      </header>\\n      <section className=\\"settings\\">\\n        <h2>Settings</h2>\\n        <div className=\\"setting-item\\">\\n          <label>Theme:</label>\\n          <select \\n            value={user?.settings.theme} \\n            onChange={(e) => handleUpdateProfile({\\n              settings: { ...user!.settings, theme: e.target.value as 'light' | 'dark' }\\n            })}\\n          >\\n            <option value=\\"light\\">Light</option>\\n            <option value=\\"dark\\">Dark</option>\\n          </select>\\n        </div>\\n      </section>\\n    </div>\\n  );\\n}"
      }
    ]
  }
}
"""
        tool_calls = parser.parse(response)

        # Should successfully parse despite complex nested structures
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "multi_edit"
        assert tool_calls[0].parameters["file_path"] == "src/components/Dashboard.jsx"
        assert "edits" in tool_calls[0].parameters
        assert isinstance(tool_calls[0].parameters["edits"], list)
        assert len(tool_calls[0].parameters["edits"]) == 2

        # Verify first edit
        edit1 = tool_calls[0].parameters["edits"][0]
        assert "search" in edit1
        assert "replace" in edit1
        assert "import React from 'react'" in edit1["search"]
        assert "useState" in edit1["replace"]
        assert "useEffect" in edit1["replace"]

        # Verify second edit (complex TypeScript + React code)
        edit2 = tool_calls[0].parameters["edits"][1]
        assert "interface User" in edit2["replace"]
        assert "useState<User | null>" in edit2["replace"]
        assert "fetchUserData" in edit2["replace"]
        assert "handleUpdateProfile" in edit2["replace"]
        # Check for nested object structures in code
        assert "settings: {" in edit2["replace"]
        assert "preferences: {" in edit2["replace"]
        # Check for quotes in JSX (JSON parser correctly unescapes them)
        assert 'className="' in edit2["replace"]
        # Check for conditional rendering
        assert "user?.name || 'Guest'" in edit2["replace"]

    def test_parse_editing_json_file_stress_test(self, parser):
        """Stress test: Editing a JSON file with lots of nested braces and brackets."""
        response = """
THOUGHT: I'll update the configuration file with nested JSON structures.

{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "config.json",
    "content": "{\\n  \\"database\\": {\\n    \\"primary\\": {\\n      \\"host\\": \\"localhost\\",\\n      \\"port\\": 5432,\\n      \\"credentials\\": {\\n        \\"username\\": \\"admin\\",\\n        \\"password\\": \\"secret\\"\\n      }\\n    },\\n    \\"replicas\\": [\\n      {\\n        \\"host\\": \\"replica1.example.com\\",\\n        \\"port\\": 5432\\n      },\\n      {\\n        \\"host\\": \\"replica2.example.com\\",\\n        \\"port\\": 5432\\n      }\\n    ]\\n  },\\n  \\"api\\": {\\n    \\"endpoints\\": {\\n      \\"users\\": \\"/api/v1/users\\",\\n      \\"posts\\": \\"/api/v1/posts\\",\\n      \\"comments\\": \\"/api/v1/comments\\"\\n    },\\n    \\"rateLimit\\": {\\n      \\"maxRequests\\": 100,\\n      \\"windowMs\\": 60000,\\n      \\"whitelist\\": [\\"127.0.0.1\\", \\"10.0.0.0/8\\"]\\n    }\\n  },\\n  \\"features\\": {\\n    \\"flags\\": {\\n      \\"enableNewUI\\": true,\\n      \\"enableBetaFeatures\\": false,\\n      \\"experimentalSettings\\": {\\n        \\"aiAssistant\\": true,\\n        \\"darkMode\\": true,\\n        \\"customThemes\\": [\\n          {\\"name\\": \\"ocean\\", \\"primary\\": \\"#0077be\\"},\\n          {\\"name\\": \\"sunset\\", \\"primary\\": \\"#ff6b35\\"}\\n        ]\\n      }\\n    }\\n  }\\n}"
  }
}
"""
        tool_calls = parser.parse(response)

        # Should successfully parse despite JSON file content with many nested braces
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "write_file"
        assert tool_calls[0].parameters["file_path"] == "config.json"

        content = tool_calls[0].parameters["content"]

        # Verify the JSON content is correctly parsed (not confused by nested braces)
        assert '"database":' in content
        assert '"primary":' in content
        assert '"replicas":' in content
        assert '"api":' in content
        assert '"endpoints":' in content
        assert '"rateLimit":' in content
        assert '"features":' in content
        assert '"flags":' in content
        assert '"experimentalSettings":' in content

        # Verify nested objects
        assert '"credentials":' in content
        assert '"username": "admin"' in content

        # Verify arrays
        assert '"whitelist": ["127.0.0.1", "10.0.0.0/8"]' in content
        assert '"customThemes":' in content

        # Verify nested arrays with objects
        assert '{"name": "ocean", "primary": "#0077be"}' in content
        assert '{"name": "sunset", "primary": "#ff6b35"}' in content

    def test_parse_multiple_tools_with_json_file_edits(self, parser):
        """Stress test: Multiple tool calls including JSON file edits."""
        response = """
THOUGHT: I'll create a config file, read it back to verify, then update the database schema.

[
  {
    "tool_name": "write_file",
    "parameters": {
      "file_path": "app-config.json",
      "content": "{\\n  \\"app\\": {\\n    \\"name\\": \\"MyApp\\",\\n    \\"version\\": \\"1.0.0\\",\\n    \\"settings\\": {\\n      \\"theme\\": \\"dark\\",\\n      \\"language\\": \\"en\\",\\n      \\"features\\": [\\"auth\\", \\"analytics\\", \\"api\\"]\\n    }\\n  }\\n}"
    }
  },
  {
    "tool_name": "read_file",
    "parameters": {
      "file_path": "app-config.json"
    }
  },
  {
    "tool_name": "write_file",
    "parameters": {
      "file_path": "schema.json",
      "content": "{\\n  \\"tables\\": [\\n    {\\n      \\"name\\": \\"users\\",\\n      \\"columns\\": [\\n        {\\"name\\": \\"id\\", \\"type\\": \\"uuid\\", \\"primary\\": true},\\n        {\\"name\\": \\"email\\", \\"type\\": \\"string\\", \\"unique\\": true}\\n      ]\\n    }\\n  ]\\n}"
    }
  }
]
"""
        tool_calls = parser.parse(response)

        # Should parse all 3 tool calls despite complex nested JSON in content
        assert len(tool_calls) == 3

        # First tool: write_file with JSON content
        assert tool_calls[0].name == "write_file"
        assert tool_calls[0].parameters["file_path"] == "app-config.json"
        assert '"app":' in tool_calls[0].parameters["content"]
        assert '"settings":' in tool_calls[0].parameters["content"]
        assert '"features": ["auth", "analytics", "api"]' in tool_calls[0].parameters["content"]

        # Second tool: read_file
        assert tool_calls[1].name == "read_file"
        assert tool_calls[1].parameters["file_path"] == "app-config.json"

        # Third tool: write_file with schema JSON
        assert tool_calls[2].name == "write_file"
        assert tool_calls[2].parameters["file_path"] == "schema.json"
        assert '"tables":' in tool_calls[2].parameters["content"]
        assert '"columns":' in tool_calls[2].parameters["content"]
