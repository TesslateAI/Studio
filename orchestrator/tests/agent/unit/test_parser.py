"""
Unit tests for AgentResponseParser.

Tests tool call parsing, completion detection, thought extraction,
and various response formats (XML, JSON, bash).
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

    def test_parse_xml_single_tool_call(self, parser):
        """Test parsing a single XML-format tool call."""
        response = """
THOUGHT: I need to read the App.jsx file.

<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "src/App.jsx"}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].parameters == {"file_path": "src/App.jsx"}

    def test_parse_xml_multiple_tool_calls(self, parser):
        """Test parsing multiple XML-format tool calls."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Header.jsx", "content": "import React from 'react';"}
</parameters>
</tool_call>

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Footer.jsx", "content": "import React from 'react';"}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 2
        assert tool_calls[0].name == "write_file"
        assert tool_calls[0].parameters["file_path"] == "src/Header.jsx"
        assert tool_calls[1].name == "write_file"
        assert tool_calls[1].parameters["file_path"] == "src/Footer.jsx"

    def test_parse_bash_code_block(self, parser):
        """Test parsing bash code blocks as tool calls."""
        response = """
I'll run this command:

```bash
ls -la src/
```
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "execute_command"
        assert tool_calls[0].parameters == {"command": "ls -la src/"}

    def test_parse_no_tool_calls(self, parser):
        """Test parsing response with no tool calls."""
        response = "This is just a conversational response with no tools."

        tool_calls = parser.parse(response)

        assert len(tool_calls) == 0

    def test_parse_json_with_escaped_quotes(self, parser):
        """Test parsing JSON parameters with escaped quotes."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/App.jsx", "content": "const message = \\"Hello World\\";"}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert '"Hello World"' in tool_calls[0].parameters["content"]

    def test_parse_error_invalid_json(self, parser):
        """Test handling of invalid JSON in parameters."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "test.js", "content": "broken json with "unescaped quotes"}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        # Should create a parse error tool call
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "__parse_error__"
        assert "tool_name" in tool_calls[0].parameters
        assert tool_calls[0].parameters["tool_name"] == "write_file"

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

<tool_call>
<tool_name>bash_exec</tool_name>
<parameters>
{"command": "ls src/"}
</parameters>
</tool_call>
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

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Button.jsx", "content": "..."}
</parameters>
</tool_call>

The button component has been created successfully!
"""
        conversational = parser.get_conversational_text(response)

        assert "I'll create a new button component" in conversational
        assert "successfully" in conversational
        assert "<tool_call>" not in conversational
        assert "write_file" not in conversational

    def test_parse_with_whitespace_variations(self, parser):
        """Test parsing handles whitespace variations in tool calls."""
        response = """
<tool_call>
  <tool_name>  read_file  </tool_name>
  <parameters>
  {"file_path": "test.js"}
  </parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].parameters == {"file_path": "test.js"}

    def test_parse_case_insensitive_xml_tags(self, parser):
        """Test that XML parsing is case-insensitive."""
        response = """
<TOOL_CALL>
<TOOL_NAME>read_file</TOOL_NAME>
<PARAMETERS>
{"file_path": "test.js"}
</PARAMETERS>
</TOOL_CALL>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"

    def test_parse_multiline_json_parameters(self, parser):
        """Test parsing multi-line JSON parameters."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{
  "file_path": "src/config.js",
  "content": "const config = {\\n  api: 'https://api.example.com',\\n  timeout: 5000\\n};"
}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "write_file"
        assert "config" in tool_calls[0].parameters["content"]

    def test_parse_empty_parameters(self, parser):
        """Test parsing tool call with empty parameters object."""
        response = """
<tool_call>
<tool_name>get_project_info</tool_name>
<parameters>
{}
</parameters>
</tool_call>
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

<tool_call>
<tool_name>patch_file</tool_name>
<parameters>
{"file_path": "src/Button.jsx", "search": "bg-blue-500", "replace": "bg-green-500"}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)
        explanation = parser.extract_explanation(response)

        assert len(tool_calls) == 1
        assert explanation is not None
        assert "better visibility" in explanation

    def test_parse_mixed_formats(self, parser):
        """Test that parser prefers XML over bash when both present."""
        response = """
<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "test.js"}
</parameters>
</tool_call>

```bash
ls -la
```
"""
        tool_calls = parser.parse(response)

        # Should only parse XML (preferred format)
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"

    @pytest.mark.parametrize("invalid_json,expected_error", [
        ('{"key": value}', "JSON parsing failed"),  # Missing quotes
        ('{"key": "value"', "JSON parsing failed"),  # Missing closing brace
        ('{key: "value"}', "JSON parsing failed"),  # Unquoted key
    ])
    def test_parse_various_json_errors(self, parser, invalid_json, expected_error):
        """Test handling of various JSON syntax errors."""
        response = f"""
<tool_call>
<tool_name>test_tool</tool_name>
<parameters>
{invalid_json}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "__parse_error__"
        assert expected_error in tool_calls[0].parameters["error"]

    def test_tool_call_dataclass(self):
        """Test ToolCall dataclass attributes."""
        tool_call = ToolCall(
            name="test_tool",
            parameters={"param1": "value1"},
            raw_text="<tool_call>...</tool_call>"
        )

        assert tool_call.name == "test_tool"
        assert tool_call.parameters["param1"] == "value1"
        assert tool_call.raw_text == "<tool_call>...</tool_call>"

    def test_parse_nested_json_objects(self, parser):
        """Test parsing tool calls with nested JSON objects."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{
  "file_path": "config.json",
  "content": "{\\"database\\": {\\"host\\": \\"localhost\\", \\"port\\": 5432}}"
}
</parameters>
</tool_call>
"""
        tool_calls = parser.parse(response)

        assert len(tool_calls) == 1
        assert "database" in tool_calls[0].parameters["content"]
        assert "localhost" in tool_calls[0].parameters["content"]

    def test_parse_unicode_content(self, parser):
        """Test parsing tool calls with Unicode characters."""
        response = """
<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "test.txt", "content": "Hello 世界 🌍"}
</parameters>
</tool_call>
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

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "index.html", "content": "..."}
</parameters>
</tool_call>

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
        assert "<tool_call>" not in conversational
        assert "TASK_COMPLETE" not in conversational
