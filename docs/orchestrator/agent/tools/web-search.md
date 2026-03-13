# Web Search Tool

The `web_search` tool enables agents to search the web for current information using a provider abstraction with automatic fallback.

## Tools Overview

| Tool | Purpose | Parameters |
|------|---------|------------|
| `web_search` | Search the web for current information | query, max_results, detailed |

## web_search

**File**: `orchestrator/app/agent/tools/web_ops/search.py`

Search the web and return structured results with titles, URLs, and snippets. Optionally fetch full page content for the top 3 results.

### Parameters

```python
{
    "query": "React 19 new features",        # Required: search query
    "max_results": 5,                         # Optional, default 5, max 10
    "detailed": false                         # Optional, default false (fetch page content for top 3)
}
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "web_search",
    "result": {
        "message": "Found 5 results for 'React 19 new features'",
        "results": [
            {
                "title": "React 19 Release Notes",
                "url": "https://react.dev/blog/2024/12/05/react-19",
                "snippet": "React 19 introduces new features..."
            },
            # ... more results
        ]
    }
}

# With detailed=true, top 3 results include "content" field:
{
    "title": "React 19 Release Notes",
    "url": "https://react.dev/blog/2024/12/05/react-19",
    "snippet": "React 19 introduces...",
    "content": "<full page content, truncated at 15000 chars>"
}
```

## Search Provider Abstraction

**File**: `orchestrator/app/agent/tools/web_ops/providers.py`

The search system uses a provider abstraction with automatic fallback based on available API keys.

### Provider Priority

| Priority | Provider | API Key Required | Quality |
|----------|----------|-----------------|---------|
| 1 | Tavily | `TAVILY_API_KEY` | Best quality, includes raw content |
| 2 | Brave Search | `BRAVE_SEARCH_API_KEY` | Good alternative |
| 3 | DuckDuckGo | None (always available) | No API key needed |

### Architecture

```
┌─────────────────────────────────────────┐
│        get_search_provider()            │
│   Auto-selects best available provider  │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────┐                        │
│  │SearchProvider│ (ABC)                  │
│  │  search()   │                        │
│  └──────┬──────┘                        │
│         │                               │
│   ┌─────┴──────┬──────────┐             │
│   │            │          │             │
│ ┌─▼──────┐ ┌──▼─────┐ ┌──▼──────────┐  │
│ │Tavily  │ │ Brave  │ │ DuckDuckGo │  │
│ │Provider│ │Provider│ │  Provider   │  │
│ └────────┘ └────────┘ └────────────┘  │
│                                         │
└─────────────────────────────────────────┘
```

All providers return standardized `SearchResult` objects:

```python
@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str | None = None  # Only Tavily provides raw content
```

### Configuration (config.py)

| Setting | Default | Purpose |
|---------|---------|---------|
| `web_search_provider` | `"tavily"` | Preferred provider (tavily, brave, duckduckgo) |
| `tavily_api_key` | `""` | Tavily API key |
| `brave_search_api_key` | `""` | Brave Search API key |
| `web_search_max_results` | `5` | Default max results |
| `web_search_timeout` | `15` | Search timeout in seconds |

### Adding a New Search Provider

1. Create a class that inherits from `SearchProvider` in `providers.py`
2. Implement the `search()` method returning `list[SearchResult]`
3. Add the provider to `get_search_provider()` fallback chain
4. Add any required API key to `config.py`

```python
class MyProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        # Call your search API
        results = await call_api(query, max_results)
        return [SearchResult(title=r.title, url=r.url, snippet=r.snippet) for r in results]
```

## Parallel Execution

`web_search` is included in the `PARALLEL_TOOLS` set, meaning it can be executed concurrently with other parallel-safe tools during agent iterations. This avoids blocking the agent while waiting for search results.

## Related Documentation

- [shell-ops.md](./shell-ops.md) - Shell operation tools
- [file-ops.md](./file-ops.md) - File operation tools
- [registry.md](./registry.md) - Tool registry internals
