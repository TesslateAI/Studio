"""
Base Configuration Parser

Parses TESSLATE.md from marketplace bases OR user custom repos to extract:
- Startup commands (with security validation)
- Project structure
- Framework configuration
- Language-specific setup

This enables dynamic, language-agnostic container startup.

SECURITY: All startup commands are validated to prevent:
- Command injection
- Privilege escalation
- Network attacks
- File system escapes
- Resource exhaustion
"""
import re
import logging
import asyncio
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


# SECURITY: Dangerous patterns that are NEVER allowed in startup commands
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+/',  # Delete root filesystem
    r':\(\)\{.*\|.*&\s*\};:',  # Fork bomb
    r'curl.*\|\s*sh',  # Download and execute scripts
    r'wget.*\|\s*sh',  # Download and execute scripts
    r'nc\s+-l',  # Netcat listener (reverse shell)
    r'dd\s+if=/dev/zero',  # Disk fill attack
    r'mkfifo.*nc',  # Named pipe reverse shell
    r'/dev/tcp/',  # Bash TCP connections
    r'eval\s*\$\(',  # Eval with command substitution
    r'sudo\s+',  # Privilege escalation (container runs as 1000:1000)
    r'su\s+',  # Switch user
    r'chmod\s+[0-7]*7[0-7]*\s+/',  # Make system files executable
    r'chown\s+.*\s+/',  # Change ownership of system files
    r'docker\s+',  # Docker-in-docker (security risk)
    r'\$\(curl',  # Command substitution with network
    r'\$\(wget',  # Command substitution with network
    r'>\s*/dev/sda',  # Write to disk devices
    r'>\s*/proc/',  # Write to proc filesystem
    r'iptables',  # Firewall modification
    r'setuid',  # Set UID bit
    r'passwd\s+',  # Password modification
]

# SECURITY: Whitelist of safe command prefixes (only these are allowed to start commands)
SAFE_COMMAND_PREFIXES = [
    'npm', 'node', 'npx', 'yarn', 'pnpm',  # Node.js
    'python', 'python3', 'pip', 'pip3', 'uvicorn', 'gunicorn', 'flask',  # Python
    'go', 'air',  # Go
    'cargo', 'rustc',  # Rust
    'dotnet',  # .NET
    'java', 'mvn', 'gradle',  # Java
    'ruby', 'bundle', 'rails',  # Ruby
    'php', 'composer',  # PHP
    'cd', 'ls', 'echo', 'sleep', 'cat', 'mkdir', 'cp', 'mv',  # Safe shell commands
    'if', 'for', 'while', 'test', '[',  # Shell control flow
]


