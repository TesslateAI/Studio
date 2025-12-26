"""
Factory for creating view-scoped tool registries.

This module provides factory functions to create ViewScopedToolRegistry instances
with appropriate providers based on view context. It supports dynamic provider
registration for extensibility.
"""

import logging
from typing import Dict, Type, Optional, List
from uuid import UUID

from .view_context import ViewContext
from .view_scoped_registry import ViewScopedToolRegistry
from .providers.base import AbstractToolProvider
from .registry import ToolRegistry, create_scoped_tool_registry

logger = logging.getLogger(__name__)

# Registry of provider classes by view context
_PROVIDER_CLASSES: Dict[ViewContext, Type[AbstractToolProvider]] = {}

# Cached view-scoped registries (by view context)
_REGISTRY_CACHE: Dict[ViewContext, ViewScopedToolRegistry] = {}


def register_provider_class(
    view: ViewContext,
    provider_cls: Type[AbstractToolProvider]
):
    """
    Register a tool provider class for a view context.

    This allows plugins/extensions to register custom providers
    for new views or override existing ones.

    Args:
        view: ViewContext the provider serves
        provider_cls: Class implementing AbstractToolProvider
    """
    _PROVIDER_CLASSES[view] = provider_cls
    # Invalidate cached registry for this view
    _REGISTRY_CACHE.pop(view, None)
    logger.info(f"Registered provider class {provider_cls.__name__} for {view.value}")


def get_registered_providers() -> Dict[ViewContext, Type[AbstractToolProvider]]:
    """
    Get all registered provider classes.

    Returns:
        Dict mapping ViewContext to provider class
    """
    return _PROVIDER_CLASSES.copy()


def _ensure_providers_registered():
    """
    Ensure all built-in providers are registered.

    Called lazily to avoid import cycles.
    """
    if ViewContext.GRAPH not in _PROVIDER_CLASSES:
        try:
            from .providers.graph_provider import GraphToolProvider
            register_provider_class(ViewContext.GRAPH, GraphToolProvider)
        except ImportError:
            logger.warning("GraphToolProvider not available")


def create_view_scoped_registry(
    view_context: ViewContext,
    project_id: Optional[UUID] = None,
    container_id: Optional[UUID] = None,
    base_tool_names: Optional[List[str]] = None,
    use_cache: bool = True
) -> ViewScopedToolRegistry:
    """
    Factory function to create a view-scoped tool registry.

    Creates a registry with:
    1. Base tools (file ops, shell, etc.) - filtered based on view context
    2. View-specific tools from the appropriate provider

    Args:
        view_context: The current UI view
        project_id: Project UUID (for context validation)
        container_id: Optional container UUID (for container-scoped ops)
        base_tool_names: Optional list of base tool names to include
                        If None, all base tools are included (with view-specific filtering)
        use_cache: Whether to use cached registry (default True)

    Returns:
        Configured ViewScopedToolRegistry
    """
    _ensure_providers_registered()

    # Tools to exclude in graph view - agent must use graph_shell_exec with container_id
    # In graph view, there's no "current container" so base shell tools don't make sense
    GRAPH_EXCLUDED_TOOLS = {
        'bash_exec',      # Use graph_shell_exec instead
        'shell_exec',     # Use graph_shell_exec instead
        'shell_open',     # Use graph_shell_open instead
        'shell_close',    # Use graph_shell_close instead
    }

    # Check cache first (only for standard configurations)
    cache_key = (view_context, tuple(sorted(base_tool_names)) if base_tool_names else None)
    if use_cache and base_tool_names is None and view_context in _REGISTRY_CACHE:
        registry = _REGISTRY_CACHE[view_context]
        registry.set_active_view(view_context)
        return registry

    # Create base registry with core tools
    if base_tool_names:
        # Apply view-specific filtering
        if view_context == ViewContext.GRAPH:
            base_tool_names = [t for t in base_tool_names if t not in GRAPH_EXCLUDED_TOOLS]
        base_registry = create_scoped_tool_registry(base_tool_names)
    else:
        from .registry import get_tool_registry
        full_registry = get_tool_registry()
        # For graph view, filter out shell tools from base registry
        if view_context == ViewContext.GRAPH:
            # Create a filtered registry without shell tools
            filtered_tools = [t.name for t in full_registry.list_tools() if t.name not in GRAPH_EXCLUDED_TOOLS]
            base_registry = create_scoped_tool_registry(filtered_tools)
            logger.info(f"[GRAPH VIEW] Excluded base shell tools: {GRAPH_EXCLUDED_TOOLS}")
        else:
            base_registry = full_registry

    # Create view-scoped registry
    registry = ViewScopedToolRegistry(base_registry)

    # Register all known providers
    for view, provider_cls in _PROVIDER_CLASSES.items():
        try:
            provider = provider_cls()
            registry.register_provider(provider)
        except Exception as e:
            logger.warning(f"Failed to create provider for {view.value}: {e}")

    # Set active view
    registry.set_active_view(view_context)

    # Cache if using standard configuration
    if use_cache and base_tool_names is None:
        _REGISTRY_CACHE[view_context] = registry

    logger.info(
        f"Created view-scoped registry: view={view_context.value}, "
        f"project_id={project_id}, container_id={container_id}, "
        f"tools={len(registry.get_available_tools())}"
    )

    return registry


def get_view_scoped_registry(view_context: ViewContext) -> ViewScopedToolRegistry:
    """
    Get or create a cached view-scoped registry.

    Convenience function for getting standard registries.

    Args:
        view_context: The view context

    Returns:
        ViewScopedToolRegistry for the specified view
    """
    return create_view_scoped_registry(view_context)


def clear_registry_cache():
    """Clear all cached registries."""
    _REGISTRY_CACHE.clear()
    logger.info("Cleared view-scoped registry cache")
