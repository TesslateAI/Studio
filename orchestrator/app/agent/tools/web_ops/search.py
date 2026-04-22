"""
Web Search Tool

Allows agents to search the web for current information.
Returns structured results with titles, URLs, and snippets.

Retry Strategy:
- Automatically retries on transient failures (ConnectionError, TimeoutError)
- Exponential backoff: 1s -> 2s -> 4s (up to 3 attempts)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def web_search_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Search the web for current information.

    Args:
        params: {
            query: str,  # Search query (required)
            max_results: int,  # Max results to return (default: 5)
            detailed: bool  # Fetch page content for top 3 results (default: False)
        }
        context: Standard tool execution context (unused).

    Returns:
        Dict with search results.
    """
    query = params.get("query")
    max_results = params.get("max_results", 5)
    detailed = params.get("detailed", False)

    if not query:
        raise ValueError("query parameter is required")

    if not query.strip():
        return error_output(
            message="Search query cannot be empty",
            suggestion="Provide a meaningful search query",
        )

    # Cap max_results to prevent abuse
    max_results = min(max_results, 10)

    from ..web_ops.providers import get_search_provider

    provider = get_search_provider()
    results = await provider.search(query, max_results)

    if not results:
        return success_output(
            message=f"No results found for '{query}'",
            results=[],
        )

    # Optionally fetch page content for top results
    if detailed and results:
        for result in results[:3]:
            if not result.content:
                result.content = await _fetch_page_content(result.url)

    # Format results for output
    formatted_results = []
    for r in results:
        entry = {
            "title": r.title,
            "url": r.url,
            "snippet": r.snippet,
        }
        if r.content:
            entry["content"] = r.content
        formatted_results.append(entry)

    return success_output(
        message=f"Found {len(results)} results for '{query}'",
        results=formatted_results,
    )


async def _fetch_page_content(url: str, max_length: int = 15000) -> str | None:
    """Fetch and truncate page content for detailed search results."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... (truncated)"
            return content
    except Exception as e:
        logger.debug(f"Failed to fetch content from {url}: {e}")
        return None


def register_web_search_tool(registry) -> None:
    """Register the web_search tool."""

    registry.register(
        Tool(
            name="web_search",
            description=(
                "Search the web for current information. Returns titles, URLs, "
                "and snippets. Set 'detailed' to true to also fetch page content "
                "for top 3 results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5, max: 10)",
                        "default": 5,
                    },
                    "detailed": {
                        "type": "boolean",
                        "description": (
                            "If true, fetch full page content for the top 3 "
                            "results (slower but more detailed)"
                        ),
                        "default": False,
                    },
                },
                "required": ["query"],
            },
            executor=web_search_tool,
            category=ToolCategory.WEB,
            examples=[
                '{"tool_name": "web_search", "parameters": {"query": "React 19 new features"}}',
                '{"tool_name": "web_search", "parameters": {"query": "FastAPI websocket tutorial", "max_results": 3, "detailed": true}}',
            ],
        )
    )

    logger.info("Registered web_search tool")