def validate_startup_command(command: str) -> tuple[bool, Optional[str]]:
    """
    Validate startup command for security issues.

    Args:
        command: Raw startup command from TESSLATE.md

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

    # Extract all command words (split by common delimiters)
    command_words = re.findall(r'\b[\w\-\.]+', command)

    # Check that all commands start with safe prefixes
    # Split command by &&, ||, ;, and | to get individual commands
    commands = re.split(r'[;&|]+', command)

    for cmd in commands:
        cmd = cmd.strip()
        if not cmd or cmd.startswith('#'):  # Skip empty lines and comments
            continue

        # Get the first word (actual command)
        first_word = cmd.split()[0] if cmd.split() else ''

        # Allow shell built-ins and safe prefixes
        if first_word and not any(first_word.startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES):
            logger.warning(f"[SECURITY] Command '{first_word}' not in whitelist")
            return False, f"Command '{first_word}' is not in the safe command whitelist"

    # Check command length (prevent resource exhaustion)
    if len(command) > 10000:
        return False, "Command is too long (max 10000 characters)"

    logger.info(f"[SECURITY] ✅ Command validated successfully")
    return True, None


class BaseConfig:
    """Represents parsed configuration from a TESSLATE.md file."""

    def __init__(self):
        self.start_command: Optional[str] = None
        self.framework: Dict[str, str] = {}
        self.tech_stack: List[str] = []
        self.structure_type: str = "single"  # 'single' or 'multi'
        self.directories: List[str] = []
        self.port: int = 3000  # Default port (Next.js, Vite, most dev servers)
        self.is_validated: bool = False
        self.validation_error: Optional[str] = None

    def validate(self) -> bool:
        """
        Validate the configuration, especially startup command security.

        Returns:
            True if valid, False otherwise
        """
        if not self.start_command:
            # No start command = use safe default
            self.is_validated = True
            return True

        is_valid, error = validate_startup_command(self.start_command)
        self.is_validated = is_valid
        self.validation_error = error

        if not is_valid:
            logger.error(f"[SECURITY] ❌ Invalid startup command: {error}")

        return is_valid

    def to_dict(self) -> Dict[str, Any]:
        return {
            'start_command': self.start_command,
            'framework': self.framework,
            'tech_stack': self.tech_stack,
            'structure_type': self.structure_type,
            'directories': self.directories,
            'port': self.port,
            'is_validated': self.is_validated,
            'validation_error': self.validation_error,
        }


def parse_tesslate_md(content: str) -> BaseConfig:
    """
    Parse TESSLATE.md content and extract configuration.

    Args:
        content: Raw TESSLATE.md file content

    Returns:
        BaseConfig object with parsed data
    """
    config = BaseConfig()

    # Extract Start Command section
    start_command_match = re.search(
        r'##\s*Development Server.*?```bash\n(.*?)```',
        content,
        re.DOTALL | re.IGNORECASE
    )
    if start_command_match:
        config.start_command = start_command_match.group(1).strip()
        logger.debug(f"[BASE-CONFIG] Extracted start command: {config.start_command[:100]}...")

    # Extract Framework Configuration
    framework_match = re.search(
        r'##\s*Framework Configuration.*?\n(.*?)(?=\n##|\Z)',
        content,
        re.DOTALL | re.IGNORECASE
    )
    if framework_match:
        framework_text = framework_match.group(1)
        # Parse key-value pairs like "**Frontend**: Vite + React"
        for line in framework_text.split('\n'):
            if '**' in line and ':' in line:
                key_match = re.search(r'\*\*(.+?)\*\*:\s*(.+)', line)
                if key_match:
                    key = key_match.group(1).strip().lower()
                    value = key_match.group(2).strip()
                    config.framework[key] = value

        logger.debug(f"[BASE-CONFIG] Framework config: {config.framework}")

    # Extract Port (look for "**Port**: 5173" or similar patterns)
    port_match = re.search(
        r'\*\*Port\*\*:\s*(\d+)',
        content,
        re.IGNORECASE
    )
    if port_match:
        config.port = int(port_match.group(1))
        logger.debug(f"[BASE-CONFIG] Extracted port: {config.port}")
    else:
        # Try to infer from framework
        if 'vite' in content.lower() or 'react' in content.lower():
            config.port = 5173  # Vite default
        elif 'next' in content.lower():
            config.port = 3000  # Next.js default
        elif 'fastapi' in content.lower() or 'uvicorn' in content.lower():
            config.port = 8000  # FastAPI default
        logger.debug(f"[BASE-CONFIG] Using default/inferred port: {config.port}")

    # Detect structure type (single-dir vs multi-dir)
    # Multi-dir if has "frontend/" or "backend/" in file structure
    if re.search(r'(frontend/|backend/|client/|server/)', content, re.IGNORECASE):
        config.structure_type = "multi"

        # Extract directory names
        dir_matches = re.findall(r'^(frontend|backend|client|server|api)/', content, re.MULTILINE | re.IGNORECASE)
        config.directories = list(set(d.lower() for d in dir_matches))

        logger.info(f"[BASE-CONFIG] Detected multi-directory structure: {config.directories}")
    else:
        config.structure_type = "single"
        logger.info(f"[BASE-CONFIG] Detected single-directory structure")

    # Extract tech stack
    tech_stack_match = re.search(
        r'\*\*Tech Stack:\*\*.*?\n((?:- .*\n)+)',
        content,
        re.DOTALL
    )
    if tech_stack_match:
        tech_lines = tech_stack_match.group(1).strip().split('\n')
        config.tech_stack = [line.strip('- ').strip() for line in tech_lines]
        logger.debug(f"[BASE-CONFIG] Tech stack: {config.tech_stack}")

    return config


def get_base_config_from_cache(base_slug: str) -> Optional[BaseConfig]:
    """
    Read and parse TESSLATE.md from base cache volume (marketplace bases).

    Args:
        base_slug: Base slug (e.g., 'nextjs-15', 'vite-react-fastapi')

    Returns:
        BaseConfig object or None if not found
    """
    import docker

    try:
        client = docker.from_env()

        # Read TESSLATE.md from cache volume using temporary container
        command = f"cat /cache/{base_slug}/TESSLATE.md"

        result = client.containers.run(
            image="alpine",
            command=["sh", "-c", command],
            volumes={
                'tesslate-base-cache': {
                    'bind': '/cache',
                    'mode': 'ro'
                }
            },
            remove=True,
            stdout=True,
            stderr=False
        )

        content = result.decode('utf-8', errors='replace')
        config = parse_tesslate_md(content)

        # SECURITY: Validate the configuration
        if not config.validate():
            logger.error(f"[SECURITY] ❌ Config validation failed for {base_slug}: {config.validation_error}")
            return None

        logger.info(f"[BASE-CONFIG] ✅ Successfully parsed and validated config for {base_slug}")
        return config

    except Exception as e:
        logger.warning(f"[BASE-CONFIG] Could not read TESSLATE.md for {base_slug}: {e}")
        return None


async def get_base_config_from_volume(project_slug: str) -> Optional[BaseConfig]:
    """
    Read and parse TESSLATE.md from the shared projects volume.

    With the new architecture, orchestrator has direct filesystem access
    to /projects/{project-slug}/, so no temp containers needed.

    Args:
        project_slug: Project slug (e.g., 'my-project-abc123')

    Returns:
        BaseConfig object or None if not found
    """
    try:
        # NEW ARCHITECTURE: Direct filesystem access via shared projects-data volume
        # Orchestrator has this mounted at /projects
        tesslate_path = Path(f"/projects/{project_slug}/TESSLATE.md")

        if tesslate_path.exists():
            content = tesslate_path.read_text(encoding='utf-8')
            config = parse_tesslate_md(content)

            # SECURITY: Validate the configuration (CRITICAL for user-provided repos!)
            if not config.validate():
                logger.error(f"[SECURITY] ❌ Config validation failed for {project_slug}: {config.validation_error}")
                return None

            logger.info(f"[BASE-CONFIG] ✅ Successfully parsed and validated config from /projects/{project_slug}")
            return config
        else:
            logger.debug(f"[BASE-CONFIG] No TESSLATE.md found at {tesslate_path}")
            return None

    except Exception as e:
        logger.debug(f"[BASE-CONFIG] Could not read TESSLATE.md for {project_slug}: {e}")
        return None


def generate_startup_command(config: Optional[BaseConfig]) -> List[str]:
    """
    Generate docker-compose command array from base configuration.

    This is the ROBUST, language-agnostic solution that replaces hardcoded commands.

    SECURITY: Only uses validated commands from config, or safe defaults.

    Args:
        config: Parsed and VALIDATED BaseConfig, or None for safe defaults

    Returns:
        List of command args for docker-compose (e.g., ['sh', '-c', '...'])
    """
    # Use custom command if available and validated
    if config and config.start_command and config.is_validated:
        logger.info(f"[BASE-CONFIG] ✅ Using validated custom start command from TESSLATE.md")
        return ['sh', '-c', config.start_command]

    # Fallback: Safe, generic startup command
    # This handles:
    # - Bases without TESSLATE.md
    # - Invalid/dangerous TESSLATE.md commands
    # - Custom repos without configuration
    logger.info(f"[BASE-CONFIG] Using safe generic startup command")

    generic_command = (
        # CRITICAL: Export PATH to include user bin directories (for pip, npm global, etc.)
        # This ensures Python packages installed with --user and other user-level tools work
        'export PATH="$HOME/.local/bin:/home/node/.local/bin:$PATH" && '
        # Install dependencies (only if missing) for all supported languages
        'echo "[TESSLATE] Starting dev environment..." && '
        # Node.js (check multiple package file locations for multi-dir projects)
        'if [ -f "package.json" ]; then '
        '  [ ! -d "node_modules" ] && echo "[TESSLATE] Installing Node.js dependencies..." && npm install || true; '
        'fi && '
        'if [ -f "frontend/package.json" ]; then '
        '  [ ! -d "frontend/node_modules" ] && echo "[TESSLATE] Installing frontend dependencies..." && cd frontend && npm install && cd .. || true; '
        'fi && '
        # Python (install to user directory for consistency)
        'if [ -f "requirements.txt" ]; then '
        '  echo "[TESSLATE] Installing Python dependencies..." && pip install --user -r requirements.txt || true; '
        'fi && '
        'if [ -f "backend/requirements.txt" ]; then '
        '  echo "[TESSLATE] Installing backend dependencies..." && cd backend && pip install --user -r requirements.txt && cd .. || true; '
        'fi && '
        # Go
        'if [ -f "go.mod" ]; then '
        '  echo "[TESSLATE] Downloading Go dependencies..." && go mod download || true; '
        'fi && '
        # Start dev server (try to detect the correct command)
        'echo "[TESSLATE] Starting development server..." && '
        '('
        # Try package.json scripts (most common)
        '  if [ -f "package.json" ]; then npm run dev; '
        # Try frontend subdirectory
        '  elif [ -f "frontend/package.json" ]; then cd frontend && npm run dev; '
        # Try Python servers
        '  elif [ -f "main.py" ]; then python3 main.py; '
        '  elif [ -f "app.py" ]; then python3 app.py; '
        # Try Go
        '  elif [ -f "main.go" ]; then go run .; '
        # Fallback: just keep container alive
        '  else echo "[TESSLATE] No startup method detected. Container is ready for manual commands." && sleep infinity; '
        '  fi'
        ')'
    )

    return ['sh', '-c', generic_command]
