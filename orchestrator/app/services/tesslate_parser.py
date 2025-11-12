"""
TESSLATE.md Parser Service

Parses TESSLATE.md files from base repositories to extract:
- Development server startup commands
- Port configurations
- Framework information
- Stop commands

This enables dynamic project startup across different tech stacks.
"""

import re
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class TesslateConfig:
    """Configuration extracted from TESSLATE.md."""
    framework: str
    port: int
    start_command: str
    stop_command: Optional[str] = None
    environment_vars: Dict[str, str] = None

    def __post_init__(self):
        if self.environment_vars is None:
            self.environment_vars = {}


class TesslateParser:
    """Parser for TESSLATE.md configuration files."""

    # Default configurations for known frameworks
    DEFAULT_CONFIGS = {
        "vite": TesslateConfig(
            framework="vite",
            port=5173,
            start_command="npm install\nnpm run dev -- --host 0.0.0.0 --port 5173"
        ),
        "nextjs": TesslateConfig(
            framework="nextjs",
            port=3000,
            start_command="npm install\nnpm run dev -- --hostname 0.0.0.0 --port 3000"
        ),
        "react": TesslateConfig(
            framework="react",
            port=3000,
            start_command="npm install\nnpm start"
        ),
        "expo": TesslateConfig(
            framework="expo",
            port=19006,
            start_command="npm install\nnpx expo start --web"
        ),
    }

    @staticmethod
    def parse(content: str) -> TesslateConfig:
        """
        Parse TESSLATE.md content and extract configuration.

        Args:
            content: Raw content of TESSLATE.md file

        Returns:
            TesslateConfig with parsed values
        """
        try:
            # Extract framework
            framework = TesslateParser._extract_framework(content)

            # Extract port
            port = TesslateParser._extract_port(content)

            # Extract start command
            start_command = TesslateParser._extract_start_command(content)

            # Extract stop command (optional)
            stop_command = TesslateParser._extract_stop_command(content)

            # Extract environment variables (optional)
            env_vars = TesslateParser._extract_environment_vars(content)

            config = TesslateConfig(
                framework=framework,
                port=port,
                start_command=start_command,
                stop_command=stop_command,
                environment_vars=env_vars
            )

            logger.info(f"Parsed TESSLATE.md: framework={framework}, port={port}")
            return config

        except Exception as e:
            logger.warning(f"Failed to parse TESSLATE.md: {e}, using Vite defaults")
            return TesslateParser.DEFAULT_CONFIGS["vite"]

    @staticmethod
    def _extract_framework(content: str) -> str:
        """Extract framework from TESSLATE.md."""
        # Look for "**Framework**: <name>" pattern
        pattern = r'\*\*Framework\*\*:\s*([^\n]+)'
        match = re.search(pattern, content, re.IGNORECASE)

        if match:
            framework_text = match.group(1).strip()
            # Normalize to lowercase key
            framework_lower = framework_text.lower()

            if "next" in framework_lower or "nextjs" in framework_lower:
                return "nextjs"
            elif "expo" in framework_lower:
                return "expo"
            elif "vite" in framework_lower:
                return "vite"
            elif "react" in framework_lower:
                return "react"
            elif "fastapi" in framework_lower:
                return "fastapi"
            elif "go" in framework_lower:
                return "go"

            return framework_lower.split()[0]  # First word

        # Fallback: try to detect from content
        if "Expo" in content or "expo" in content.lower() or "React Native" in content:
            return "expo"
        elif "Next.js" in content or "nextjs" in content.lower():
            return "nextjs"
        elif "Vite" in content or "vite" in content.lower():
            return "vite"

        return "vite"  # Default

    @staticmethod
    def _extract_port(content: str) -> int:
        """Extract primary port from TESSLATE.md."""
        # Look for "**Port**: <number>" or "- **Port**: <number>"
        patterns = [
            r'\*\*Port\*\*:\s*(\d+)',
            r'port:\s*(\d+)',
            r'Development:\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return int(match.group(1))

        # Fallback: detect from framework
        if "Next.js" in content or "nextjs" in content.lower():
            return 3000

        return 5173  # Default Vite port

    @staticmethod
    def _extract_start_command(content: str) -> str:
        """Extract start command from TESSLATE.md."""
        # Look for "**Start Command**:" section with bash code block
        pattern = r'\*\*Start\s+Command\*\*:\s*```(?:bash)?\s*(.+?)\s*```'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            commands = match.group(1).strip()
            # Clean up: remove comments
            lines = []
            for line in commands.split('\n'):
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith('#'):
                    lines.append(line)

            return '\n'.join(lines)

        # Fallback: default Vite command
        return "npm install\nnpm run dev -- --host 0.0.0.0 --port 5173"

    @staticmethod
    def _extract_stop_command(content: str) -> Optional[str]:
        """Extract stop command from TESSLATE.md (optional)."""
        # Look for "**Stop Command**:" section
        pattern = r'\*\*Stop\s+Command\*\*:\s*```(?:bash)?\s*(.+?)\s*```'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            commands = match.group(1).strip()
            lines = []
            for line in commands.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    lines.append(line)

            return '\n'.join(lines) if lines else None

        return None

    @staticmethod
    def _extract_environment_vars(content: str) -> Dict[str, str]:
        """Extract environment variables from TESSLATE.md (optional)."""
        env_vars = {}

        # Look for "## Environment Variables" section with code block
        pattern = r'##\s*Environment\s+Variables\s*```(?:env)?\s*(.+?)\s*```'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

        if match:
            env_section = match.group(1).strip()
            # Look for KEY=value patterns
            for line in env_section.split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

        return env_vars

    @staticmethod
    def get_default_config(framework: str = "vite") -> TesslateConfig:
        """Get default configuration for a framework."""
        return TesslateParser.DEFAULT_CONFIGS.get(
            framework.lower(),
            TesslateParser.DEFAULT_CONFIGS["vite"]
        )
