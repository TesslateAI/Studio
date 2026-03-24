"""Resolve project configuration from various sources.

Priority chain:
1. **Filesystem** — read ``.tesslate/config.json`` directly from a local path.
2. **Volume (K8s)** — read the config from a btrfs CSI volume via FileOps gRPC.
3. **LLM** — analyse the project file tree and generate a config with AI.
4. **Fallback** — return a minimal single-app config.

Helper ``collect_project_files`` gathers the file tree and config-file
contents that ``generate_config_via_llm`` needs.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.base_config_parser import (
    AppConfig,
    TesslateProjectConfig,
    parse_tesslate_config,
    read_tesslate_config,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        ".next",
        "__pycache__",
        ".venv",
        "vendor",
        "target",
    }
)

CONFIG_FILENAMES: frozenset[str] = frozenset(
    {
        "package.json",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Makefile",
        "pyproject.toml",
        "pubspec.yaml",
        "Gemfile",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "mix.exs",
        ".tesslate/config.json",
    }
)

_MAX_CONFIG_FILE_SIZE = 20 * 1024  # 20 KB per config file


# ---------------------------------------------------------------------------
# 1. Fast path — read from filesystem
# ---------------------------------------------------------------------------


async def resolve_config(source_path: str) -> TesslateProjectConfig | None:
    """Read .tesslate/config.json from *source_path*. Returns ``None`` if not found."""
    return read_tesslate_config(source_path)


# ---------------------------------------------------------------------------
# 2. Resolve from a K8s volume via FileOps gRPC
# ---------------------------------------------------------------------------


async def resolve_config_from_volume(
    volume_id: str,
    node_name: str,
) -> TesslateProjectConfig | None:
    """Read .tesslate/config.json from a btrfs volume via FileOps gRPC."""
    from ...services.fileops_client import FileOpsClient
    from ...services.node_discovery import NodeDiscovery

    try:
        discovery = NodeDiscovery()
        address = await discovery.get_fileops_address(node_name)
        async with FileOpsClient(address) as client:
            content = await client.read_file_text(volume_id, ".tesslate/config.json")
            return parse_tesslate_config(content)
    except Exception as e:
        logger.debug(f"[CONFIG-RESOLVER] Could not read config from volume: {e}")
        return None


# ---------------------------------------------------------------------------
# 3. LLM path — generate config via AI analysis
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a project analyzer. Analyze the project files and call the generate_config \
tool with the correct configuration for running this project in containerized dev environments."""

_LLM_USER_TEMPLATE = """\
Analyze this project and generate a .tesslate/config.json by calling the generate_config tool.

## File tree:
{file_tree_str}

## Config file contents:
{config_contents_str}

## Rules:
1. Every start command MUST bind to 0.0.0.0 (not localhost) for container networking
2. For Node.js: use `npm install && npm run dev -- --host 0.0.0.0` or equivalent
3. For Python: use `pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8001 --reload`
4. For Go: use `go mod tidy && go run .` or `air` if .air.toml exists
5. If the project has frontend + backend in separate dirs, create separate apps
6. If it's a monorepo with one entry point, use directory "." and one app
7. For projects with no server (CLI tools, libraries), set port to null and start to "sleep infinity"
8. Use common port conventions: Next.js=3000, Vite=5173, FastAPI=8001, Go=8080, Rails=3000, Django=8000
9. primaryApp should be the frontend or the main user-facing app
10. Only add infrastructure (postgres, redis, etc.) if the project clearly uses them
11. Set "build" to the production build command (e.g. "npm run build", "go build -o main"). Omit if no build step.
12. Set "output" to the build output directory (e.g. "dist", "out", "build", ".next/standalone"). Omit if no build step.
13. Set "framework" to the framework identifier (e.g. "nextjs", "vite", "react", "vue", "svelte", "astro", "fastapi", "go"). This helps deployment providers configure correctly."""

