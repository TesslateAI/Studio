"""
Deployment guards service for validating container-to-provider compatibility.

This module defines which deployment providers support which container types
and frameworks, enabling the UI to show/prevent invalid connections.
"""

from typing import TypedDict


class ProviderCapability(TypedDict):
    """Defines what a deployment provider supports."""

    display_name: str
    types: list[str]  # Container types: frontend, backend, fullstack, worker, database, *
    frameworks: list[str]  # Supported frameworks: nextjs, react, vue, fastapi, etc., *
    supports_serverless: bool
    supports_static: bool
    supports_fullstack: bool
    deployment_mode: str  # source (provider builds) or pre-built (upload built files)
    icon: str  # Provider icon/emoji
    color: str  # Brand color for UI
    auth_type: str  # oauth, token, or none


# Provider compatibility definitions
PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "vercel": {
        "display_name": "Vercel",
        "types": ["frontend"],
        "frameworks": [
            "nextjs",
            "react",
            "vue",
            "svelte",
            "astro",
            "nuxt",
            "remix",
            "solid",
            "qwik",
        ],
        "supports_serverless": True,
        "supports_static": True,
        "supports_fullstack": False,  # Only with edge functions
        "deployment_mode": "source",
        "icon": "▲",
        "color": "#000000",
        "auth_type": "oauth",
    },
    "netlify": {
        "display_name": "Netlify",
        "types": ["frontend"],
        "frameworks": [
            "nextjs",
            "react",
            "vue",
            "svelte",
            "astro",
            "gatsby",
            "nuxt",
            "hugo",
            "jekyll",
        ],
        "supports_serverless": True,
        "supports_static": True,
        "supports_fullstack": False,
        "deployment_mode": "pre-built",
        "icon": "◆",
        "color": "#00C7B7",
        "auth_type": "oauth",
    },
    "cloudflare": {
        "display_name": "Cloudflare",
        "types": ["frontend", "worker"],
        "frameworks": ["react", "vue", "svelte", "astro", "solid", "qwik"],
        "supports_serverless": True,  # Workers
        "supports_static": True,  # Pages
        "supports_fullstack": False,
        "deployment_mode": "pre-built",
        "icon": "🔥",
        "color": "#F38020",
        "auth_type": "token",
    },
    "digitalocean": {
        "display_name": "DigitalOcean K8s",
        "types": ["*"],  # All container types
        "frameworks": ["*"],  # All frameworks
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,  # App Platform
        "deployment_mode": "source",
        "icon": "🌊",
        "color": "#0080FF",
        "auth_type": "token",
    },
    "railway": {
        "display_name": "Railway",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "🚂",
        "color": "#0B0D0E",
        "auth_type": "token",
    },
    "fly": {
        "display_name": "Fly.io",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "container",
        "icon": "✈️",
        "color": "#7B3FE4",
        "auth_type": "token",
    },
    "heroku": {
        "display_name": "Heroku",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "🟣",
        "color": "#430098",
        "auth_type": "token",
    },
    "render": {
        "display_name": "Render",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "🔷",
        "color": "#46E3B7",
        "auth_type": "token",
    },
    "koyeb": {
        "display_name": "Koyeb",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": True,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "🟢",
        "color": "#121212",
        "auth_type": "token",
    },
    "zeabur": {
        "display_name": "Zeabur",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": True,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "⚡",
        "color": "#6C5CE7",
        "auth_type": "token",
    },
    "northflank": {
        "display_name": "Northflank",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "source",
        "icon": "🔶",
        "color": "#01E277",
        "auth_type": "token",
    },
    "github-pages": {
        "display_name": "GitHub Pages",
        "types": ["frontend"],
        "frameworks": ["react", "vue", "svelte", "astro", "nextjs"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": False,
        "deployment_mode": "pre-built",
        "icon": "📄",
        "color": "#222222",
        "auth_type": "token",
    },
    "surge": {
        "display_name": "Surge.sh",
        "types": ["frontend"],
        "frameworks": ["react", "vue", "svelte", "astro", "vite"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": False,
        "deployment_mode": "pre-built",
        "icon": "🌊",
        "color": "#D93472",
        "auth_type": "token",
    },
    "deno-deploy": {
        "display_name": "Deno Deploy",
        "types": ["frontend", "backend"],
        "frameworks": ["*"],
        "supports_serverless": True,
        "supports_static": True,
        "supports_fullstack": False,
        "deployment_mode": "source",
        "icon": "🦕",
        "color": "#000000",
        "auth_type": "token",
    },
    "firebase": {
        "display_name": "Firebase Hosting",
        "types": ["frontend"],
        "frameworks": ["react", "vue", "svelte", "astro", "nextjs", "angular"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": False,
        "deployment_mode": "pre-built",
        "icon": "🔥",
        "color": "#FFCA28",
        "auth_type": "token",
    },
    "aws-apprunner": {
        "display_name": "AWS App Runner",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": False,
        "supports_fullstack": True,
        "deployment_mode": "container",
        "icon": "☁️",
        "color": "#FF9900",
        "auth_type": "token",
    },
    "gcp-cloudrun": {
        "display_name": "GCP Cloud Run",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": True,
        "supports_static": False,
        "supports_fullstack": True,
        "deployment_mode": "container",
        "icon": "☁️",
        "color": "#4285F4",
        "auth_type": "token",
    },
    "azure-container-apps": {
        "display_name": "Azure Container Apps",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": True,
        "supports_static": False,
        "supports_fullstack": True,
        "deployment_mode": "container",
        "icon": "☁️",
        "color": "#0078D4",
        "auth_type": "token",
    },
    "do-container": {
        "display_name": "DigitalOcean App Platform (Container)",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "container",
        "icon": "🌊",
        "color": "#0080FF",
        "auth_type": "token",
    },
    "dockerhub": {
        "display_name": "Docker Hub",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": False,
        "supports_fullstack": False,
        "deployment_mode": "export",
        "icon": "🐳",
        "color": "#2496ED",
        "auth_type": "token",
    },
    "ghcr": {
        "display_name": "GitHub Container Registry",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": False,
        "supports_fullstack": False,
        "deployment_mode": "export",
        "icon": "📦",
        "color": "#222222",
        "auth_type": "token",
    },
    "download": {
        "display_name": "Download Export",
        "types": ["*"],
        "frameworks": ["*"],
        "supports_serverless": False,
        "supports_static": True,
        "supports_fullstack": True,
        "deployment_mode": "export",
        "icon": "💾",
        "color": "#6B7280",
        "auth_type": "none",
    },
}

# Map common framework names to normalized names
FRAMEWORK_ALIASES: dict[str, str] = {
    "next": "nextjs",
    "next.js": "nextjs",
    "react-app": "react",
    "create-react-app": "react",
    "cra": "react",
    "vue3": "vue",
    "vue.js": "vue",
    "sveltekit": "svelte",
    "nuxt3": "nuxt",
    "nuxt.js": "nuxt",
    "fastapi": "python",
    "flask": "python",
    "django": "python",
    "express": "node",
    "nodejs": "node",
    "node.js": "node",
    "go": "golang",
}

# Map service_slug to container type category
SERVICE_TYPE_MAPPING: dict[str, str] = {
    # Databases
    "postgres": "database",
    "postgresql": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "cache",
    "memcached": "cache",
    # Backends
    "fastapi": "backend",
    "flask": "backend",
    "django": "backend",
    "express": "backend",
    "node": "backend",
    "python": "backend",
    "go": "backend",
    "rust": "backend",
    # Frontends
    "nextjs": "frontend",
    "react": "frontend",
    "vue": "frontend",
    "svelte": "frontend",
    "astro": "frontend",
    "angular": "frontend",
    "gatsby": "frontend",
    # Workers
    "worker": "worker",
    "cloudflare-worker": "worker",
}


class ValidationResult(TypedDict):
    """Result of a deployment validation check."""

    allowed: bool
    reason: str
    provider_info: ProviderCapability | None


def normalize_framework(framework: str | None) -> str | None:
    """Normalize framework name to standard form."""
    if not framework:
        return None
    framework_lower = framework.lower().strip()
    return FRAMEWORK_ALIASES.get(framework_lower, framework_lower)


def get_container_type_category(
    container_type: str | None,
    service_slug: str | None,
    framework: str | None,
) -> str:
    """Determine the container type category for validation."""
    # Service containers are usually databases/caches
    if container_type == "service":
        if service_slug and service_slug.lower() in SERVICE_TYPE_MAPPING:
            return SERVICE_TYPE_MAPPING[service_slug.lower()]
        return "service"

    # Base containers - infer from framework
    if framework:
        framework_normalized = normalize_framework(framework)
        if framework_normalized and framework_normalized in SERVICE_TYPE_MAPPING:
            return SERVICE_TYPE_MAPPING[framework_normalized]

    # Default to frontend for base containers (most common case)
    return "frontend" if container_type == "base" else "unknown"


def validate_deployment_connection(
    provider: str,
    container_type: str | None,
    service_slug: str | None = None,
    framework: str | None = None,
) -> ValidationResult:
    """
    Validate whether a container can be deployed to a specific provider.

    Args:
        provider: The deployment provider (vercel, netlify, cloudflare, digitalocean, railway, fly)
        container_type: The container type (base, service)
        service_slug: For service containers, the service identifier (postgres, redis, etc.)
        framework: The detected framework (nextjs, react, fastapi, etc.)

    Returns:
        ValidationResult with allowed status, reason, and provider info
    """
    # Check if provider is supported
    if provider not in PROVIDER_CAPABILITIES:
        return {
            "allowed": False,
            "reason": f"Unknown deployment provider: {provider}",
            "provider_info": None,
        }

    provider_info = PROVIDER_CAPABILITIES[provider]

    # Service containers (databases, caches) cannot be deployed to external providers
    if container_type == "service":
        service_type = SERVICE_TYPE_MAPPING.get(service_slug.lower() if service_slug else "", "service")
        if service_type in ("database", "cache"):
            return {
                "allowed": False,
                "reason": f"{provider_info['display_name']} cannot deploy database/cache services. "
                "Use managed services or full-stack providers like Railway or Fly.io.",
                "provider_info": provider_info,
            }

    # Get the container's type category
    type_category = get_container_type_category(container_type, service_slug, framework)

    # Check type compatibility
    allowed_types = provider_info["types"]
    if "*" not in allowed_types and type_category not in allowed_types:
        allowed_list = ", ".join(allowed_types)
        return {
            "allowed": False,
            "reason": f"{provider_info['display_name']} only supports {allowed_list} containers. "
            f"This container is detected as '{type_category}'.",
            "provider_info": provider_info,
        }

    # Check framework compatibility
    framework_normalized = normalize_framework(framework)
    allowed_frameworks = provider_info["frameworks"]
    if (
        framework_normalized
        and "*" not in allowed_frameworks
        and framework_normalized not in allowed_frameworks
    ):
        allowed_list = ", ".join(allowed_frameworks[:5])
        if len(allowed_frameworks) > 5:
            allowed_list += f", and {len(allowed_frameworks) - 5} more"
        return {
            "allowed": False,
            "reason": f"{provider_info['display_name']} doesn't support {framework} framework. "
            f"Supported: {allowed_list}.",
            "provider_info": provider_info,
        }

    # Passed all checks
    return {
        "allowed": True,
        "reason": f"Container can be deployed to {provider_info['display_name']}",
        "provider_info": provider_info,
    }


def get_compatible_providers(
    container_type: str | None,
    service_slug: str | None = None,
    framework: str | None = None,
) -> list[str]:
    """
    Get list of providers compatible with a container.

    Returns list of provider slugs that can deploy this container.
    """
    compatible = []
    for provider in PROVIDER_CAPABILITIES:
        result = validate_deployment_connection(
            provider=provider,
            container_type=container_type,
            service_slug=service_slug,
            framework=framework,
        )
        if result["allowed"]:
            compatible.append(provider)
    return compatible


def get_provider_info(provider: str) -> ProviderCapability | None:
    """Get capability info for a provider."""
    return PROVIDER_CAPABILITIES.get(provider)


def list_all_providers() -> dict[str, ProviderCapability]:
    """Get all provider capabilities."""
    return PROVIDER_CAPABILITIES.copy()
