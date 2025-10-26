"""
Agent Response Parser

Parses LLM responses to extract tool calls and completion signals.
Uses regex pattern matching to work with ANY model (not just function-calling models).

Supports multiple formats:
- XML-style: <tool_call><tool_name>...</tool_name><parameters>...</parameters></tool_call>
- JSON-style: {"tool_call": {"name": "...", "parameters": {...}}}
- Bash-style: ```bash\ncommand\n```
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """
    Represents a parsed tool call from the model's response.

    Attributes:
        name: Tool name
        parameters: Tool parameters as dict
        raw_text: Original text that was parsed
    """
    name: str
    parameters: Dict[str, Any]
    raw_text: str = ""


class AgentResponseParser:
    """
    Parses agent responses to extract tool calls and check for completion.

    Uses multiple regex patterns to maximize compatibility with different models.
    """

    # Pattern for XML-style tool calls (recommended format)
    XML_PATTERN = r'<tool_call>\s*<tool_name>(.*?)</tool_name>\s*<parameters>(.*?)</parameters>\s*</tool_call>'

    # Pattern for JSON-style tool calls (alternative format)
    JSON_PATTERN = r'\{"tool_call":\s*\{\s*"name":\s*"(.*?)",\s*"parameters":\s*(\{.*?\})\s*\}\}'

    # Pattern for bash code blocks (for backward compatibility)
    BASH_PATTERN = r'```bash\s*\n(.*?)\n```'

    # Completion signals
    COMPLETION_SIGNALS = [
        "TASK_COMPLETE",
        "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        "<task_complete>",
        "<!-- TASK COMPLETE -->"
    ]

    def __init__(self):
        logger.info("AgentResponseParser initialized")

    def parse(self, response: str) -> List[ToolCall]:
        """
        Parse a model response to extract all tool calls.

        Tries multiple formats in order of preference:
        1. XML-style tool calls (most explicit)
        2. JSON-style tool calls
        3. Bash code blocks (for simple command execution)

        Args:
            response: Model's text response

        Returns:
            List of ToolCall objects (empty if no tool calls found)
        """
        tool_calls = []

        # Try XML format first (most explicit and reliable)
        tool_calls.extend(self._parse_xml_format(response))

        # If no XML found, try JSON format
        if not tool_calls:
            tool_calls.extend(self._parse_json_format(response))

        # If still no tools found, check for bash blocks (simple commands)
        if not tool_calls:
            tool_calls.extend(self._parse_bash_format(response))

        if tool_calls:
            logger.info(f"Parsed {len(tool_calls)} tool call(s) from response")
        else:
            logger.debug("No tool calls found in response")

        return tool_calls

    def _parse_xml_format(self, response: str) -> List[ToolCall]:
        """Parse XML-style tool calls."""
        tool_calls = []
        matches = re.findall(self.XML_PATTERN, response, re.DOTALL | re.IGNORECASE)

        for tool_name, params_str in matches:
            try:
                tool_name = tool_name.strip()
                params_str = params_str.strip()

                # Parse JSON parameters with robust error handling
                parameters = self._parse_json_with_fixes(params_str)
                if parameters is None:
                    # If parsing failed, create an error tool call
                    logger.error(f"Failed to parse parameters for tool '{tool_name}': {params_str[:200]}")
                    tool_calls.append(ToolCall(
                        name="__parse_error__",
                        parameters={
                            "error": "JSON parsing failed",
                            "tool_name": tool_name,
                            "raw_params": params_str[:500],
                            "suggestion": "Ensure all string values have properly escaped quotes. Use \\\" for quotes inside strings."
                        },
                        raw_text=f"<tool_call><tool_name>{tool_name}</tool_name><parameters>{params_str[:200]}</parameters></tool_call>"
                    ))
                    continue

                tool_calls.append(ToolCall(
                    name=tool_name,
                    parameters=parameters,
                    raw_text=f"<tool_call><tool_name>{tool_name}</tool_name><parameters>{params_str}</parameters></tool_call>"
                ))

                logger.debug(f"Parsed XML tool call: {tool_name}")

            except Exception as e:
                logger.error(f"Failed to parse XML tool call: {e}", exc_info=True)
                continue

        return tool_calls

    def _parse_json_with_fixes(self, json_str: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to parse JSON with multiple fallback strategies for common errors.

        Args:
            json_str: JSON string to parse

        Returns:
            Parsed dict or None if all attempts fail
        """
        # Strategy 1: Try direct parsing
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Fix single quotes
        try:
            fixed = json_str.replace("'", '"')
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Try to fix unescaped quotes in string values
        try:
            # This regex finds quoted strings and escapes internal quotes
            # Pattern: "key": "value with "quotes" inside"
            # We need to be careful not to break already-escaped quotes
            fixed = self._fix_unescaped_quotes(json_str)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Strategy 4: Try fixing common newline issues
        try:
            fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # All strategies failed
        logger.warning(f"All JSON parsing strategies failed for: {json_str[:100]}")
        return None

    def _fix_unescaped_quotes(self, json_str: str) -> str:
        """
        Attempt to fix unescaped quotes inside JSON string values.

        This is a heuristic approach that tries to identify string values
        and escape quotes within them.
        """
        # Pattern to match: "key": "value"
        # We'll process each matched string value
        import re

        def escape_inner_quotes(match):
            """Escape quotes inside a JSON string value."""
            full_match = match.group(0)
            key_part = match.group(1)  # Everything before the value
            value_content = match.group(2)  # The value content

            # Escape any unescaped quotes in the value
            # Don't touch already escaped quotes
            escaped_value = re.sub(r'(?<!\\)"', r'\"', value_content)

            return f'{key_part}"{escaped_value}"'

        # Match pattern: "key": "value with possible "quotes""
        # This is complex and may not handle all edge cases perfectly
        pattern = r'("(?:[^"\\]|\\.)*?":\s*)"((?:[^"\\]|\\.)*)(")'

        try:
            # Try to fix the quotes
            fixed = json_str
            # Look for the pattern and replace
            # This is a simple heuristic - may need refinement
            return fixed
        except Exception as e:
            logger.debug(f"Quote fixing error: {e}")
            return json_str

    def _parse_json_format(self, response: str) -> List[ToolCall]:
        """Parse JSON-style tool calls."""
        tool_calls = []
        matches = re.findall(self.JSON_PATTERN, response, re.DOTALL)

        for tool_name, params_str in matches:
            try:
                tool_name = tool_name.strip()
                parameters = self._parse_json_with_fixes(params_str)

                if parameters is None:
                    logger.error(f"Failed to parse parameters for JSON tool '{tool_name}': {params_str[:200]}")
                    tool_calls.append(ToolCall(
                        name="__parse_error__",
                        parameters={
                            "error": "JSON parsing failed",
                            "tool_name": tool_name,
                            "raw_params": params_str[:500],
                            "suggestion": "Ensure all string values have properly escaped quotes. Use \\\" for quotes inside strings."
                        },
                        raw_text=f'{{"tool_call": {{"name": "{tool_name}", "parameters": {params_str[:200]}}}}}'
                    ))
                    continue

                tool_calls.append(ToolCall(
                    name=tool_name,
                    parameters=parameters,
                    raw_text=f'{{"tool_call": {{"name": "{tool_name}", "parameters": {params_str}}}}}'
                ))

                logger.debug(f"Parsed JSON tool call: {tool_name}")

            except Exception as e:
                logger.error(f"Failed to parse JSON tool call: {e}", exc_info=True)
                continue

        return tool_calls

    def _parse_bash_format(self, response: str) -> List[ToolCall]:
        """
        Parse bash code blocks as execute_command tool calls.

        This provides backward compatibility and simple command execution.
        """
        tool_calls = []
        matches = re.findall(self.BASH_PATTERN, response, re.DOTALL)

        for command in matches:
            command = command.strip()
            if not command:
                continue

            tool_calls.append(ToolCall(
                name="execute_command",
                parameters={"command": command},
                raw_text=f"```bash\n{command}\n```"
            ))

            logger.debug(f"Parsed bash command as tool call: {command[:50]}...")

        return tool_calls

    def is_complete(self, response: str) -> bool:
        """
        Check if the response indicates task completion.

        Args:
            response: Model's text response

        Returns:
            True if task is complete, False otherwise
        """
        response_upper = response.upper()
        for signal in self.COMPLETION_SIGNALS:
            if signal.upper() in response_upper:
                logger.info(f"Task completion signal found: {signal}")
                return True

        return False

    def extract_thought(self, response: str) -> Optional[str]:
        """
        Extract the THOUGHT section from the response.

        Many models are trained to output their reasoning as THOUGHT: ...

        Args:
            response: Model's text response

        Returns:
            The thought text if found, None otherwise
        """
        # Pattern: THOUGHT: text (until next section or tool call)
        pattern = r'THOUGHT:\s*(.+?)(?=\n(?:EXPLANATION:|<tool_call>|```|$))'
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)

        if match:
            thought = match.group(1).strip()
            logger.debug(f"Extracted thought: {thought[:100]}...")
            return thought

        return None

    def extract_explanation(self, response: str) -> Optional[str]:
        """
        Extract the EXPLANATION section from the response.

        Args:
            response: Model's text response

        Returns:
            The explanation text if found, None otherwise
        """
        pattern = r'EXPLANATION:\s*(.+?)(?=\n(?:THOUGHT:|<tool_call>|```|$))'
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)

        if match:
            explanation = match.group(1).strip()
            logger.debug(f"Extracted explanation: {explanation[:100]}...")
            return explanation

        return None

    def get_conversational_text(self, response: str) -> str:
        """
        Extract the conversational/explanatory text from the response.

        Removes tool calls and returns just the text that should be shown to the user.

        Args:
            response: Model's text response

        Returns:
            Clean text without tool call syntax
        """
        # Remove XML tool calls
        text = re.sub(self.XML_PATTERN, '', response, flags=re.DOTALL | re.IGNORECASE)

        # Remove JSON tool calls
        text = re.sub(self.JSON_PATTERN, '', text, flags=re.DOTALL)

        # Remove bash blocks
        text = re.sub(self.BASH_PATTERN, '', text, flags=re.DOTALL)

        # Remove completion signals
        for signal in self.COMPLETION_SIGNALS:
            # Case-insensitive removal
            text = re.sub(re.escape(signal), '', text, flags=re.IGNORECASE)

        # Remove THOUGHT: and EXPLANATION: prefixes
        text = re.sub(r'^\s*THOUGHT:\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r'^\s*EXPLANATION:\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)

        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()

        return text
