"""Live marker substitution for built-in skill bodies.

Skill bodies authored in ``seeds/skills.py`` may contain marker tokens of the
form ``{{MARKER_NAME}}``. When an agent calls ``load_skill`` on a built-in,
each marker is replaced by a freshly-rendered block sourced directly from the
authoritative Python modules (Pydantic models, ``SERVICES`` catalog,
validation constants, etc.). This eliminates drift between the skill body
and the code it documents.

Caching is trivially simple: once a skill slug has been rendered in this
process, the result is memoised in ``_RENDERED`` and returned on every
subsequent call. Both the skill body and its code sources can only change
across a redeploy, which restarts the process and wipes the dict — so no
TTL or invalidation logic is needed.

Exposed surface:
  * ``render_markers(body)``        — low-level: substitute markers in any text
  * ``get_rendered_body(slug, raw)`` — memoised version keyed on slug
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Renderers — each reads from its authoritative source
# ---------------------------------------------------------------------------


def _render_config_schema() -> str:
    """Pydantic-generated JSON Schema for the full .tesslate/config.json body."""
    from ..schemas import TesslateConfigCreate

    schema = TesslateConfigCreate.model_json_schema()
    return "```json\n" + json.dumps(schema, indent=2) + "\n```"


def _render_startup_command_rules() -> str:
    """Safe command prefixes, dangerous-pattern blocklist, and meta rules."""
    from .base_config_parser import DANGEROUS_PATTERNS, SAFE_COMMAND_PREFIXES

    safe = ", ".join(f"`{p}`" for p in SAFE_COMMAND_PREFIXES)
    dangerous_lines = "\n".join(f"- `{p}`" for p in DANGEROUS_PATTERNS)
    return (
        "**Every `start` command is validated before a container starts.** "
        "A command is rejected if any of the rules below fails.\n\n"
        "### Safe-prefix whitelist\n\n"
        f"The first token of every sub-command (splits on `;`, `&&`, `||`, `|`) "
        f"must start with one of:\n\n{safe}\n\n"
        "### Dangerous-pattern blocklist (regex, case-insensitive)\n\n"
        f"{dangerous_lines}\n\n"
        "### Other rules\n\n"
        "- **Bind to `0.0.0.0`**, not `localhost` / `127.0.0.1`. The container "
        "is accessed from outside its own network namespace — localhost-bound "
        "servers are unreachable.\n"
        "- **Max command length: 10,000 characters.**\n"
        "- Commands run as the container's non-root user (1000:1000); no `sudo`.\n"
    )


def _render_service_catalog() -> str:
    """The full infrastructure service catalog — one row per service."""
    from .service_definitions import SERVICES, ServiceType

    # Only list runnable/container services + external providers; skip
    # deployment targets (rendered separately).
    relevant = [
        s for s in SERVICES.values() if s.service_type != ServiceType.DEPLOYMENT_TARGET
    ]
    # Group by category for easier reading.
    by_category: dict[str, list] = {}
    for svc in relevant:
        by_category.setdefault(svc.category, []).append(svc)

    lines = [
        "The agent can add any of these services as an **infrastructure** node "
        "(`container_type=service`). The slug goes in `infrastructure.<slug>` "
        "and the `image`, `port`, and `env` fields are pre-filled from the "
        "catalog unless overridden.\n",
    ]
    for category in sorted(by_category):
        lines.append(f"\n### {category.title()}\n")
        lines.append("| Slug | Name | Image | Port | Outputs |")
        lines.append("|------|------|-------|------|---------|")
        for svc in sorted(by_category[category], key=lambda s: s.slug):
            outputs = ", ".join(f"`{k}`" for k in svc.outputs) if svc.outputs else "—"
            image = f"`{svc.docker_image}`" if svc.docker_image else "external"
            port = str(svc.internal_port or svc.default_port or "—")
            lines.append(
                f"| `{svc.slug}` | {svc.name} | {image} | {port} | {outputs} |"
            )

    # Connection-template examples for the two most common DB services.
    examples: list[str] = []
    for key in ("postgres", "redis"):
        svc = SERVICES.get(key)
        if svc and svc.connection_template:
            tmpl = json.dumps(svc.connection_template, indent=2)
            examples.append(f"#### `{key}` connection_template\n\n```json\n{tmpl}\n```")
    if examples:
        lines.append(
            "\n### Connection templates\n\n"
            "When a container `connection` points from an **app** to an "
            "**infrastructure** node, these env vars are computed from the "
            "service's credentials and injected into the app's environment. "
            "Placeholders like `{container_name}` and `{internal_port}` are "
            "filled by the orchestrator.\n"
        )
        lines.extend(examples)

    return "\n".join(lines)


def _render_connection_semantics() -> str:
    """What a connections edge actually does."""
    return (
        "A `connections` entry `{\"from_node\": \"A\", \"to_node\": \"B\"}` "
        "declares **three things** at once:\n\n"
        "1. **Startup ordering** — `A` is started after `B` is healthy.\n"
        "2. **Env-var injection** — `B`'s `outputs` / `connection_template` "
        "values are rendered with `B`'s credentials and placed into `A`'s "
        "environment. E.g. connecting an app to `postgres` automatically "
        "injects `DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`, etc. — "
        "the app never has to hard-code the hostname.\n"
        "3. **Service DNS resolution** — in K8s mode, `B` is reachable from "
        "`A` as `http://<B-name>.proj-<project_id>.svc.cluster.local:<port>`. "
        "In Docker, `B` is reachable as `http://<B-name>` on the project "
        "network. The orchestrator handles DNS; the app uses plain "
        "hostnames.\n\n"
        "**Connector types** (`ContainerConnection.connector_type`):\n"
        "- `env_injection` (default) — computes env vars from templates.\n"
        "- `http_api`, `database`, `message_queue`, `websocket`, `cache`, "
        "`depends_on` — metadata hints; behavior today is the same as "
        "`env_injection`.\n"
    )


def _render_deployment_compatibility() -> str:
    """Per-provider framework support and exclusion rules."""
    from .service_definitions import DEPLOYMENT_COMPATIBILITY

    lines = [
        "External deployment targets (provider nodes in the config) only "
        "accept certain frameworks and container types. The `targets` list "
        "in a deployment entry must reference app names whose `framework` "
        "is supported by the provider.\n",
        "| Provider | Supported frameworks | Target `container_type` | Excluded services |",
        "|----------|----------------------|-------------------------|-------------------|",
    ]
    for provider, rules in DEPLOYMENT_COMPATIBILITY.items():
        display = rules.get("display_name", provider)
        fw = ", ".join(rules.get("frameworks", [])) or "—"
        ct = ", ".join(rules.get("container_types", [])) or "—"
        ex = ", ".join(rules.get("exclude_services", [])) or "—"
        lines.append(f"| {display} | {fw} | {ct} | {ex} |")
    return "\n".join(lines)


def _render_container_types() -> str:
    """Explain base vs service container_type."""
    return (
        "Every container has a `container_type`:\n\n"
        "- **`base`** — an application the user builds or owns. Has a "
        "`directory`, `port`, and a `start` command. Deployable to "
        "external providers (Vercel/Netlify/Cloudflare). In config, lives "
        "under `apps`.\n"
        "- **`service`** — a managed infrastructure dependency (database, "
        "cache, etc.) run from a known Docker image. Not deployable. In "
        "config, lives under `infrastructure` and is keyed by a slug from "
        "the service catalog.\n\n"
        "Only `base` containers can be the target of a `deployments` entry "
        "or a `previews` entry."
    )


def _render_url_patterns() -> str:
    """Docker vs K8s URL patterns exposed to users / the agent."""
    return (
        "- **Docker (local dev)** — `http://<project-slug>-<container-name>"
        ".<app-domain>` via Traefik. Example: "
        "`http://my-app-abc-frontend.localhost`.\n"
        "- **Kubernetes** — `https://<project-slug>-<container-name>."
        "<app-domain>` via NGINX Ingress. Example: "
        "`https://my-app-abc-frontend.your-domain.com`.\n"
        "- **Internal service DNS (K8s only)** — `http://dev-<container-dir>."
        "proj-<project-id>.svc.cluster.local:<port>` for pod-to-pod calls. "
        "Used by `project_control`'s `health_check` action.\n\n"
        "The agent should never hard-code these URLs in code it writes — "
        "the orchestrator derives them at container start and the canvas UI "
        "shows them to the user."
    )


def _render_lifecycle_tools() -> str:
    """Static reference of the agent's lifecycle-tool surface."""
    return (
        "| Tool | Purpose |\n"
        "|------|---------|\n"
        "| `apply_setup_config` | Atomic write of `.tesslate/config.json` + "
        "replace the project graph (containers/connections/deployments/"
        "previews) in one transaction. Validates every startup command. |\n"
        "| `project_start` | Start every container in the project. |\n"
        "| `project_stop` | Stop every container + close shell sessions. |\n"
        "| `project_restart` | One-call stop + start for the whole stack. |\n"
        "| `container_start` | Start a single container by name. |\n"
        "| `container_stop` | Stop a single container by name. |\n"
        "| `container_restart` | Stop + start a single container. |\n"
        "| `project_control` (observation) | `action=status` / "
        "`container_logs` / `health_check` — read-only inspection. |\n\n"
        "**Typical flow** after editing config:\n\n"
        "```\n"
        "apply_setup_config(config=…)            # write + sync graph\n"
        "container_restart(container_name=…)     # for each affected app\n"
        "project_control(action=\"health_check\", container_name=…)\n"
        "project_control(action=\"container_logs\", container_name=…) if unhealthy\n"
        "```\n"
    )


