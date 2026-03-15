"""
Base Configuration Parser

Parses .tesslate/config.json from project directories to extract:
- Startup commands (with security validation)
- App configuration (ports, env vars, directories)
- Infrastructure services

This enables dynamic, language-agnostic container startup.

SECURITY: All startup commands are validated to prevent:
- Command injection
- Privilege escalation
- Network attacks
- File system escapes
- Resource exhaustion
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# SECURITY: Dangerous patterns that are NEVER allowed in startup commands
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",  # Delete root filesystem
    r":\(\)\{.*\|.*&\s*\};:",  # Fork bomb
    r"curl.*\|\s*sh",  # Download and execute scripts
    r"wget.*\|\s*sh",  # Download and execute scripts
    r"nc\s+-l",  # Netcat listener (reverse shell)
    r"dd\s+if=/dev/zero",  # Disk fill attack
    r"mkfifo.*nc",  # Named pipe reverse shell
    r"/dev/tcp/",  # Bash TCP connections
    r"eval\s*\$\(",  # Eval with command substitution
    r"sudo\s+",  # Privilege escalation (container runs as 1000:1000)
    r"su\s+",  # Switch user
    r"chmod\s+[0-7]*7[0-7]*\s+/",  # Make system files executable
    r"chown\s+.*\s+/",  # Change ownership of system files
    r"docker\s+",  # Docker-in-docker (security risk)
    r"\$\(curl",  # Command substitution with network
    r"\$\(wget",  # Command substitution with network
    r">\s*/dev/sda",  # Write to disk devices
    r">\s*/proc/",  # Write to proc filesystem
    r"iptables",  # Firewall modification
    r"setuid",  # Set UID bit
    r"passwd\s+",  # Password modification
]

# SECURITY: Whitelist of safe command prefixes (only these are allowed to start commands)
SAFE_COMMAND_PREFIXES = [
    "npm",
    "node",
    "npx",
    "yarn",
    "pnpm",
    "bun",
    "bunx",  # Node.js
    "python",
    "python3",
    "pip",
    "pip3",
    "uv",
    "uvicorn",
    "gunicorn",
    "flask",
    "poetry",  # Python
    "go",
    "air",  # Go
    "cargo",
    "rustc",  # Rust
    "dotnet",  # .NET
    "java",
    "mvn",
    "gradle",  # Java
    "ruby",
    "bundle",
    "rails",  # Ruby
    "php",
    "composer",  # PHP
    "cd",
    "ls",
    "echo",
    "sleep",
    "cat",
    "mkdir",
    "cp",
    "mv",  # Safe shell commands
    "if",
    "for",
    "while",
    "test",
    "[",  # Shell control flow
]


def validate_startup_command(command: str) -> tuple[bool, str | None]:
    """
    Validate startup command for security issues.

    Args:
        command: Raw startup command string to validate

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if command is safe
        - (False, "reason") if command is dangerous
    """
    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            logger.error(f"[SECURITY] Dangerous pattern detected: {pattern}")
            return False, f"Command contains dangerous pattern: {pattern}"

    # Check that all commands start with safe prefixes
    # Split command by &&, ||, ;, and | to get individual commands
    commands = re.split(r"[;&|]+", command)

    for cmd in commands:
        cmd = cmd.strip()
        if not cmd or cmd.startswith("#"):  # Skip empty lines and comments
            continue

        # Get the first word (actual command)
        first_word = cmd.split()[0] if cmd.split() else ""

        # Allow shell built-ins and safe prefixes
        if first_word and not any(
            first_word.startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES
        ):
            logger.warning(f"[SECURITY] Command '{first_word}' not in whitelist")
            return False, f"Command '{first_word}' is not in the safe command whitelist"

    # Check command length (prevent resource exhaustion)
    if len(command) > 10000:
        return False, "Command is too long (max 10000 characters)"

    logger.info("[SECURITY] ✅ Command validated successfully")
    return True, None


def get_node_modules_fix_prefix() -> str:
    """Public API for K8s orchestrator."""
    return _install_deps_if_missing_command()


def _install_deps_if_missing_command() -> str:
    """
    Generate a shell snippet that installs dependencies if node_modules is missing.

    node_modules is never copied between filesystems -- it is always installed
    fresh inside the container to avoid broken symlinks and permission issues.
    This detects the lockfile to pick the right package manager.
    """
    return (
        'if [ -f "package.json" ] && [ ! -d "node_modules" ]; then '
        '  echo "[TESSLATE] Installing dependencies..." && '
        '  if [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then bun install; '
        '  elif [ -f "pnpm-lock.yaml" ]; then pnpm install; '
        '  elif [ -f "yarn.lock" ]; then yarn install; '
        "  else npm install; "
        "  fi; "
        "fi && "
    )


# ---------------------------------------------------------------------------
# .tesslate/config.json parser
# ---------------------------------------------------------------------------


@dataclass
class AppConfig:
    """Configuration for a single app in .tesslate/config.json."""
    directory: str = "."
    port: int | None = 3000
    start: str = ""
    env: dict[str, str] = field(default_factory=dict)
    x: float | None = None
    y: float | None = None


@dataclass
class InfraConfig:
    """Configuration for an infrastructure service in .tesslate/config.json."""
    image: str = ""
    port: int = 5432
    x: float | None = None
    y: float | None = None


@dataclass
class TesslateProjectConfig:
    """Parsed .tesslate/config.json configuration."""
    apps: dict[str, AppConfig] = field(default_factory=dict)
    infrastructure: dict[str, InfraConfig] = field(default_factory=dict)
    primaryApp: str = ""


def parse_tesslate_config(json_str: str) -> TesslateProjectConfig:
    """
    Parse .tesslate/config.json content and return validated config.

    Args:
        json_str: Raw JSON string from .tesslate/config.json

    Returns:
        TesslateProjectConfig with parsed and validated data

    Raises:
        ValueError: If JSON is invalid or contains dangerous commands
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in .tesslate/config.json: {e}")

    config = TesslateProjectConfig()

    # Parse apps
    for name, app_data in data.get("apps", {}).items():
        start_cmd = app_data.get("start", "")
        if start_cmd:
            is_valid, error = validate_startup_command(start_cmd)
            if not is_valid:
                raise ValueError(f"App '{name}' has invalid start command: {error}")

        config.apps[name] = AppConfig(
            directory=app_data.get("directory", "."),
            port=app_data.get("port", 3000),
            start=start_cmd,
            env=app_data.get("env", {}),
            x=app_data.get("x"),
            y=app_data.get("y"),
        )

    # Parse infrastructure
    for name, infra_data in data.get("infrastructure", {}).items():
        config.infrastructure[name] = InfraConfig(
            image=infra_data.get("image", ""),
            port=infra_data.get("port", 5432),
            x=infra_data.get("x"),
            y=infra_data.get("y"),
        )

    config.primaryApp = data.get("primaryApp", "")

    # Validate primaryApp exists in apps (if specified)
    if config.primaryApp and config.primaryApp not in config.apps:
        logger.warning(f"[CONFIG] primaryApp '{config.primaryApp}' not found in apps, will use first app")
        if config.apps:
            config.primaryApp = next(iter(config.apps))

    return config


