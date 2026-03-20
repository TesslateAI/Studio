"""
Web Search Providers

Provider abstraction with automatic fallback:
- Tavily (if API key configured) — best quality
- Brave Search (if API key configured) — good alternative
- DuckDuckGo (always available) — no API key needed

Each provider returns standardized SearchResult objects.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Standardized search result across all providers."""
    title: str
    url: str
    snippet: str
    content: str | None = None


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute a search query and return results."""
        ...


class TavilyProvider(SearchProvider):
    """Search provider using Tavily API (best quality, requires API key)."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=self.api_key)
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )

        results = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:500],
                    content=item.get("raw_content"),
                )
            )
        return results


class BraveSearchProvider(SearchProvider):
    """Search provider using Brave Search API (requires API key)."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", "")[:500],
                )
            )
        return results


class DuckDuckGoProvider(SearchProvider):
    """Search provider using DuckDuckGo (no API key required, always available)."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        import asyncio

        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        search_results = await asyncio.to_thread(_search)
        results = []
        for item in search_results:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", "")[:500],
                )
            )
        return results


def get_search_provider() -> SearchProvider:
    """
    Auto-select the best available search provider.

    Priority: Tavily (if key set) -> Brave (if key set) -> DuckDuckGo (always works)
    """
    from ....config import get_settings

    settings = get_settings()

    if settings.tavily_api_key:
        logger.debug("Using Tavily search provider")
        return TavilyProvider(api_key=settings.tavily_api_key)

    if settings.brave_search_api_key:
        logger.debug("Using Brave search provider")
        return BraveSearchProvider(api_key=settings.brave_search_api_key)

    logger.debug("Using DuckDuckGo search provider (no API key required)")
    return DuckDuckGoProvider()
