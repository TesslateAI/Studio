"""
Startup Script Generator

Generates shell scripts for starting development servers based on
TESSLATE.md configuration. Supports multiple frameworks and architectures.
"""

from typing import Optional
import os
import logging
from .tesslate_parser import TesslateConfig

logger = logging.getLogger(__name__)


class StartupGenerator:
    """Generates startup scripts for project dev containers."""

    @staticmethod
    def generate_script(config: TesslateConfig, project_path: str) -> str:
        """
        Generate a startup script based on TesslateConfig.

        Args:
            config: Parsed TESSLATE configuration
            project_path: Absolute path to project directory

        Returns:
            Shell script content as string
        """
        script_lines = [
            "#!/bin/sh",
            "set -e",
            "",
            "# Generated startup script from TESSLATE.md",
            f"# Framework: {config.framework}",
            f"# Port: {config.port}",
            "",
            "cd /app",
            ""
        ]

        # Add environment variables if any
        if config.environment_vars:
            script_lines.append("# Environment Variables")
            for key, value in config.environment_vars.items():
                script_lines.append(f"export {key}={value}")
            script_lines.append("")

        # Add startup commands
        script_lines.append("# Start Development Server")
        script_lines.extend(config.start_command.split('\n'))

        script_content = '\n'.join(script_lines)
        return script_content

    @staticmethod
    def write_script(config: TesslateConfig, project_path: str) -> str:
        """
        Generate and write startup script to filesystem.

        Args:
            config: Parsed TESSLATE configuration
            project_path: Absolute path to project directory

        Returns:
            Path to generated script
        """
        script_content = StartupGenerator.generate_script(config, project_path)
        script_path = os.path.join(project_path, "start.sh")

        try:
            with open(script_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(script_content)

            # Make executable
            os.chmod(script_path, 0o755)

            logger.info(f"Generated startup script: {script_path}")
            return script_path

        except Exception as e:
            logger.error(f"Failed to write startup script: {e}")
            raise

    @staticmethod
    def generate_default_script(project_path: str, framework: str = "vite") -> str:
        """
        Generate a default startup script for a framework.

        Args:
            project_path: Absolute path to project directory
            framework: Framework name (vite, nextjs, etc.)

        Returns:
            Path to generated script
        """
        from .tesslate_parser import TesslateParser

        config = TesslateParser.get_default_config(framework)
        return StartupGenerator.write_script(config, project_path)
