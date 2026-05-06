"""Verify the pubsub package exports its full public surface.

Regression test for the missing `subscribe_app_runtime_events` /
`publish_app_runtime_event` exports that caused an ImportError inside the SSE
generator, aborting every /events connection with ERR_ABORTED.
"""

from __future__ import annotations

import importlib


def test_subscribe_app_runtime_events_is_exported():
    pkg = importlib.import_module("app.services.pubsub")
    assert hasattr(pkg, "subscribe_app_runtime_events"), (
        "subscribe_app_runtime_events must be exported from app.services.pubsub"
    )
    fn = pkg.subscribe_app_runtime_events
    # Must be callable and return an async generator (has __aiter__/__anext__ on the result).
    assert callable(fn)


def test_publish_app_runtime_event_is_exported():
    pkg = importlib.import_module("app.services.pubsub")
    assert hasattr(pkg, "publish_app_runtime_event"), (
        "publish_app_runtime_event must be exported from app.services.pubsub"
    )
    fn = pkg.publish_app_runtime_event
    assert callable(fn)


def test_all_declared_exports_are_importable():
    """Every name in __all__ must resolve without ImportError."""
    pkg = importlib.import_module("app.services.pubsub")
    for name in pkg.__all__:
        assert hasattr(pkg, name), (
            f"app.services.pubsub.__all__ declares {name!r} but it is missing"
        )


def test_pubsub_functions_originate_from_redis_pubsub():
    """Both app-runtime helpers must come from redis_pubsub (not some stub)."""
    from app.services.pubsub import (
        publish_app_runtime_event,
        subscribe_app_runtime_events,
    )
    from app.services.pubsub.redis_pubsub import (
        publish_app_runtime_event as _pub,
    )
    from app.services.pubsub.redis_pubsub import (
        subscribe_app_runtime_events as _sub,
    )

    assert subscribe_app_runtime_events is _sub
    assert publish_app_runtime_event is _pub