# ---------------------------------------------------------------------------
# Registry + render entry point
# ---------------------------------------------------------------------------


MARKER_RENDERERS: dict[str, Callable[[], str]] = {
    "{{TESSLATE_CONFIG_SCHEMA}}": _render_config_schema,
    "{{STARTUP_COMMAND_RULES}}": _render_startup_command_rules,
    "{{SERVICE_CATALOG}}": _render_service_catalog,
    "{{CONNECTION_SEMANTICS}}": _render_connection_semantics,
    "{{DEPLOYMENT_COMPATIBILITY}}": _render_deployment_compatibility,
    "{{CONTAINER_TYPES}}": _render_container_types,
    "{{URL_PATTERNS}}": _render_url_patterns,
    "{{LIFECYCLE_TOOLS}}": _render_lifecycle_tools,
}


def render_markers(body: str) -> str:
    """Substitute every known marker in *body*. Unknown markers are left as-is."""
    rendered = body
    for marker, renderer in MARKER_RENDERERS.items():
        if marker in rendered:
            try:
                rendered = rendered.replace(marker, renderer())
            except Exception:
                logger.exception(
                    "Failed to render marker %s; leaving placeholder in body",
                    marker,
                )
    return rendered


_RENDERED: dict[str, str] = {}


def get_rendered_body(slug: str, raw_body: str) -> str:
    """Return the marker-substituted body for *slug*, caching per-process.

    First call for a slug pays the render cost. Every subsequent call is a
    dict lookup. Both the skill body and its code sources can only change
    across a redeploy (which restarts the process), so there is no need for
    per-body keying or invalidation.
    """
    if slug not in _RENDERED:
        _RENDERED[slug] = render_markers(raw_body)
    return _RENDERED[slug]


def _reset_cache_for_tests() -> None:
    """Unit-test hook — clears the per-process cache."""
    _RENDERED.clear()