def read_tesslate_config(project_path: str) -> TesslateProjectConfig | None:
    """
    Read and parse .tesslate/config.json from a project directory.

    Args:
        project_path: Absolute path to project root (e.g., /projects/my-project-abc123)

    Returns:
        TesslateProjectConfig or None if file doesn't exist
    """
    config_path = Path(project_path) / ".tesslate" / "config.json"
    try:
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")
            config = parse_tesslate_config(content)
            logger.info(f"[CONFIG] Successfully parsed .tesslate/config.json from {project_path}")
            return config
        else:
            logger.debug(f"[CONFIG] No .tesslate/config.json found at {config_path}")
            return None
    except ValueError as e:
        logger.error(f"[CONFIG] Failed to parse .tesslate/config.json: {e}")
        return None
    except Exception as e:
        logger.error(f"[CONFIG] Error reading .tesslate/config.json: {e}")
        return None


def write_tesslate_config(project_path: str, config: TesslateProjectConfig) -> None:
    """
    Write .tesslate/config.json to a project directory.

    Args:
        project_path: Absolute path to project root
        config: TesslateProjectConfig to serialize
    """
    config_dir = Path(project_path) / ".tesslate"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "config.json"

    data: dict[str, Any] = {
        "apps": {},
        "infrastructure": {},
        "primaryApp": config.primaryApp,
    }

    for name, app in config.apps.items():
        app_data: dict[str, Any] = {
            "directory": app.directory,
            "port": app.port,
            "start": app.start,
            "env": app.env,
        }
        if app.x is not None:
            app_data["x"] = app.x
        if app.y is not None:
            app_data["y"] = app.y
        data["apps"][name] = app_data

    for name, infra in config.infrastructure.items():
        infra_data: dict[str, Any] = {
            "image": infra.image,
            "port": infra.port,
        }
        if infra.x is not None:
            infra_data["x"] = infra.x
        if infra.y is not None:
            infra_data["y"] = infra.y
        data["infrastructure"][name] = infra_data

    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    logger.info(f"[CONFIG] Wrote .tesslate/config.json to {config_path}")


def get_app_startup_config(project_path: str, app_name: str) -> tuple[list[str], int]:
    """
    Unified function to get startup command and port for an app.

    Priority:
    1. .tesslate/config.json
    2. Generic fallback (no config found)

    Args:
        project_path: Absolute path to project root
        app_name: Name of the app (key in config.apps)

    Returns:
        Tuple of (command_array, port) where command_array is ['sh', '-c', '...']
    """
    # Priority 1: .tesslate/config.json
    tesslate_config = read_tesslate_config(project_path)
    if tesslate_config and app_name in tesslate_config.apps:
        app = tesslate_config.apps[app_name]
        port = app.port or 3000

        if app.start:
            # Build env var prefix if any
            env_prefix = ""
            if app.env:
                env_parts = [f'export {k}="{v}"' for k, v in app.env.items()]
                env_prefix = " && ".join(env_parts) + " && "

            # Prepend dependency install for Node.js projects
            deps_prefix = _install_deps_if_missing_command()

            # Handle directory change if not root
            dir_prefix = ""
            if app.directory and app.directory != ".":
                dir_prefix = f"cd {app.directory} && "

            command = f"{dir_prefix}{env_prefix}{deps_prefix}{app.start}"
            logger.info(f"[CONFIG] Using .tesslate/config.json for app '{app_name}': port={port}")
            return ["sh", "-c", command], port
        else:
            # No start command - keep container alive
            logger.info(f"[CONFIG] App '{app_name}' has no start command, using sleep infinity")
            return ["sh", "-c", "sleep infinity"], port

    # Priority 2: Generic fallback (no config found)
    logger.info(f"[CONFIG] Using generic fallback for app '{app_name}'")
    return ["sh", "-c", "sleep infinity"], 3000
