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

                # Parse JSON parameters
                try:
                    parameters = json.loads(params_str)
                except json.JSONDecodeError:
                    # Try to fix common JSON errors
                    params_str = params_str.replace("'", '"')  # Single quotes to double
                    parameters = json.loads(params_str)

                tool_calls.append(ToolCall(
                    name=tool_name,
                    parameters=parameters,
                    raw_text=f"<tool_call><tool_name>{tool_name}</tool_name><parameters>{params_str}</parameters></tool_call>"
                ))

                logger.debug(f"Parsed XML tool call: {tool_name}")

            except Exception as e:
                logger.warning(f"Failed to parse XML tool call: {e}")
                continue

        return tool_calls

    def _parse_json_format(self, response: str) -> List[ToolCall]:
        """Parse JSON-style tool calls."""
        tool_calls = []
        matches = re.findall(self.JSON_PATTERN, response, re.DOTALL)

        for tool_name, params_str in matches:
            try:
                tool_name = tool_name.strip()
                parameters = json.loads(params_str)

                tool_calls.append(ToolCall(
                    name=tool_name,
                    parameters=parameters,
                    raw_text=f'{{"tool_call": {{"name": "{tool_name}", "parameters": {params_str}}}}}'
                ))

                logger.debug(f"Parsed JSON tool call: {tool_name}")

            except Exception as e:
                logger.warning(f"Failed to parse JSON tool call: {e}")
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

        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()

        return text
