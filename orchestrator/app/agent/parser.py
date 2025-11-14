"""
Agent Response Parser

Parses LLM responses to extract tool calls and completion signals.
Uses JSON parsing to work with ANY model (not just function-calling models).

Parses pure JSON tool calls:
- Single tool: {"tool_name": "...", "parameters": {...}}
- Multiple tools: [{"tool_name": "...", "parameters": {...}}, ...]
- Parameters are JSON objects with tool-specific fields
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

    Parses pure JSON tool calls as instructed in the system prompt.
    """

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

        Parses pure JSON tool calls as instructed in the system prompt.
        Supports both single object and array formats.

        Args:
            response: Model's text response

        Returns:
            List of ToolCall objects (empty if no tool calls found)
        """
        tool_calls = self._parse_json_format(response)

        if tool_calls:
            logger.info(f"Parsed {len(tool_calls)} tool call(s) from response")
        else:
            logger.debug("No tool calls found in response")

        return tool_calls

    def _parse_json_format(self, response: str) -> List[ToolCall]:
        """
        Parse pure JSON tool calls from response.

        Supports two formats:
        1. Single tool call: {"tool_name": "...", "parameters": {...}}
        2. Multiple tool calls: [{"tool_name": "...", "parameters": {...}}, ...]

        Uses a balanced bracket approach to extract JSON blocks robustly.
        """
        tool_calls = []

        # Extract all potential JSON blocks (arrays and objects)
        json_blocks = self._extract_json_blocks(response)

        for block in json_blocks:
            try:
                parsed = self._parse_json_with_fixes(block)

                if parsed and isinstance(parsed, list):
                    # It's an array of tool calls
                    for item in parsed:
                        if isinstance(item, dict) and "tool_name" in item:
                            tool_name = item.get("tool_name", "").strip()
                            parameters = item.get("parameters", {})

                            if tool_name:
                                tool_calls.append(ToolCall(
                                    name=tool_name,
                                    parameters=parameters if isinstance(parameters, dict) else {},
                                    raw_text=block[:200]
                                ))
                                logger.debug(f"Parsed JSON tool call from array: {tool_name}")

                elif parsed and isinstance(parsed, dict) and "tool_name" in parsed:
                    # It's a single tool call
                    tool_name = parsed.get("tool_name", "").strip()
                    parameters = parsed.get("parameters", {})

                    if tool_name:
                        tool_calls.append(ToolCall(
                            name=tool_name,
                            parameters=parameters if isinstance(parameters, dict) else {},
                            raw_text=block[:200]
                        ))
                        logger.debug(f"Parsed JSON tool call from object: {tool_name}")
            except Exception as e:
                logger.debug(f"Failed to parse JSON block: {e}")
                continue

        return tool_calls

    def _extract_json_blocks(self, text: str) -> List[str]:
        """
        Extract all JSON-like blocks (objects and arrays) from text using balanced bracket matching.

        This is more robust than regex for nested structures.

        Returns:
            List of JSON string blocks
        """
        blocks = []
        i = 0

        while i < len(text):
            # Look for start of JSON block ('{' or '[')
            if text[i] in ['{', '[']:
                start_char = text[i]
                end_char = '}' if start_char == '{' else ']'

                # Find matching closing bracket using balanced counting
                start = i
                depth = 0
                in_string = False
                escape_next = False

                while i < len(text):
                    char = text[i]

                    # Handle string escape sequences
                    if escape_next:
                        escape_next = False
                        i += 1
                        continue

                    if char == '\\':
                        escape_next = True
                        i += 1
                        continue

                    # Toggle string state
                    if char == '"':
                        in_string = not in_string
                        i += 1
                        continue

                    # Only count brackets outside of strings
                    if not in_string:
                        if char == start_char:
                            depth += 1
                        elif char == end_char:
                            depth -= 1

                            # Found matching bracket
                            if depth == 0:
                                block = text[start:i+1]
                                blocks.append(block)
                                break

                    i += 1
            else:
                i += 1

        return blocks

    def _parse_json_with_fixes(self, json_str: str) -> Optional[Any]:
        """
        Attempt to parse JSON with multiple fallback strategies for common errors.

        Args:
            json_str: JSON string to parse

        Returns:
            Parsed object (dict, list, etc.) or None if all attempts fail
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
        pattern = r'THOUGHT:\s*(.+?)(?=\n(?:EXPLANATION:|<tool_call>|$))'
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
        pattern = r'EXPLANATION:\s*(.+?)(?=\n(?:THOUGHT:|<tool_call>|$))'
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)

        if match:
            explanation = match.group(1).strip()
            logger.debug(f"Extracted explanation: {explanation[:100]}...")
            return explanation

        return None

    def get_conversational_text(self, response: str) -> str:
        """
        Extract the conversational/explanatory text from the response.

        Removes tool calls (JSON objects/arrays) and returns just the text that should be shown to the user.

        Args:
            response: Model's text response

        Returns:
            Clean text without tool call syntax
        """
        # Remove JSON tool calls (arrays first, then objects)
        # Remove arrays: [ ... ]
        text = re.sub(r'\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*\]', '', response, flags=re.DOTALL)
        # Remove objects: { ... }
        text = re.sub(r'\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}', '', text, flags=re.DOTALL)

        # Remove <think> and <thinking> tags (internal reasoning from models)
        # First remove complete pairs
        text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Then remove orphaned closing tags along with everything before them
        # This handles cases where the opening tag was truncated/missing
        text = re.sub(r'^.*?</think(?:ing)?>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Finally remove any remaining orphaned opening tags
        text = re.sub(r'<think(?:ing)?>', '', text, flags=re.IGNORECASE)

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
