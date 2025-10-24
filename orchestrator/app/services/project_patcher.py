"""
Project Configuration Patcher

Automatically detects and patches imported GitHub projects to work with Tesslate Studio.
Handles missing configurations, incompatible settings, and framework-specific requirements.
"""
import json
import os
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging
from .framework_detector import FrameworkDetector

logger = logging.getLogger(__name__)


class ProjectPatcher:
    """Patches imported projects to work with Tesslate Studio."""

    # Required Vite configuration for Tesslate Studio
    REQUIRED_VITE_CONFIG = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // Allow external connections (required for Docker)
    port: 5173,
    strictPort: true,
    allowedHosts: process.env.VITE_ALLOWED_HOSTS ? [process.env.VITE_ALLOWED_HOSTS] : 'all',
    hmr: {
      host: process.env.VITE_HMR_HOST || 'localhost',
      port: process.env.VITE_HMR_PORT ? parseInt(process.env.VITE_HMR_PORT) : 5173,
    },
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      interval: process.env.CHOKIDAR_INTERVAL ? parseInt(process.env.CHOKIDAR_INTERVAL) : 1000,
    }
  },
  optimizeDeps: {
    include: ['react', 'react-dom']
  }
})
"""

    # Minimal index.html template if missing
    MINIMAL_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Vite + React</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

    def __init__(self, project_path: str):
        """
        Initialize the patcher for a specific project.

        Args:
            project_path: Path to the project directory
        """
        self.project_path = Path(project_path)
        self.patches_applied: List[str] = []
        self.issues_detected: List[str] = []

    async def detect_project_type(self) -> Tuple[str, str]:
        """
        Detect the project type and framework.

        Returns:
            Tuple of (project_type, framework) e.g., ("frontend", "vite")
        """
        package_json_path = self.project_path / "package.json"

        if not package_json_path.exists():
            logger.warning(f"[PATCHER] No package.json found in {self.project_path}")
            return ("unknown", "unknown")

        try:
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_json_content = f.read()

            framework, config = FrameworkDetector.detect_from_package_json(package_json_content)
            return ("frontend", framework)

        except Exception as e:
            logger.error(f"[PATCHER] Error reading package.json: {e}")
            return ("unknown", "unknown")

    async def patch_vite_config(self) -> bool:
        """
        Patch or create vite.config.js with Tesslate-compatible settings.

        Returns:
            True if patched, False if no action needed
        """
        vite_config_paths = [
            self.project_path / "vite.config.js",
            self.project_path / "vite.config.ts",
        ]

        # Find existing config
        existing_config = None
        for config_path in vite_config_paths:
            if config_path.exists():
                existing_config = config_path
                break

        if existing_config:
            # Check if it already has required settings
            try:
                with open(existing_config, 'r', encoding='utf-8') as f:
                    content = f.read()

                needs_patch = False
                issues = []

                # Check for host: '0.0.0.0'
                if "host:" not in content or "0.0.0.0" not in content:
                    needs_patch = True
                    issues.append("Missing Docker-compatible host setting")

                # Check for HMR config
                if "hmr:" not in content:
                    needs_patch = True
                    issues.append("Missing HMR configuration")

                # Check for watch polling
                if "usePolling" not in content:
                    needs_patch = True
                    issues.append("Missing file watch polling (required for Docker)")

                if needs_patch:
                    logger.info(f"[PATCHER] Vite config needs patching: {', '.join(issues)}")
                    # Backup original
                    backup_path = existing_config.with_suffix(existing_config.suffix + '.backup')
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        f.write(content)

                    # Write patched config
                    with open(existing_config, 'w', encoding='utf-8') as f:
                        f.write(self.REQUIRED_VITE_CONFIG)

                    self.patches_applied.append(f"Patched {existing_config.name} (backup saved)")
                    logger.info(f"[PATCHER] ✅ Patched vite config (backup: {backup_path.name})")
                    return True
                else:
                    logger.info(f"[PATCHER] Vite config already compatible")
                    return False

            except Exception as e:
                logger.error(f"[PATCHER] Error reading vite config: {e}")
                # Fall through to create new config

        # Create new vite.config.js if missing
        vite_config_js = self.project_path / "vite.config.js"
        with open(vite_config_js, 'w', encoding='utf-8') as f:
            f.write(self.REQUIRED_VITE_CONFIG)

        self.patches_applied.append("Created vite.config.js")
        logger.info(f"[PATCHER] ✅ Created vite.config.js")
        return True

    async def patch_package_json(self) -> bool:
        """
        Ensure package.json has required scripts and dependencies.

        Returns:
            True if patched, False if no action needed
        """
        package_json_path = self.project_path / "package.json"

        if not package_json_path.exists():
            logger.warning(f"[PATCHER] No package.json found, cannot patch")
            self.issues_detected.append("Missing package.json")
            return False

        try:
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_json = json.load(f)

            modified = False

            # Ensure scripts exist
            if 'scripts' not in package_json:
                package_json['scripts'] = {}

            # Required scripts for Vite
            required_scripts = {
                'dev': 'vite',
                'build': 'vite build',
                'preview': 'vite preview'
            }

            for script_name, script_cmd in required_scripts.items():
                if script_name not in package_json['scripts']:
                    package_json['scripts'][script_name] = script_cmd
                    modified = True
                    logger.info(f"[PATCHER] Added script: {script_name}")

            if modified:
                with open(package_json_path, 'w', encoding='utf-8') as f:
                    json.dump(package_json, f, indent=2)

                self.patches_applied.append("Updated package.json scripts")
                logger.info(f"[PATCHER] ✅ Patched package.json")
                return True

            return False

        except Exception as e:
            logger.error(f"[PATCHER] Error patching package.json: {e}")
            self.issues_detected.append(f"Failed to patch package.json: {str(e)}")
            return False

    async def ensure_index_html(self) -> bool:
        """
        Ensure index.html exists at project root.

        Returns:
            True if created, False if already exists
        """
        index_html_path = self.project_path / "index.html"

        if index_html_path.exists():
            return False

        # Create minimal index.html
        with open(index_html_path, 'w', encoding='utf-8') as f:
            f.write(self.MINIMAL_INDEX_HTML)

        self.patches_applied.append("Created index.html")
        logger.info(f"[PATCHER] ✅ Created index.html")
        return True

    async def validate_project_structure(self) -> Dict[str, any]:
        """
        Validate the project structure and identify issues.

        Returns:
            Dictionary with validation results:
            - valid: bool
            - issues: List[str]
            - warnings: List[str]
        """
        issues = []
        warnings = []

        # Check for package.json
        if not (self.project_path / "package.json").exists():
            issues.append("Missing package.json")

        # Check for entry point
        possible_entry_points = [
            "src/main.jsx",
            "src/main.tsx",
            "src/index.jsx",
            "src/index.tsx",
            "src/App.jsx",
            "src/App.tsx",
        ]

        has_entry_point = any((self.project_path / entry).exists() for entry in possible_entry_points)
        if not has_entry_point:
            warnings.append("No standard React entry point found (src/main.jsx, src/index.jsx, etc.)")

        # Check for index.html
        if not (self.project_path / "index.html").exists():
            warnings.append("Missing index.html")

        # Check for Vite config
        has_vite_config = (
            (self.project_path / "vite.config.js").exists() or
            (self.project_path / "vite.config.ts").exists()
        )
        if not has_vite_config:
            warnings.append("Missing vite.config.js")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings
        }

    async def patch_nextjs_config(self) -> bool:
        """
        Patch or create next.config.js with Tesslate-compatible settings.

        Returns:
            True if patched, False if no action needed
        """
        next_config_path = self.project_path / "next.config.js"

        # Get the required Next.js config from framework detector
        required_config = FrameworkDetector.get_required_config_content("nextjs")

        if next_config_path.exists():
            # Backup existing config
            backup_path = next_config_path.with_suffix('.backup.js')
            with open(next_config_path, 'r', encoding='utf-8') as f:
                original = f.read()
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original)
            logger.info(f"[PATCHER] Backed up original next.config.js")

        # Write Tesslate-compatible config
        with open(next_config_path, 'w', encoding='utf-8') as f:
            f.write(required_config)

        self.patches_applied.append("Patched next.config.js for Tesslate compatibility")
        logger.info(f"[PATCHER] ✅ Wrote Tesslate-compatible next.config.js")
        return True

    async def auto_patch(self) -> Dict[str, any]:
        """
        Automatically detect and patch the project to work with Tesslate Studio.

        Returns:
            Dictionary with results:
            - project_type: str
            - framework: str
            - patches_applied: List[str]
            - issues_detected: List[str]
            - compatibility: str
            - success: bool
        """
        logger.info(f"[PATCHER] Starting auto-patch for {self.project_path}")

        # Detect project type
        project_type, framework = await self.detect_project_type()
        logger.info(f"[PATCHER] Detected: {project_type} / {framework}")

        # Get framework compatibility message
        compatibility = FrameworkDetector.get_compatibility_message(framework)
        logger.info(f"[PATCHER] Compatibility: {compatibility}")

        # Validate structure
        validation = await self.validate_project_structure()
        logger.info(f"[PATCHER] Validation: {validation}")

        # Apply patches based on framework
        if framework == "vite":
            await self.patch_vite_config()
            await self.patch_package_json()
            await self.ensure_index_html()
        elif framework == "nextjs":
            await self.patch_nextjs_config()
            await self.patch_package_json()
            self.issues_detected.append(
                "Next.js detected. Experimental support - The dev server will run on port 3000 instead of 5173. "
                "Some Tesslate features may not work as expected."
            )
        elif framework == "create-react-app":
            await self.patch_package_json()
            self.issues_detected.append(
                "Create React App detected. Experimental support - Consider migrating to Vite for better performance. "
                "CRA projects run on port 3000 and may have slower hot reload."
            )
        else:
            self.issues_detected.append(
                f"Unknown framework detected. Manual configuration may be required. "
                f"Tesslate Studio is optimized for Vite projects."
            )

        result = {
            "project_type": project_type,
            "framework": framework,
            "compatibility": compatibility,
            "patches_applied": self.patches_applied,
            "issues_detected": self.issues_detected + validation.get("issues", []),
            "warnings": validation.get("warnings", []),
            "success": len(self.patches_applied) > 0 or len(self.issues_detected) == 0
        }

        logger.info(f"[PATCHER] Auto-patch completed: {result}")
        return result