_GENERATE_CONFIG_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_config",
        "description": "Generate .tesslate/config.json for a project's containerized dev environment",
        "parameters": {
            "type": "object",
            "properties": {
                "apps": {
                    "type": "object",
                    "description": "Map of app name to app config",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Relative directory or '.' for root",
                            },
                            "port": {
                                "type": ["integer", "null"],
                                "description": "Port number or null for no server",
                            },
                            "start": {
                                "type": "string",
                                "description": "Shell command to install deps and start dev server",
                            },
                            "build": {
                                "type": "string",
                                "description": "Production build command (e.g. 'npm run build'). Omit if no build step.",
                            },
                            "output": {
                                "type": "string",
                                "description": "Build output directory (e.g. 'dist', 'out', 'build'). Omit if no build step.",
                            },
                            "framework": {
                                "type": "string",
                                "description": "Framework identifier (e.g. 'nextjs', 'vite', 'react', 'vue', 'fastapi', 'go')",
                            },
                            "env": {
                                "type": "object",
                                "description": "Environment variables",
                                "additionalProperties": {"type": "string"},
                            },
                        },
                        "required": ["directory", "port", "start"],
                    },
                },
                "infrastructure": {
                    "type": "object",
                    "description": "Map of service name to infra config (databases, caches, etc.)",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "image": {
                                "type": "string",
                                "description": "Docker image:tag",
                            },
                            "port": {
                                "type": "integer",
                                "description": "Internal port",
                            },
                        },
                        "required": ["image", "port"],
                    },
                },
                "primaryApp": {
                    "type": "string",
                    "description": "Name of the main app to show in preview",
                },
            },
            "required": ["apps", "infrastructure", "primaryApp"],
        },
    },
}


async def generate_config_via_llm(
    file_tree: list[str],
    config_files_content: dict[str, str],
    user_id: UUID,
    db: AsyncSession,
    model: str | None = None,
) -> TesslateProjectConfig | None:
    """Analyse project files via LLM tool call and generate config. Returns ``None`` on failure."""
    import json

    from ...agent.models import get_llm_client, resolve_model_name
    from ...config import get_settings

    settings = get_settings()

    file_tree_str = "\n".join(file_tree)
    config_contents_str = "\n\n".join(
        f"### {fname}\n```\n{content}\n```" for fname, content in config_files_content.items()
    )

    prompt = _LLM_USER_TEMPLATE.format(
        file_tree_str=file_tree_str,
        config_contents_str=config_contents_str,
    )

    try:
        analyze_model = model or settings.default_model
        client = await get_llm_client(user_id, analyze_model, db)
        resolved_model = resolve_model_name(analyze_model)

        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[_GENERATE_CONFIG_TOOL],
            tool_choice={"type": "function", "function": {"name": "generate_config"}},
            temperature=0.1,
            max_tokens=2000,
        )

        message = response.choices[0].message

        # Extract config from tool call arguments (guaranteed valid JSON by the API)
        if not message.tool_calls:
            logger.warning("[CONFIG-RESOLVER] LLM did not produce a tool call")
            return None

        args_json = message.tool_calls[0].function.arguments
        config_data = json.loads(args_json)
        return parse_tesslate_config(json.dumps(config_data))
    except Exception as e:
        logger.warning(f"[CONFIG-RESOLVER] LLM config generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 4. Fallback config
# ---------------------------------------------------------------------------


def fallback_config(project_name: str) -> TesslateProjectConfig:
    """Single app, directory='.', port=3000, no start command."""
    safe_name = project_name.lower().replace(" ", "-")[:30] or "app"
    return TesslateProjectConfig(
        apps={safe_name: AppConfig(directory=".", port=3000, start="")},
        infrastructure={},
        primaryApp=safe_name,
    )


# ---------------------------------------------------------------------------
# 5. Helper — collect file tree and config files from a local path
# ---------------------------------------------------------------------------


async def collect_project_files(
    source_path: str,
) -> tuple[list[str], dict[str, str]]:
    """Walk *source_path* and return ``(file_tree, config_files_content)``.

    Directories in :data:`SKIP_DIRS` are pruned.  Only files whose name
    matches :data:`CONFIG_FILENAMES` have their content read (up to 20 KB
    each).
    """
    file_tree: list[str] = []
    config_files_content: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(source_path):
        # Prune skipped directories in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, source_path)
            file_tree.append(rel_path)

            if rel_path in CONFIG_FILENAMES or fname in CONFIG_FILENAMES:
                try:
                    size = os.path.getsize(full_path)
                    if size <= _MAX_CONFIG_FILE_SIZE:
                        with open(full_path, encoding="utf-8", errors="replace") as fh:
                            config_files_content[rel_path] = fh.read()
                except OSError:
                    pass  # Skip unreadable files silently

    return file_tree, config_files_content
