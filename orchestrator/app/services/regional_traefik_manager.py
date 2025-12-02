"""
Regional Traefik Manager

Manages multiple regional Traefik instances for scalability.
Each regional Traefik handles a subset of projects (250 max) to avoid
the Docker network-per-container limit of ~1000 networks.

Architecture:
- Main Traefik: Entry point, routes to regional Traefiks
- Regional Traefiks: Each joins up to 250 project networks
- Sequential fill: regional-0 fills to 250, then regional-1, etc.
"""

import asyncio
import logging
import os
import yaml
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuration
PROJECTS_PER_REGIONAL = 250  # Conservative limit (Docker supports ~1000 networks)
REGIONAL_TRAEFIK_BASE_PORT = 8081  # Base port for regional Traefik dashboards


class RegionalTraefikManager:
    """
    Manages lifecycle of regional Traefik instances.

    Sequential fill: Fills regional-0 to 250 projects, then regional-1, etc.
    """

    def __init__(self):
        self.compose_dir = Path("docker-compose-regional-traefiks")
        self.compose_dir.mkdir(exist_ok=True)
        self.running_regionals: Dict[int, bool] = {}  # regional_index -> is_running
        self.project_counts: Dict[int, int] = {}  # regional_index -> project_count
        self.project_assignments: Dict[str, int] = {}  # project_slug -> regional_index
        logger.info("[REGIONAL-TRAEFIK] Manager initialized (sequential fill)")

    def get_regional_index_for_project(self, project_slug: str) -> int:
        """
        Determine which regional Traefik should handle this project.

        Sequential fill: Assigns to first regional with capacity (< 250 projects)

        Args:
            project_slug: Project slug identifier

        Returns:
            Regional Traefik index (0-based)
        """
        # Check if project already assigned
        if project_slug in self.project_assignments:
            return self.project_assignments[project_slug]

        # Find first regional with capacity
        regional_index = 0
        while self.project_counts.get(regional_index, 0) >= PROJECTS_PER_REGIONAL:
            regional_index += 1
            if regional_index > 100:  # Safety limit
                logger.error("[REGIONAL-TRAEFIK] Exceeded maximum regional Traefiks (100)")
                raise RuntimeError("Maximum regional Traefik limit exceeded")

        # Assign project to this regional
        self.project_assignments[project_slug] = regional_index
        self.project_counts[regional_index] = self.project_counts.get(regional_index, 0) + 1

        logger.info(f"[REGIONAL-TRAEFIK] Assigned {project_slug} to regional-{regional_index} "
                   f"({self.project_counts[regional_index]}/{PROJECTS_PER_REGIONAL} projects)")

        return regional_index

    def release_project(self, project_slug: str) -> None:
        """
        Release a project's regional assignment (called when project is deleted).

        Args:
            project_slug: Project slug to release
        """
        if project_slug in self.project_assignments:
            regional_index = self.project_assignments[project_slug]
            del self.project_assignments[project_slug]
            if regional_index in self.project_counts:
                self.project_counts[regional_index] = max(0, self.project_counts[regional_index] - 1)
            logger.info(f"[REGIONAL-TRAEFIK] Released {project_slug} from regional-{regional_index}")

    def get_regional_traefik_name(self, regional_index: int) -> str:
        """Get the Docker container name for a regional Traefik."""
        return f"tesslate-traefik-regional-{regional_index}"

    def get_regional_network_name(self) -> str:
        """Get the shared network name for regional Traefiks."""
        return "tesslate-regional-traefik-network"

    async def _generate_regional_compose_config(self, regional_index: int) -> Dict:
        """
        Generate docker-compose configuration for a regional Traefik instance.

        Args:
            regional_index: Index of the regional Traefik (0-based)

        Returns:
            Docker Compose configuration dictionary
        """
        container_name = self.get_regional_traefik_name(regional_index)
        dashboard_port = REGIONAL_TRAEFIK_BASE_PORT + regional_index

        # Regional Traefik config
        compose_config = {
            'version': '3.8',
            'networks': {
                self.get_regional_network_name(): {
                    'external': True,
                    'name': self.get_regional_network_name()
                }
            },
            'services': {
                'traefik': {
                    'image': 'traefik:v2.10',
                    'container_name': container_name,
                    'restart': 'unless-stopped',
                    'networks': [self.get_regional_network_name()],
                    'ports': [
                        # Dashboard for this regional Traefik (for debugging)
                        f"{dashboard_port}:8080"
                    ],
                    'volumes': [
                        # Docker socket for service discovery
                        '/var/run/docker.sock:/var/run/docker.sock:ro'
                    ],
                    'command': [
                        '--api.insecure=true',
                        '--api.dashboard=true',
                        '--providers.docker=true',
                        '--providers.docker.exposedbydefault=false',
                        '--providers.docker.network=' + self.get_regional_network_name(),
                        # Regional Traefik listens on port 80 (internal only, not exposed to host)
                        '--entrypoints.web.address=:80',
                        # Transport-level timeouts for slow-starting dev servers (Next.js takes 2+ min)
                        # Traefik 2.x requires static config for timeouts (no label support)
                        '--entryPoints.web.transport.respondingTimeouts.readTimeout=600s',
                        '--entryPoints.web.transport.respondingTimeouts.writeTimeout=600s',
                        '--entryPoints.web.transport.respondingTimeouts.idleTimeout=600s',
                        # Log level
                        '--log.level=INFO',
                        # Enable access logs for debugging
                        '--accesslog=true'
                    ],
                    'labels': {
                        'com.tesslate.type': 'regional-traefik',
                        'com.tesslate.regional-index': str(regional_index)
                    }
                }
            }
        }

        return compose_config

    async def ensure_regional_network_exists(self) -> None:
        """
        Ensure the shared network for regional Traefiks exists.
        This network allows main Traefik to communicate with regional Traefiks.
        """
        network_name = self.get_regional_network_name()

        try:
            # Check if network exists
            process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'inspect', network_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            if process.returncode == 0:
                logger.debug(f"[REGIONAL-TRAEFIK] Network {network_name} already exists")
                return

            # Create network
            logger.info(f"[REGIONAL-TRAEFIK] Creating network {network_name}...")
            create_process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'create', network_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await create_process.communicate()

            if create_process.returncode == 0:
                logger.info(f"[REGIONAL-TRAEFIK] ✅ Network {network_name} created")
            else:
                logger.error(f"[REGIONAL-TRAEFIK] Failed to create network {network_name}")

        except Exception as e:
            logger.error(f"[REGIONAL-TRAEFIK] Error ensuring network exists: {e}")

    async def start_regional_traefik(self, regional_index: int) -> None:
        """
        Start a regional Traefik instance.

        Args:
            regional_index: Index of the regional Traefik to start
        """
        container_name = self.get_regional_traefik_name(regional_index)

        # Check if already running
        if await self._is_regional_running(regional_index):
            logger.debug(f"[REGIONAL-TRAEFIK] {container_name} already running")
            self.running_regionals[regional_index] = True
            return

        # Ensure shared network exists
        await self.ensure_regional_network_exists()

        # Generate compose file
        compose_config = await self._generate_regional_compose_config(regional_index)
        compose_file = self.compose_dir / f"regional-{regional_index}.yml"

        with open(compose_file, 'w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"[REGIONAL-TRAEFIK] Generated compose file: {compose_file}")
        logger.info(f"[REGIONAL-TRAEFIK] Timeout configuration: readTimeout=600s, writeTimeout=600s, idleTimeout=600s")
        logger.info(f"[REGIONAL-TRAEFIK] Starting {container_name}...")

        try:
            # Start using docker-compose
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',
                '-f', str(compose_file),
                '-p', f'regional-traefik-{regional_index}',
                'up', '-d',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[REGIONAL-TRAEFIK] Failed to start {container_name}: {error_msg}")
                raise RuntimeError(f"Failed to start regional Traefik: {error_msg}")

            logger.info(f"[REGIONAL-TRAEFIK] ✅ {container_name} started successfully")
            logger.info(f"[REGIONAL-TRAEFIK] Dashboard: http://localhost:{REGIONAL_TRAEFIK_BASE_PORT + regional_index}")

            # Wait for regional Traefik to be ready (max 10 seconds)
            logger.info(f"[REGIONAL-TRAEFIK] Waiting for {container_name} to be ready...")
            await self._wait_for_regional_ready(regional_index, max_wait=10)

            # Connect main Traefik to regional network (so it can route to regionals)
            await self._connect_main_traefik_to_regional_network()

            self.running_regionals[regional_index] = True

        except Exception as e:
            logger.error(f"[REGIONAL-TRAEFIK] Error starting {container_name}: {e}", exc_info=True)
            raise

    async def _is_regional_running(self, regional_index: int) -> bool:
        """Check if a regional Traefik is currently running."""
        container_name = self.get_regional_traefik_name(regional_index)

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'inspect', '-f', '{{.State.Running}}', container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                is_running = stdout.decode().strip() == 'true'
                return is_running

            return False

        except Exception as e:
            logger.debug(f"[REGIONAL-TRAEFIK] Error checking if {container_name} running: {e}")
            return False

    async def _wait_for_regional_ready(self, regional_index: int, max_wait: int = 10) -> None:
        """
        Wait for a regional Traefik to be ready to accept connections.

        Args:
            regional_index: Index of the regional Traefik
            max_wait: Maximum seconds to wait
        """
        container_name = self.get_regional_traefik_name(regional_index)
        network_name = self.get_regional_network_name()

        for attempt in range(max_wait * 2):  # Check every 0.5 seconds
            try:
                # Check if container is running
                if not await self._is_regional_running(regional_index):
                    logger.warning(f"[REGIONAL-TRAEFIK] {container_name} not running on attempt {attempt + 1}")
                    await asyncio.sleep(0.5)
                    continue

                # Try to connect to Traefik API
                process = await asyncio.create_subprocess_exec(
                    'docker', 'exec', container_name, 'wget', '-q', '-O-', 'http://localhost:8080/api/overview',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2.0)

                if process.returncode == 0:
                    logger.info(f"[REGIONAL-TRAEFIK] ✅ {container_name} is ready!")
                    return

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.debug(f"[REGIONAL-TRAEFIK] Waiting for {container_name}: {e}")

            await asyncio.sleep(0.5)

        logger.warning(f"[REGIONAL-TRAEFIK] {container_name} did not become ready in {max_wait}s")

    async def _connect_main_traefik_to_regional_network(self) -> None:
        """
        Connect main Traefik to the regional network so it can route to regional Traefiks.
        """
        network_name = self.get_regional_network_name()

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'connect', network_name, 'tesslate-traefik',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            if process.returncode == 0:
                logger.info(f"[REGIONAL-TRAEFIK] ✅ Main Traefik connected to {network_name}")
            else:
                # Already connected is not an error
                logger.debug(f"[REGIONAL-TRAEFIK] Main Traefik already connected to {network_name}")

        except Exception as e:
            logger.warning(f"[REGIONAL-TRAEFIK] Error connecting main Traefik: {e}")

    async def ensure_regional_for_project(self, project_slug: str) -> int:
        """
        Ensure the appropriate regional Traefik is running for a project.
        Returns the regional index.

        Args:
            project_slug: Project slug

        Returns:
            Regional Traefik index that handles this project
        """
        regional_index = self.get_regional_index_for_project(project_slug)

        # Start regional Traefik if not running
        if not self.running_regionals.get(regional_index, False):
            await self.start_regional_traefik(regional_index)

        return regional_index

    async def stop_regional_traefik(self, regional_index: int) -> None:
        """
        Stop a regional Traefik instance.

        Args:
            regional_index: Index of the regional Traefik to stop
        """
        container_name = self.get_regional_traefik_name(regional_index)
        compose_file = self.compose_dir / f"regional-{regional_index}.yml"

        if not compose_file.exists():
            logger.warning(f"[REGIONAL-TRAEFIK] Compose file not found for {container_name}")
            return

        logger.info(f"[REGIONAL-TRAEFIK] Stopping {container_name}...")

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',
                '-f', str(compose_file),
                '-p', f'regional-traefik-{regional_index}',
                'down',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[REGIONAL-TRAEFIK] Failed to stop {container_name}: {error_msg}")
                raise RuntimeError(f"Failed to stop regional Traefik: {error_msg}")

            logger.info(f"[REGIONAL-TRAEFIK] ✅ {container_name} stopped")
            self.running_regionals[regional_index] = False

        except Exception as e:
            logger.error(f"[REGIONAL-TRAEFIK] Error stopping {container_name}: {e}", exc_info=True)
            raise


# Singleton instance
_regional_traefik_manager: Optional[RegionalTraefikManager] = None


def get_regional_traefik_manager() -> RegionalTraefikManager:
    """Get the singleton regional Traefik manager instance."""
    global _regional_traefik_manager

    if _regional_traefik_manager is None:
        _regional_traefik_manager = RegionalTraefikManager()

    return _regional_traefik_manager
