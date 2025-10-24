"""
Framework Detection and Configuration Service

Detects project framework (Vite, Next.js, CRA, etc.) and provides
framework-specific configuration for dev server startup.
"""
import json
from typing import Dict, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class FrameworkConfig:
    """Framework-specific configuration."""

    def __init__(
        self,
        framework: str,
        dev_command: str,
        port: int,
        config_file: str,
        required_vite_config: Optional[str] = None,
        required_next_config: Optional[str] = None
    ):
        self.framework = framework
        self.dev_command = dev_command
        self.port = port
        self.config_file = config_file
        self.required_vite_config = required_vite_config
        self.required_next_config = required_next_config


# Framework configurations
FRAMEWORK_CONFIGS = {
    "vite": FrameworkConfig(
        framework="vite",
        dev_command="npm run dev",
        port=5173,
        config_file="vite.config.js",
        required_vite_config="""import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
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
    ),
    "nextjs": FrameworkConfig(
        framework="nextjs",
        dev_command="npm run dev",
        port=3000,
        config_file="next.config.js",
        required_next_config="""/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable React strict mode for development
  reactStrictMode: true,

  // Configure hostname for external access (required for Docker/K8s)
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Access-Control-Allow-Origin',
            value: '*',
          },
        ],
      },
    ]
  },

  // Development server configuration
  devIndicators: {
    buildActivity: true,
    buildActivityPosition: 'bottom-right',
  },
}

module.exports = nextConfig
"""
    ),
    "create-react-app": FrameworkConfig(
        framework="create-react-app",
        dev_command="npm start",
        port=3000,
        config_file="package.json",
    ),
    "unknown": FrameworkConfig(
        framework="unknown",
        dev_command="npm run dev",
        port=5173,
        config_file="package.json",
    ),
}


class FrameworkDetector:
    """Detects project framework and provides configuration."""

    @staticmethod
    def detect_from_package_json(package_json_content: str) -> Tuple[str, FrameworkConfig]:
        """
        Detect framework from package.json content.

        Args:
            package_json_content: Content of package.json file

        Returns:
            Tuple of (framework_name, framework_config)
        """
        try:
            pkg = json.loads(package_json_content)
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            scripts = pkg.get('scripts', {})

            # Detect Next.js
            if 'next' in deps:
                logger.info("[FRAMEWORK] Detected Next.js project")
                return ("nextjs", FRAMEWORK_CONFIGS["nextjs"])

            # Detect Vite
            if 'vite' in deps:
                logger.info("[FRAMEWORK] Detected Vite project")
                return ("vite", FRAMEWORK_CONFIGS["vite"])

            # Detect Create React App
            if 'react-scripts' in deps:
                logger.info("[FRAMEWORK] Detected Create React App project")
                return ("create-react-app", FRAMEWORK_CONFIGS["create-react-app"])

            # Default to Vite (most common in Tesslate)
            logger.warning("[FRAMEWORK] Unknown framework, defaulting to Vite configuration")
            return ("unknown", FRAMEWORK_CONFIGS["unknown"])

        except Exception as e:
            logger.error(f"[FRAMEWORK] Error detecting framework: {e}")
            return ("unknown", FRAMEWORK_CONFIGS["unknown"])

    @staticmethod
    def get_dev_server_command(framework: str, port: Optional[int] = None) -> str:
        """
        Get the dev server startup command for a framework.

        Args:
            framework: Framework name (vite, nextjs, etc.)
            port: Optional custom port

        Returns:
            Command to start dev server
        """
        config = FRAMEWORK_CONFIGS.get(framework, FRAMEWORK_CONFIGS["unknown"])

        if framework == "nextjs":
            # Next.js requires PORT environment variable
            port_num = port or config.port
            return f"PORT={port_num} npm run dev"
        elif framework == "vite":
            return "npm run dev"
        elif framework == "create-react-app":
            port_num = port or config.port
            return f"PORT={port_num} npm start"
        else:
            return config.dev_command

    @staticmethod
    def get_required_config_content(framework: str) -> Optional[str]:
        """
        Get the required configuration file content for a framework.

        Args:
            framework: Framework name

        Returns:
            Configuration file content or None
        """
        config = FRAMEWORK_CONFIGS.get(framework, FRAMEWORK_CONFIGS["unknown"])

        if framework == "vite":
            return config.required_vite_config
        elif framework == "nextjs":
            return config.required_next_config
        else:
            return None

    @staticmethod
    def get_framework_port(framework: str) -> int:
        """
        Get the default port for a framework.

        Args:
            framework: Framework name

        Returns:
            Default port number
        """
        config = FRAMEWORK_CONFIGS.get(framework, FRAMEWORK_CONFIGS["unknown"])
        return config.port

    @staticmethod
    def is_framework_supported(framework: str) -> bool:
        """
        Check if a framework is fully supported by Tesslate Studio.

        Args:
            framework: Framework name

        Returns:
            True if fully supported
        """
        # Currently, Vite is the primary supported framework
        # Next.js and CRA have experimental support
        return framework in ["vite", "nextjs", "create-react-app"]

    @staticmethod
    def get_compatibility_message(framework: str) -> str:
        """
        Get a compatibility message for the framework.

        Args:
            framework: Framework name

        Returns:
            Human-readable compatibility message
        """
        if framework == "vite":
            return "Fully supported - Optimized for Tesslate Studio"
        elif framework == "nextjs":
            return "Experimental support - Some features may not work correctly"
        elif framework == "create-react-app":
            return "Experimental support - Consider migrating to Vite for better performance"
        else:
            return "Unknown framework - May require manual configuration"
