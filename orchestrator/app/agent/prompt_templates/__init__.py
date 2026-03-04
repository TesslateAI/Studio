"""
Prompt Templates for TesslateAgent

Contains system prompts, plan mode guidance, and subagent prompts
adapted for Tesslate Studio's container-based, async architecture.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Template variable mappings for Tesslate tools
TEMPLATE_VARS = {
    "${GLOB_TOOL_NAME}": "bash_exec",
    "${GREP_TOOL_NAME}": "bash_exec",
    "${READ_TOOL_NAME}": "read_file",
    "${BASH_TOOL_NAME}": "bash_exec",
    "${EDIT_TOOL_NAME}": "apply_patch",
    "${WRITE_TOOL_NAME}": "write_file",
    "${UPDATE_PLAN_TOOL_NAME}": "update_plan",
    "${INVOKE_SUBAGENT_TOOL_NAME}": "invoke_subagent",
    "${SAVE_PLAN_TOOL_NAME}": "save_plan",
    "${WEB_SEARCH_TOOL_NAME}": "web_fetch",
    "${AGENT_NAME}": "Tesslate Agent",
}


def resolve_template(content: str, extra_vars: dict | None = None) -> str:
    """
    Resolve template variables in prompt content.

    Args:
        content: Template content with ${VAR} placeholders
        extra_vars: Additional variables to resolve

    Returns:
        Content with variables resolved
    """
    result = content

    for var, value in TEMPLATE_VARS.items():
        result = result.replace(var, value)

    if extra_vars:
        for var, value in extra_vars.items():
            result = result.replace(var, value)

    return result


def load_prompt(prompt_name: str, subdir: str | None = None) -> str:
    """
    Load and resolve a prompt template from the prompts directory.

    Args:
        prompt_name: Name of prompt file (without .md extension)
        subdir: Optional subdirectory (e.g., "subagent")

    Returns:
        Resolved prompt content
    """
    prompts_dir = Path(__file__).parent

    if subdir:
        path = prompts_dir / subdir / f"{prompt_name}.md"
    else:
        path = prompts_dir / f"{prompt_name}.md"

    if not path.exists():
        logger.warning(f"Prompt template not found: {path}")
        return ""

    content = path.read_text(encoding="utf-8")
    return resolve_template(content)
