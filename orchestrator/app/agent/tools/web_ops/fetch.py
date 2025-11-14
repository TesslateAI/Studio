"""
Web Fetch and Search Tools

Tools for accessing external web content.

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError, httpx.RequestError)
- Exponential backoff: 1s → 2s → 4s (up to 3 attempts)
- Does NOT retry on HTTP errors (4xx, 5xx) - those fail immediately
"""

import logging
from typing import Dict, Any
import httpx
from urllib.parse import quote_plus

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def web_fetch_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch content from a URL.

    Useful for reading documentation, APIs, or other web resources.

    Retry behavior:
    - Automatically retries on ConnectionError, TimeoutError
    - Up to 3 attempts with exponential backoff (1s, 2s, 4s)
    - HTTP errors (404, 500, etc.) fail immediately without retry

    Args:
        params: {
            url: str,  # URL to fetch
            timeout: int  # Optional timeout in seconds (default: 10)
        }
        context: {}

    Returns:
        Dict with web content
    """
    url = params.get("url")
    timeout = params.get("timeout", 10)

    if not url:
        raise ValueError("url parameter is required")

    # Basic validation
    if not url.startswith(("http://", "https://")):
        return error_output(
            message="Invalid URL: must start with http:// or https://",
            suggestion="Check your URL format",
            url=url
        )

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Get content
            content = response.text
            content_type = response.headers.get("content-type", "")

            # Truncate very large responses
            max_length = 50000  # ~50KB of text
            truncated = len(content) > max_length
            if truncated:
                content = content[:max_length] + "\n\n... (truncated)"

            return success_output(
                message=f"Fetched {len(content)} characters from '{url}'",
                url=url,
                content=content,
                details={
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "truncated": truncated,
                    "size_bytes": len(content)
                }
            )

    except httpx.TimeoutException:
        return error_output(
            message=f"Request to '{url}' timed out after {timeout} seconds",
            suggestion="Try increasing the timeout or check if the URL is accessible",
            url=url
        )
    except httpx.HTTPStatusError as e:
        return error_output(
            message=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}",
            suggestion="Check if the URL is correct and accessible",
            url=url,
            details={"status_code": e.response.status_code}
        )
    except Exception as e:
        return error_output(
            message=f"Failed to fetch '{url}': {str(e)}",
            suggestion="Check if the URL is valid and accessible",
            url=url,
            details={"error": str(e)}
        )


def register_web_tools(registry):
    """Register web fetch tool."""

    registry.register(Tool(
        name="web_fetch",
        description="Fetch content from a URL. Useful for reading documentation, API responses, or other web resources. Returns up to 50KB of content.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch (must start with http:// or https://)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds (default: 10)",
                    "default": 10
                }
            },
            "required": ["url"]
        },
        executor=web_fetch_tool,
        category=ToolCategory.PROJECT,  # Using PROJECT since there's no WEB category
        examples=[
            '{"tool_name": "web_fetch", "parameters": {"url": "https://example.com/api/docs"}}',
            '{"tool_name": "web_fetch", "parameters": {"url": "https://stackoverflow.com/questions/12345", "timeout": 15}}'
        ]
    ))

    logger.info("Registered 1 web tool")
