"""
Capability gating decorator.

Every protocol endpoint declares the capability it implements. The decorator
checks the active capability set per request — if the capability is in
`DISABLED_CAPABILITIES`, the request short-circuits with a typed JSON envelope:

```http
HTTP/1.1 501 Not Implemented
Content-Type: application/json
X-Tesslate-Hub-Id: ...

{"error": "unsupported_capability", "capability": "...", "hub_id": "...", "details": "..."}
```

The decorator is intentionally tiny — it adds a `capability` attribute to the
underlying handler so the OpenAPI schema and tests can introspect it.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi.responses import JSONResponse

from ..config import get_settings
from .hub_id import resolve_hub_id

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def requires_capability(capability: str, *, details: str | None = None) -> Callable[[F], F]:
    """Mark an endpoint as gated behind a capability flag."""

    def decorator(handler: F) -> F:
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("requires_capability only wraps async handlers")

        @functools.wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any):
            settings = get_settings()
            if capability not in settings.capabilities:
                hub_id = resolve_hub_id(settings)
                payload = {
                    "error": "unsupported_capability",
                    "capability": capability,
                    "hub_id": hub_id,
                    "details": details or f"This hub does not implement {capability}.",
                }
                return JSONResponse(payload, status_code=501)
            return await handler(*args, **kwargs)

        wrapper.capability = capability  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
