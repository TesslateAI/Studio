import asyncio
import subprocess
import os
import json
import shutil
import time
from typing import Dict, Optional, List, Any
from uuid import UUID
import socket
from contextlib import closing
import aiohttp
from .config import get_settings
from .base_container_manager import BaseContainerManager
from .utils.resource_naming import get_container_name


class DockerContainerManager(BaseContainerManager):
    """
    Docker + Traefik development container manager for multi-user, multi-project environments.
    - Uses a single base image with project files mounted as volumes
    - Proper port allocation and container lifecycle management
    - Organized container naming for Docker Desktop visibility
    - Automatic cleanup and resource management
    - Uses Traefik for automatic routing with zero port conflicts
    """
    
    def __init__(self):
        self.containers: Dict[str, Dict] = {}  # project_key -> {container_name, hostname, user_id, project_id}
        self.activity_tracker: Dict[str, float] = {}  # project_key -> last_activity_timestamp
        # Detect the correct network name by checking which network Traefik is on
        self.network_name = self._detect_traefik_network()
        self.base_image_name = "tesslate-devserver:latest"
        self.container_label = "com.tesslate.devserver"
        self._docker_available = None  # Lazy check
        self._network_ready = False  # Lazy initialization
        self._base_image_ready = False  # Base image built once

        # For Docker-in-Docker: convert container paths to host paths
        # The orchestrator runs in a container with ./orchestrator mounted at /app
        # When creating child containers, we need to use host paths, not container paths
        self._detect_host_mount_path()

        print(f"[INFO] DevContainerManager initialized - Using network: {self.network_name}")
        print("[INFO] Traefik-powered zero-port-conflict architecture")

    def _detect_traefik_network(self) -> str:
        """
        Detect which network Traefik is on to ensure preview containers use the same network.
        This handles both development (tesslate-network) and production (tesslate-studio_tesslate-network).
        """
        try:
            # Try to find Traefik container
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=traefik", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip():
                traefik_container = result.stdout.strip().split('\n')[0]

                # Get Traefik's networks
                network_result = subprocess.run(
                    ["docker", "inspect", traefik_container, "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if network_result.returncode == 0:
                    networks = network_result.stdout.strip().split()
                    # Prefer networks with 'tesslate' in the name
                    for network in networks:
                        if 'tesslate' in network.lower():
                            print(f"[INFO] Detected Traefik network: {network}")
                            return network

                    # Fallback to first network if no tesslate network found
                    if networks:
                        print(f"[WARN] No tesslate network found, using: {networks[0]}")
                        return networks[0]

            # Fallback: check which tesslate network exists
            network_list = subprocess.run(
                ["docker", "network", "ls", "--filter", "name=tesslate", "--format", "{{.Name}}"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if network_list.returncode == 0 and network_list.stdout.strip():
                available_networks = network_list.stdout.strip().split('\n')
                # Prefer production network if it exists
                if 'tesslate-studio_tesslate-network' in available_networks:
                    print(f"[INFO] Using production network: tesslate-studio_tesslate-network")
                    return 'tesslate-studio_tesslate-network'
                elif available_networks:
                    print(f"[INFO] Using network: {available_networks[0]}")
                    return available_networks[0]

        except Exception as e:
            print(f"[WARN] Could not detect Traefik network: {e}")

        # Final fallback
        print("[WARN] Could not detect network, using default: tesslate-network")
        return "tesslate-network"

    def _detect_host_mount_path(self):
        """
        Detect the host paths for volume mounts in Docker-in-Docker scenarios.

        The orchestrator container has TWO separate volume mounts:
        - ./users:/app/users (user project files)
        - ./orchestrator/app:/app/app (orchestrator code)

        We need to detect both to correctly map container paths to host paths.
        """
        # Check if we're running in a container
        if os.path.exists('/.dockerenv'):
            # We're in a container - need to detect host paths for volume mounts
            try:
                # Get all mounts for this container
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{ json .Mounts }}",
                     socket.gethostname()],
                    capture_output=True,
                    text=True,
                    timeout=3
                )

                if result.returncode == 0 and result.stdout.strip():
                    import json
                    mounts = json.loads(result.stdout.strip())

                    # Find the /app/users mount
                    users_mount = None
                    for mount in mounts:
                        if mount.get('Destination') == '/app/users':
                            users_mount = mount.get('Source')
                            print(f"[INFO] Detected /app/users mount: {users_mount}")
                            break

                    if users_mount:
                        self.host_users_base = users_mount
                    else:
                        # Fallback: assume standard setup
                        self.host_users_base = "/root/Tesslate-Studio/users"
                        print(f"[WARN] Could not detect /app/users mount, using fallback: {self.host_users_base}")
                else:
                    # Fallback if docker inspect fails
                    self.host_users_base = "/root/Tesslate-Studio/users"
                    print(f"[WARN] Docker inspect failed, using fallback for users: {self.host_users_base}")

            except Exception as e:
                # Fallback if anything goes wrong
                self.host_users_base = "/root/Tesslate-Studio/users"
                print(f"[WARN] Error detecting host paths: {e}, using fallback: {self.host_users_base}")

            # Also set host_mount_base for backwards compatibility
            self.host_mount_base = "/root/Tesslate-Studio/orchestrator"
            print(f"[INFO] Host users base path: {self.host_users_base}")
        else:
            # Not in a container - paths are already host paths
            self.host_users_base = os.path.abspath("users")
            self.host_mount_base = os.path.abspath(".")
            print(f"[INFO] Running on host, users base: {self.host_users_base}")

    def _convert_to_host_path(self, container_path: str) -> str:
        """
        Convert a container path to the corresponding host path for Docker-in-Docker.

        The orchestrator container has TWO separate volume mounts:
        - ./users:/app/users (user project files)
        - ./orchestrator/app:/app/app (orchestrator code)

        We need to use the correct base path depending on which mount the path refers to.
        """
        if not hasattr(self, 'host_users_base'):
            return container_path

        # /app/users/* paths use the separate users volume mount
        if container_path.startswith('/app/users/'):
            # Extract the relative path after /app/users/
            relative_path = container_path[11:]  # Remove '/app/users/'
            host_path = os.path.join(self.host_users_base, relative_path)
            print(f"[DEBUG] Converted users path: {container_path} -> {host_path}")
            return host_path
        elif container_path.startswith('/app/'):
            # Other /app paths use the standard mount (if we need to handle them)
            relative_path = container_path[5:]  # Remove '/app/'
            host_path = os.path.join(self.host_mount_base, relative_path) if hasattr(self, 'host_mount_base') else container_path
            print(f"[DEBUG] Converted app path: {container_path} -> {host_path}")
            return host_path
        else:
            # Path doesn't start with /app, assume it's already a host path
            return container_path
    
    def _check_docker_available(self) -> bool:
        """Check if Docker is available and working (lazy/cached)."""
        if self._docker_available is not None:
            return self._docker_available
        
        try:
            print("[DEBUG] Checking Docker availability...")
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self._docker_available = False
                return False
            
            print(f"[OK] Docker available: {result.stdout.strip()}")
            
            # Test Docker daemon
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                print("[WARN] Docker daemon is not running")
                self._docker_available = False
                return False
            
            self._docker_available = True
            return True
                
        except Exception as e:
            print(f"[WARN] Docker check failed: {str(e)}")
            self._docker_available = False
            return False
    
    def _ensure_network_exists(self) -> bool:
        """Ensure the development network exists (lazy initialization)."""
        if self._network_ready:
            return True
            
        try:
            # Check if network exists
            result = subprocess.run(
                ["docker", "network", "inspect", self.network_name],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Create network
                print(f"[BUILD] Creating Docker network: {self.network_name}")
                subprocess.run(
                    ["docker", "network", "create", self.network_name],
                    capture_output=True,
                    check=True,
                    timeout=30
                )
                print(f"[OK] Network created: {self.network_name}")
            else:
                print(f"[OK] Network exists: {self.network_name}")
            
            self._network_ready = True
            return True
                
        except Exception as e:
            print(f"[WARN] Network setup warning: {e}")
            return False  # Network issues are not fatal but we should know
    
    def _ensure_base_image_exists(self) -> bool:
        """Ensure the base development image exists (built once, reused for all projects)."""
        if self._base_image_ready:
            return True
        
        try:
            # Check if base image already exists
            result = subprocess.run(
                ["docker", "images", "-q", self.base_image_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.stdout.strip():
                print(f"[OK] Base image exists: {self.base_image_name}")
                self._base_image_ready = True
                return True
            
            # Build base image only if it doesn't exist
            print(f"[BUILD] Building fast base development image (Node.js 20, ~30 seconds)...")
            dockerfile_path = self._get_dockerfile_path()

            if not os.path.exists(dockerfile_path):
                raise FileNotFoundError(f"Dockerfile not found at: {dockerfile_path}")

            build_result = subprocess.run([
                "docker", "build",
                "--pull",  # Pull latest base image
                "-f", dockerfile_path,  # Use the actual Dockerfile.devserver
                "-t", self.base_image_name,
                os.path.dirname(dockerfile_path)  # Build context is orchestrator directory
            ], capture_output=True, text=True, timeout=300)
            
            if build_result.returncode != 0:
                print(f"[ERROR] Base image build failed:")
                print(f"STDERR: {build_result.stderr}")
                print(f"STDOUT: {build_result.stdout}")
                return False
            
            print(f"[OK] Base development image built: {self.base_image_name}")
            self._base_image_ready = True
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to create base image: {e}")
            return False

    def _get_dockerfile_path(self) -> str:
        """Get the path to Dockerfile.devserver."""
        # The orchestrator code is at /app/app when running in Docker
        # or ./orchestrator/app when running locally
        # The Dockerfile.devserver is at /app/Dockerfile.devserver (Docker) or ./orchestrator/Dockerfile.devserver (local)

        # Try to determine if we're in a container or local
        if os.path.exists('/app/Dockerfile.devserver'):
            # Running in Docker container
            return '/app/Dockerfile.devserver'
        elif os.path.exists('Dockerfile.devserver'):
            # Running locally from orchestrator directory
            return 'Dockerfile.devserver'
        else:
            # Fallback: construct path relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up from app/docker_container_manager.py to orchestrator/
            orchestrator_dir = os.path.dirname(current_dir)
            return os.path.join(orchestrator_dir, 'Dockerfile.devserver')
    
    def _get_project_key(self, user_id: UUID, project_id: str) -> str:
        """Generate a unique project key for container management."""
        return f"user-{user_id}-project-{project_id}"
    
    def _get_container_name(self, user_id: UUID, project_id: str, project_slug: str = None) -> str:
        """
        Generate a descriptive container name for Docker Desktop visibility.

        Uses project slug for human-readable names (e.g., "tesslate-my-app-k3x8n2")
        Falls back to ID-based name if slug not provided.
        """
        if project_slug:
            return f"tesslate-{project_slug}"
        return get_container_name(user_id, project_id, mode="docker")
    
    def _generate_hostname(self, project_slug: str) -> str:
        """
        Generate a unique subdomain hostname for the project container.

        Args:
            project_slug: Project slug (e.g., "my-awesome-app-k3x8n2")

        Returns:
            Full hostname (e.g., "my-awesome-app-k3x8n2.studio.localhost")
        """
        from .config import get_settings
        settings = get_settings()
        # Use project slug for clean, human-readable subdomains
        return f"{project_slug}.{settings.app_domain}"

    def _get_container_access_url(self, hostname: str) -> str:
        """Get the access URL for a container using subdomain routing."""
        # Always use subdomain routing (dev/prod parity)
        # hostname is already the full subdomain like "user6-project123.studio.localhost"
        protocol = os.environ.get('APP_PROTOCOL', 'http')
        return f"{protocol}://{hostname}/"
    
    def _get_traefik_labels(self, user_id: UUID, project_id: str, hostname: str, port: int = 5173, project_slug: str = None) -> List[str]:
        """
        Generate Traefik labels for subdomain-based routing.

        Uses hostname-based routing for dev/prod parity with Kubernetes.
        No path stripping or base path configuration needed!
        """
        # Use slug for service name if available, fallback to ID-based
        if project_slug:
            service_name = f"tesslate-{project_slug}"
        else:
            service_name = get_container_name(user_id, project_id, mode="docker")
        # hostname is the full subdomain like "my-app-k3x8n2.studio.localhost"

        labels = [
            "--label", "traefik.enable=true",

            # Subdomain-based routing for HTTP (clean!)
            "--label", f"traefik.http.routers.{service_name}.rule=Host(`{hostname}`)",
            "--label", f"traefik.http.routers.{service_name}.entrypoints=web",

            # Service configuration
            "--label", f"traefik.http.services.{service_name}.loadbalancer.server.port={port}",
            "--label", f"traefik.docker.network={self.network_name}",

            # Subdomain-based routing for HTTPS (production)
            "--label", f"traefik.http.routers.{service_name}-secure.rule=Host(`{hostname}`)",
            "--label", f"traefik.http.routers.{service_name}-secure.entrypoints=websecure",
            "--label", f"traefik.http.routers.{service_name}-secure.tls=true",
            "--label", f"traefik.http.routers.{service_name}-secure.tls.certresolver={get_settings().traefik_cert_resolver}",
            "--label", f"traefik.http.routers.{service_name}-secure.tls.domains[0].main={hostname}",
        ]

        return labels
    
    def _extract_start_command_from_tesslate(self, tesslate_content: str) -> str:
        """
        Extract start command from TESSLATE.md file.

        Handles both simple commands and multi-server setups with background processes.
        Example formats:
        - Simple: npm install && npm run dev
        - Multi-server: cd backend && uvicorn main:app &\ncd frontend && npm run dev
        """
        import re

        # Look for "Start Command" section with bash code block
        # Pattern matches: **Start Command**: followed by ```bash...``` block
        pattern = r'\*\*Start Command\*\*:\s*```(?:bash)?\s*(.*?)\s*```'
        match = re.search(pattern, tesslate_content, re.DOTALL)

        if match:
            commands = match.group(1).strip()

            # Remove comment lines and empty lines, preserving command structure
            command_lines = []
            for line in commands.split('\n'):
                # Strip leading/trailing whitespace
                line = line.strip()
                # Skip empty lines and pure comment lines
                if line and not line.startswith('#'):
                    command_lines.append(line)

            if not command_lines:
                return None

            # For multi-line commands with background processes (&):
            # We need to handle directory context properly by wrapping each backgrounded command in a subshell
            # Example: "cd backend && uvicorn ... &" followed by "cd frontend && npm run dev"
            # Becomes: "(cd /app/backend && uvicorn ... &); (cd /app/frontend && npm run dev)"
            if any('&' in line for line in command_lines):
                # Process each line to ensure proper directory context
                processed_lines = []
                for line in command_lines:
                    # If line starts with 'cd ' followed by a relative path, convert to absolute
                    if line.startswith('cd ') and not line.startswith('cd /'):
                        # Extract the directory and rest of command
                        parts = line.split('&&', 1)
                        if len(parts) >= 1:
                            cd_part = parts[0].strip()
                            # Extract directory name (e.g., "cd backend" -> "backend")
                            dir_name = cd_part.replace('cd ', '').strip()
                            # Make it absolute
                            abs_cd = f'cd /app/{dir_name}'
                            if len(parts) == 2:
                                # Reconstruct with absolute path
                                line = f'{abs_cd} && {parts[1].strip()}'
                            else:
                                line = abs_cd

                    # Wrap each command in a subshell for proper isolation
                    if line.endswith(' &'):
                        # Background process - wrap in subshell
                        processed_lines.append(f'({line.rstrip(" &")} ) &')
                    else:
                        # Foreground process
                        processed_lines.append(f'({line})')

                # Join with spaces - background (&) and subshells handle separation
                # If the last command is a foreground process, it will keep the container alive
                # If all commands are background, add 'wait' to keep container alive
                has_foreground = any(not line.endswith(' &') for line in processed_lines)
                if has_foreground:
                    final_command = ' '.join(processed_lines)
                else:
                    # All background processes - need to wait for them
                    final_command = ' '.join(processed_lines) + ' wait'
            else:
                # Simple sequential commands - join with &&
                final_command = ' && '.join(command_lines)

            return final_command if final_command else None

        return None

    def _extract_port_from_tesslate(self, tesslate_content: str) -> int:
        """Extract primary port from TESSLATE.md file."""
        import re

        # Look for "Port:" in the Framework Configuration section
        # Pattern: **Port**: 3000 or **Port**: 5173
        pattern = r'\*\*Port\*\*:\s*(\d+)'
        match = re.search(pattern, tesslate_content)

        if match:
            return int(match.group(1))

        # Fallback: default Vite port
        return 5173

    def _parse_tesslate_startup_config(self, project_path: str) -> tuple[str, int]:
        """
        Parse TESSLATE.md to extract startup command and port.

        Returns:
            tuple: (start_command, port) or (None, 5173) if parsing fails
        """
        tesslate_path = os.path.join(project_path, "TESSLATE.md")

        if not os.path.exists(tesslate_path):
            print(f"[WARN] No TESSLATE.md found at {tesslate_path}")
            return None, 5173

        try:
            with open(tesslate_path, 'r', encoding='utf-8') as f:
                content = f.read()

            start_command = self._extract_start_command_from_tesslate(content)
            port = self._extract_port_from_tesslate(content)

            if start_command:
                print(f"[TESSLATE] Parsed start command: {start_command[:100]}...")
                print(f"[TESSLATE] Parsed port: {port}")
            else:
                print(f"[TESSLATE] No start command found, will use auto-detection")

            return start_command, port

        except Exception as e:
            print(f"[WARN] Failed to parse TESSLATE.md: {e}")
            return None, 5173

    async def wait_for_container_ready_traefik(self, container_name: str, timeout: int = 60, access_url: str = None) -> bool:
        """Wait for container to be ready using generic checks and HTTP health check."""
        start_time = time.time()

        # First, wait for container to be running
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format='{{.State.Running}}'", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and "true" in result.stdout:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        # Wait for server to be ready by checking logs for common ready indicators
        print(f"[WAIT] Checking container logs for server readiness...")
        logs_ready = False
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "logs", "--tail", "50", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logs = result.stdout + result.stderr
                    logs_lower = logs.lower()

                    # Look for common server ready indicators
                    ready_indicators = [
                        "listening on",         # Generic server
                        "server running",       # Generic
                        "started on",           # Express, etc.
                        "ready in",            # Vite
                        "compiled successfully", # CRA/Webpack
                        "server started",      # Next.js
                        "localhost:",          # Most dev servers
                        "0.0.0.0:",           # Servers binding to all interfaces
                        "watching for",        # File watchers
                        "dev server running",  # Generic
                    ]

                    if any(indicator in logs_lower for indicator in ready_indicators):
                        print(f"[OK] Container {container_name} logs show server is ready")
                        logs_ready = True
                        break

            except Exception as e:
                print(f"[DEBUG] Error checking logs: {e}")
                pass

            await asyncio.sleep(3)

        if not logs_ready:
            print(f"[WARN] Container {container_name} logs check timed out")
            return True  # Return True to allow container to continue - Traefik will handle routing when ready

        # If access_url provided, verify the server is actually responding to HTTP requests via Traefik
        # This works in both development and production
        if access_url:
            print(f"[WAIT] Verifying server is responsive via Traefik at {access_url}")
            http_timeout = min(30, timeout - (time.time() - start_time))  # Use remaining time or 30s max
            http_start = time.time()

            while time.time() - http_start < http_timeout:
                try:
                    async with aiohttp.ClientSession() as session:
                        # Use a very short timeout for each attempt
                        async with session.get(
                            access_url,
                            timeout=aiohttp.ClientTimeout(total=5),
                            allow_redirects=True,
                            ssl=False  # Allow self-signed certs in development
                        ) as response:
                            # Accept any response (even 404) as long as server is responding
                            # This means Traefik is routing and the container is serving requests
                            if response.status < 500:  # Any non-server-error response means it's working
                                print(f"[OK] Server is responsive via Traefik (HTTP {response.status})")
                                # Give it a bit more time to fully initialize
                                await asyncio.sleep(2)
                                return True
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    print(f"[DEBUG] Server not ready yet: {type(e).__name__}")
                    pass

                await asyncio.sleep(2)

            print(f"[WARN] Server HTTP health check timed out after {http_timeout}s, but container is running")

        return True  # Return True to allow container to continue - Traefik will handle routing when ready
    
    async def start_container(self, project_path: str, project_id: str, user_id: UUID, project_slug: str = None, skip_validation: bool = False,
                              environment_vars: Dict[str, str] = None, secrets: Dict[str, str] = None,
                              port: int = 5173, start_command: str = None) -> str:
        """
        Start a development container with flexible configuration for any template type.

        Args:
            project_path: Path to project directory
            project_id: Project ID (for internal naming)
            user_id: User ID
            project_slug: Project slug for URL generation (e.g., "my-app-k3x8n2")
            skip_validation: Skip file validation (useful for GitHub imports that will clone later)
            environment_vars: Custom environment variables to inject into container
            secrets: Sensitive environment variables (API keys, etc.) to inject securely
            port: The port the application server will listen on (default: 5173)
            start_command: Custom start command (default: "npm install && npm start")
        """
        # For backwards compatibility, generate slug from IDs if not provided
        if not project_slug:
            project_slug = f"{user_id}-{project_id}"

        # Generate unique identifiers for multi-user system
        project_key = self._get_project_key(user_id, project_id)
        container_name = self._get_container_name(user_id, project_id, project_slug)

        print(f"[START] Starting development container for user {user_id}, project {project_slug} (ID: {project_id})")
        print(f"[INFO] Project key: {project_key}")
        print(f"[INFO] Container name: {container_name}")

        # Check Docker availability first
        if not self._check_docker_available():
            raise RuntimeError(
                "Docker is not available or not running. "
                "Please install Docker Desktop and ensure it's running."
            )

        # Ensure base image exists (reuse existing if available)
        if not self._ensure_base_image_exists():
            raise RuntimeError("Failed to create base development image")

        # Ensure network exists
        if not self._ensure_network_exists():
            print("[WARN] Docker network setup failed, proceeding without custom network")

        abs_project_path = os.path.abspath(project_path)

        # Parse TESSLATE.md for startup configuration (command + port)
        tesslate_command, tesslate_port = self._parse_tesslate_startup_config(abs_project_path)

        # Use TESSLATE.md port if available, otherwise use provided port parameter
        if tesslate_port:
            port = tesslate_port

        # Ensure users directory structure exists
        # Extract user_id directory from project_path (e.g., "users/6/123" -> "users/6")
        if project_path.startswith("users/"):
            parts = project_path.split("/")
            if len(parts) >= 2:
                user_dir = os.path.join(parts[0], parts[1])  # "users/6"
                user_dir_abs = os.path.abspath(user_dir)

                # Create users directory if it doesn't exist
                users_base = os.path.abspath("users")
                if not os.path.exists(users_base):
                    os.makedirs(users_base, exist_ok=True)
                    print(f"[SETUP] Created users directory: {users_base}")

                # Create user-specific directory if it doesn't exist
                if not os.path.exists(user_dir_abs):
                    os.makedirs(user_dir_abs, exist_ok=True)
                    print(f"[SETUP] Created user directory: {user_dir_abs}")

        if not os.path.exists(abs_project_path):
            raise FileNotFoundError(f"Project directory not found: {abs_project_path}")

        # Convert container path to host path for Docker-in-Docker
        host_project_path = self._convert_to_host_path(abs_project_path)

        # Validate required files (skip for GitHub imports or TESSLATE.md-based projects)
        tesslate_md_path = os.path.join(abs_project_path, "TESSLATE.md")
        has_tesslate = os.path.exists(tesslate_md_path)

        if not skip_validation and not has_tesslate:
            # Only validate Vite files for non-TESSLATE projects
            required_files = ["package.json", "vite.config.js", "index.html"]
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(abs_project_path, f))]

            if missing_files:
                raise FileNotFoundError(f"Missing required files: {', '.join(missing_files)}")
        elif has_tesslate:
            print(f"[INFO] TESSLATE.md found, skipping Vite-specific file validation")
        else:
            print(f"[INFO] Skipping file validation (GitHub import mode)")
        
        # Stop existing container for this user and project
        await self.stop_container(project_id, user_id)
        
        # Generate hostname for Traefik routing
        hostname = self._generate_hostname(project_slug)
        
        print(f"[INFO] Container path: {abs_project_path}")
        print(f"[INFO] Host path: {host_project_path}")
        print(f"[INFO] Hostname: {hostname}")
        print(f"[INFO] Using base image: {self.base_image_name}")

        try:
            # Start container with Traefik labels for automatic routing
            print(f"[RUN] Starting Traefik-enabled container with hostname routing...")
            run_cmd = [
                "docker", "run",
                "--rm",                                                  # Remove on exit
                "--user", "root",                                        # Run as root to avoid permission issues with Windows volumes
                "--name", container_name,                                # Multi-user container name
                "-v", f"{host_project_path}:/app",                      # Source code volume (live sync!)
                # Docker labels for organization and tracking
                "--label", "com.tesslate.devserver=true",
                "--label", f"com.tesslate.devserver.user_id={user_id}",
                "--label", f"com.tesslate.devserver.project_id={project_id}",
                "--label", "com.tesslate.devserver.type=devserver",
                "--label", f"com.tesslate.devserver.hostname={hostname}",
            ]

            # Generic environment variables that templates can use
            # Subdomain routing: Container always serves from root '/'
            # No base path configuration needed!

            # Add default environment variables
            # Get APP_DOMAIN from settings for wildcard subdomain support
            from .config import get_settings
            settings = get_settings()

            # Determine WebSocket protocol based on APP_PROTOCOL
            app_protocol = os.environ.get('APP_PROTOCOL', 'http')
            ws_protocol = 'wss' if app_protocol == 'https' else 'ws'
            hmr_port = '443' if app_protocol == 'https' else '80'

            run_cmd.extend([
                "-e", "NODE_ENV=development",                           # Development mode
                "-e", f"PORT={port}",                                   # Server port

                # Universal domain variables (available to all frameworks)
                "-e", f"APP_DOMAIN={settings.app_domain}",             # Base domain for custom logic
                "-e", f"WILDCARD_DOMAIN=*.{settings.app_domain}",      # Wildcard pattern

                # Vite HMR WebSocket configuration (critical for HTTPS)
                "-e", f"VITE_HMR_PROTOCOL={ws_protocol}",              # WebSocket protocol (ws/wss)
                "-e", f"VITE_HMR_PORT={hmr_port}",                     # WebSocket port (80/443)

                # Vite-specific wildcard subdomain support
                "-e", f"VITE_ALLOWED_HOSTS=.{settings.app_domain}",    # Native Vite allowed hosts
                "-e", f"VITE_APP_DOMAIN={settings.app_domain}",        # Legacy support

                # Next.js wildcard subdomain support
                "-e", f"ALLOWED_HOSTS=.{settings.app_domain}",         # Next.js hostname validation
                "-e", "HOSTNAME=0.0.0.0",                              # Allow all hostnames

                # Go wildcard subdomain support
                "-e", f"ALLOWED_ORIGINS=*.{settings.app_domain}",      # CORS/origin validation
                "-e", "HOST=0.0.0.0",                                  # Bind to all interfaces

                # Python/FastAPI wildcard subdomain support
                "-e", f"FASTAPI_ALLOWED_HOSTS=.{settings.app_domain},*.{settings.app_domain}",  # FastAPI/Starlette
                "-e", f"CORS_ORIGINS=https://*.{settings.app_domain},http://*.{settings.app_domain}",  # CORS config

                # File watching settings from .env (required for hot reload in Docker)
                "-e", f"CHOKIDAR_USEPOLLING={os.environ.get('CHOKIDAR_USEPOLLING', 'true')}",
                "-e", f"CHOKIDAR_INTERVAL={os.environ.get('CHOKIDAR_INTERVAL', '1000')}",
                "-e", f"WATCHPACK_POLLING={os.environ.get('WATCHPACK_POLLING', 'true')}",
            ])

            # Add custom environment variables from the orchestrator
            if environment_vars:
                for key, value in environment_vars.items():
                    run_cmd.extend(["-e", f"{key}={value}"])
                    print(f"[ENV] Added environment variable: {key}")

            # Add secrets as environment variables (marked for secure handling)
            # In production, these could be mounted from Docker secrets
            if secrets:
                for key, value in secrets.items():
                    # Use Docker secret mounting in production
                    # For now, pass as environment variables but log them as secrets
                    run_cmd.extend(["-e", f"{key}={value}"])
                    print(f"[SECRET] Added secret: {key} (value hidden)")

            # Working directory, user, and detached mode
            run_cmd.extend([
                "-w", "/app",                                           # Working directory
                "--user", "root",                                        # Run as root to fix Windows volume permissions
                "-d",                                                   # Detached mode
            ])

            # Add Traefik labels for automatic service discovery
            run_cmd.extend(self._get_traefik_labels(user_id, project_id, hostname, port, project_slug))

            # Add network (required for Traefik)
            run_cmd.extend(["--network", self.network_name])

            # Determine startup command (priority order: TESSLATE.md > start_command param > start.sh > auto-detect)
            if tesslate_command:
                # Use command from TESSLATE.md (highest priority)
                print(f"[STARTUP] Using command from TESSLATE.md")
                final_command = tesslate_command
            elif start_command:
                # Use custom start command provided by parameter
                print(f"[STARTUP] Using custom start command parameter")
                final_command = start_command
            else:
                # Check for generated start.sh script
                start_sh_path = os.path.join(abs_project_path, "start.sh")
                if os.path.exists(start_sh_path):
                    print(f"[STARTUP] Found start.sh script, using dynamic startup")
                    final_command = "sh /app/start.sh"
                else:
                    # Auto-detect framework and use appropriate dev command
                    try:
                        package_json_path = os.path.join(abs_project_path, "package.json")
                        if os.path.exists(package_json_path):
                            with open(package_json_path, 'r', encoding='utf-8') as f:
                                package_json_content = f.read()

                            from .services.framework_detector import FrameworkDetector
                            framework, config = FrameworkDetector.detect_from_package_json(package_json_content)
                            dev_command = FrameworkDetector.get_dev_server_command(framework, port)

                            print(f"[FRAMEWORK] Detected {framework}, using command: {dev_command}")
                            final_command = f"npm install --silent && {dev_command}"
                        else:
                            # Fallback if package.json doesn't exist
                            print("[WARN] package.json not found, using default npm run dev")
                            final_command = "npm install --silent && npm run dev"
                    except Exception as e:
                        print(f"[WARN] Framework detection failed: {e}, using default npm run dev")
                        final_command = "npm install --silent && npm run dev"

            # Add image and startup command
            # For commands with background processes (&), we need to wrap properly
            # to ensure the container stays alive
            if '&' in final_command and not final_command.rstrip().endswith('wait'):
                # Add wait to keep container alive for background processes
                wrapped_command = f"{final_command} ; wait"
            else:
                wrapped_command = final_command

            run_cmd.extend([
                self.base_image_name,
                "sh", "-c", wrapped_command
            ])
            
            print(f"[DEBUG] Docker run command: {' '.join(run_cmd)}")
            
            try:
                run_result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)  # Longer timeout for npm install
                
                if run_result.returncode != 0:
                    error_msg = run_result.stderr or run_result.stdout
                    print(f"[ERROR] Traefik-enabled container start failed for user {user_id}, project {project_id}:")
                    print(f"STDERR: {run_result.stderr}")
                    print(f"STDOUT: {run_result.stdout}")
                    raise RuntimeError(f"Container start failed: {error_msg}")
                
                container_id = run_result.stdout.strip()
                print(f"[OK] Traefik-enabled container started: {container_id[:12]} for user {user_id}")
                
            except subprocess.TimeoutExpired:
                print(f"[ERROR] Container start timed out for user {user_id}, project {project_id}")
                raise RuntimeError("Container start timed out")
            
            # Store container info in multi-user format
            self.containers[project_key] = {
                "container_name": container_name,
                "hostname": hostname,
                "user_id": user_id,
                "project_id": project_id,
                "container_id": container_id
            }
            
            # Wait for container to be ready (check internal port via Docker)
            print(f"[WAIT] Waiting for development server to be ready...")
            access_url = self._get_container_access_url(hostname)
            if not await self.wait_for_container_ready_traefik(container_name, timeout=120, access_url=access_url):
                await self.stop_container(project_id, user_id)
                raise RuntimeError("Development server failed to become ready")
            
            print(f"[SUCCESS] Traefik-enabled development container ready for user {user_id}!")
            
            access_url = self._get_container_access_url(hostname)
            print(f"[INFO] Access your app at: {access_url}")
            print(f"[INFO] Hot reload active - edit files and see changes instantly!")
            
            return access_url
            
        except Exception as e:
            # Cleanup container on failure
            await self.stop_container(project_id, user_id)
            raise RuntimeError(f"Failed to start development container for user {user_id}, project {project_id}: {str(e)}")
    
    async def _ensure_project_dependencies(self, project_path: str) -> None:
        """Ensure project has its dependencies installed locally (for volume mount)."""
        node_modules_path = os.path.join(project_path, "node_modules")
        
        if os.path.exists(node_modules_path):
            print(f"[OK] Project dependencies already installed")
            return
        
        print(f"[INSTALL] Installing project dependencies...")
        
        # Run npm install in a temporary container to avoid host dependency issues
        temp_container_name = f"npm-install-{int(time.time())}"
        
        try:
            install_cmd = [
                "docker", "run", "--rm",
                "--name", temp_container_name,
                "-v", f"{project_path}:/app",
                "-w", "/app",
                self.base_image_name,
                "npm", "install", "--silent"
            ]
            
            install_result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=180)
            
            if install_result.returncode != 0:
                error_msg = install_result.stderr or install_result.stdout
                print(f"[ERROR] npm install failed: {error_msg}")
                raise RuntimeError(f"Failed to install project dependencies: {error_msg}")
            
            print(f"[OK] Project dependencies installed")
            
        except subprocess.TimeoutExpired:
            print("[ERROR] npm install timed out")
            raise RuntimeError("npm install timed out")
    
    async def stop_container(self, project_id: str, user_id: UUID = None) -> None:
        """Stop and remove a development container with multi-user support."""
        container_info = None
        project_key = None
        
        if user_id is not None:
            # New multi-user mode: use specific user_id and project_id
            project_key = self._get_project_key(user_id, project_id)
            print(f"[DEBUG] Looking for container with key: {project_key}")
            if project_key in self.containers:
                container_info = self.containers[project_key]
                print(f"[DEBUG] Found container info: {container_info}")
            else:
                print(f"[DEBUG] No container found with key: {project_key}")
                print(f"[DEBUG] Available containers: {list(self.containers.keys())}")
        else:
            # Backwards compatibility: search through all containers for matching project_id
            print(f"[DEBUG] Searching for project_id: {project_id} in all containers")
            for key, info in self.containers.items():
                if info.get("project_id") == project_id:
                    container_info = info
                    project_key = key
                    print(f"[DEBUG] Found matching container: {key} -> {info}")
                    break
        
        if not container_info:
            print(f"[WARN] No container found to stop for user {user_id}, project {project_id}")
            # Try to find any running containers matching this project by labels
            try:
                result = subprocess.run(
                    ["docker", "ps", "-a", "--filter", f"label=com.tesslate.devserver.project_id={project_id}",
                     "--filter", f"label=com.tesslate.devserver.user_id={user_id}", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    container_name = result.stdout.strip().split('\n')[0]
                    print(f"[DEBUG] Found container by labels: {container_name}")
                    subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
                    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=10)
                    print(f"[OK] Force cleaned up container: {container_name}")
                else:
                    print(f"[DEBUG] No matching container found by labels")
            except Exception as e:
                print(f"[DEBUG] Force cleanup failed: {e}")
            return
        
        container_name = container_info["container_name"]
        hostname = container_info.get("hostname")
        
        print(f"[STOP] Stopping container: {container_name}")
        
        try:
            # Stop container gracefully
            subprocess.run([
                "docker", "stop", container_name
            ], capture_output=True, timeout=30)
            
            # Remove container (should auto-remove with --rm flag)
            subprocess.run([
                "docker", "rm", "-f", container_name
            ], capture_output=True, timeout=10)
            
            print(f"[OK] Container stopped: {container_name}")
            
        except Exception as e:
            print(f"[WARN] Error stopping container {container_name}: {e}")
            
            # Force remove if graceful stop failed
            try:
                subprocess.run([
                    "docker", "rm", "-f", container_name
                ], capture_output=True, timeout=10)
            except Exception:
                pass
        
        # Clean up tracking
        if project_key:
            self.containers.pop(project_key, None)
        
        # Log cleanup
        if hostname:
            print(f"[CLEANUP] Stopped container with hostname: {hostname}")
    
    async def restart_container(self, project_path: str, project_id: str, user_id: UUID) -> str:
        """Restart a development container with multi-user support."""
        print(f"[RESTART] Restarting development container for user {user_id}, project {project_id}")
        await self.stop_container(project_id, user_id)
        return await self.start_container(project_path, project_id, user_id)
    
    def get_container_url(self, project_id: str, user_id: UUID = None) -> Optional[str]:
        """Get the URL for a project's development container with multi-user support."""
        container_info = None
        
        if user_id is not None:
            # New multi-user mode: use specific user_id and project_id
            project_key = self._get_project_key(user_id, project_id)
            if project_key in self.containers:
                container_info = self.containers[project_key]
        else:
            # Backwards compatibility: search through all containers for matching project_id
            for key, info in self.containers.items():
                if info.get("project_id") == project_id:
                    container_info = info
                    break
        
        if container_info and container_info.get("hostname"):
            return self._get_container_access_url(container_info['hostname'])
        return None
    
    async def get_container_status(self, project_id: str, user_id: UUID = None, project_slug: str = None) -> Dict[str, Any]:
        """Get detailed status of a development container with multi-user support."""
        container_info = None

        if user_id is not None:
            # New multi-user mode: use specific user_id and project_id
            project_key = self._get_project_key(user_id, project_id)
            if project_key in self.containers:
                container_info = self.containers[project_key]
        else:
            # Backwards compatibility: search through all containers for matching project_id
            for key, info in self.containers.items():
                if info.get("project_id") == project_id:
                    container_info = info
                    break

        # If not in tracking dict, check if container exists in Docker
        if not container_info and user_id is not None:
            # For backwards compatibility, generate slug from IDs if not provided
            if not project_slug:
                project_slug = f"{user_id}-{project_id}"

            container_name = self._get_container_name(user_id, project_id, project_slug)
            hostname = self._generate_hostname(project_slug)

            # Check if this container exists in Docker
            result = subprocess.run([
                "docker", "inspect", container_name,
                "--format", "{{json .State}}"
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                # Container exists! Add it to tracking
                project_key = self._get_project_key(user_id, project_id)
                self.containers[project_key] = {
                    "container_name": container_name,
                    "hostname": hostname,
                    "user_id": user_id,
                    "project_id": project_id
                }
                container_info = self.containers[project_key]
                print(f"[REDISCOVER] Found existing container: {container_name}")

        if not container_info:
            return {"status": "not_found", "running": False}

        container_name = container_info["container_name"]

        try:
            # Get container status
            result = subprocess.run([
                "docker", "inspect", container_name,
                "--format", "{{json .State}}"
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                state = json.loads(result.stdout.strip())
                return {
                    "status": "running" if state.get("Running") else "stopped",
                    "running": state.get("Running", False),
                    "health": state.get("Health", {}).get("Status", "unknown"),
                    "started_at": state.get("StartedAt"),
                    "hostname": container_info.get("hostname"),
                    "url": self.get_container_url(project_id, user_id),
                    "user_id": container_info.get("user_id"),
                    "project_id": container_info.get("project_id")
                }

        except Exception as e:
            print(f"Error getting container status: {e}")

        return {"status": "error", "running": False}
    
    async def get_all_containers(self) -> List[Dict[str, Any]]:
        """Returns a list of all running containers with their metadata."""
        all_containers = []
        
        for project_key, container_info in self.containers.items():
            container_data = {
                "project_key": project_key,
                "container_name": container_info.get("container_name"),
                "hostname": container_info.get("hostname"),
                "user_id": container_info.get("user_id"),
                "project_id": container_info.get("project_id"),
                "container_id": container_info.get("container_id"),
                "url": self._get_container_access_url(container_info['hostname']) if container_info.get("hostname") else None
            }
            
            # Try to get current Docker status for each container
            container_name = container_info.get("container_name")
            if container_name:
                try:
                    result = subprocess.run([
                        "docker", "inspect", container_name,
                        "--format", "{{json .State}}"
                    ], capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        state = json.loads(result.stdout.strip())
                        container_data.update({
                            "status": "running" if state.get("Running") else "stopped",
                            "running": state.get("Running", False),
                            "health": state.get("Health", {}).get("Status", "unknown"),
                            "started_at": state.get("StartedAt")
                        })
                    else:
                        container_data.update({
                            "status": "not_found",
                            "running": False
                        })
                except Exception as e:
                    container_data.update({
                        "status": "error", 
                        "running": False,
                        "error": str(e)
                    })
            else:
                container_data.update({
                    "status": "unknown",
                    "running": False
                })
            
            all_containers.append(container_data)
        
        return all_containers
    
    async def stop_all_containers(self) -> None:
        """Stop all development containers."""
        print("[STOP] Stopping all development containers...")
        
        # Get list of all container info before iterating (to avoid modifying dict during iteration)
        containers_to_stop = list(self.containers.items())
        for project_key, container_info in containers_to_stop:
            project_id = container_info.get("project_id")
            user_id = container_info.get("user_id")
            if project_id and user_id is not None:
                await self.stop_container(project_id, user_id)
        
        print("[OK] All development containers stopped")
    
    def force_rebuild_base_image(self) -> bool:
        """Force rebuild the base image (for development/debugging)."""
        print("[REBUILD] Force rebuilding base image...")

        # Remove existing image
        try:
            subprocess.run(
                ["docker", "rmi", "-f", self.base_image_name],
                capture_output=True,
                timeout=30
            )
        except Exception:
            pass

        # Reset flags
        self._base_image_ready = False

        # Rebuild
        return self._ensure_base_image_exists()

    async def execute_command_in_container(
        self,
        user_id: UUID,
        project_id: str,
        command: List[str],
        timeout: int = 120,
        project_slug: str = None
    ) -> str:
        """
        Execute a command inside a user's development container.

        Args:
            user_id: User ID
            project_id: Project ID
            command: Command to execute (as list, e.g., ["/bin/sh", "-c", "git status"])
            timeout: Timeout in seconds
            project_slug: Project slug (optional, for slug-based container naming)

        Returns:
            Command output (stdout + stderr combined)

        Raises:
            RuntimeError: If command execution fails or container not found
        """
        # Get container name - try to find it from tracking dict first
        project_key = self._get_project_key(user_id, project_id)
        container_info = self.containers.get(project_key)

        if container_info:
            container_name = container_info["container_name"]
        elif project_slug:
            # Use slug-based naming
            container_name = self._get_container_name(user_id, project_id, project_slug)
        else:
            # Fallback to old ID-based naming (backwards compatibility)
            container_name = self._get_container_name(user_id, project_id)

        # Build docker exec command
        exec_cmd = ["docker", "exec", container_name] + command

        try:
            # Execute with timeout
            result = subprocess.run(
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Return combined output (Git operations need both stdout and stderr)
            output = result.stdout + result.stderr

            # If command failed, raise error with output
            if result.returncode != 0:
                raise RuntimeError(f"Command failed with exit code {result.returncode}: {output}")

            return output

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command execution timed out after {timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Failed to execute command in container {container_name}: {str(e)}")

    def track_activity(self, user_id: UUID, project_id: str) -> None:
        """Record activity for a project container."""
        project_key = self._get_project_key(user_id, project_id)
        self.activity_tracker[project_key] = time.time()
        print(f"[DEBUG] Activity tracked for {project_key}")

    async def cleanup_idle_environments(self, idle_timeout_minutes: int = 30) -> List[str]:
        """
        Cleanup containers that have been idle for longer than the timeout.

        Args:
            idle_timeout_minutes: Minutes of inactivity before cleanup (default: 30)

        Returns:
            List of cleaned up project keys
        """
        print(f"[CLEANUP] Checking for idle containers (timeout: {idle_timeout_minutes} minutes)...")

        cleaned = []
        current_time = time.time()
        timeout_seconds = idle_timeout_minutes * 60

        try:
            # Get list of all containers before iterating (to avoid modifying dict during iteration)
            containers_to_check = list(self.containers.items())

            for project_key, container_info in containers_to_check:
                user_id = container_info.get("user_id")
                project_id = container_info.get("project_id")
                container_name = container_info.get("container_name")

                # Check last activity time
                last_activity = self.activity_tracker.get(project_key, 0)
                idle_time = current_time - last_activity if last_activity > 0 else float('inf')
                idle_minutes = idle_time / 60

                # If no activity tracked yet, use container creation time as baseline
                if last_activity == 0 and container_name:
                    try:
                        result = subprocess.run(
                            ["docker", "inspect", container_name, "--format", "{{.State.StartedAt}}"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            # Parse Docker timestamp (ISO 8601 format)
                            from datetime import datetime
                            started_at = result.stdout.strip()
                            # Docker returns timestamp like: 2025-10-07T12:34:56.789Z
                            created_time = datetime.fromisoformat(started_at.replace('Z', '+00:00')).timestamp()
                            idle_time = current_time - created_time
                            idle_minutes = idle_time / 60
                    except Exception as e:
                        print(f"[DEBUG] Could not get container creation time for {container_name}: {e}")

                if idle_time > timeout_seconds:
                    print(f"[CLEANUP] Cleaning up idle container {project_key} (idle for {idle_minutes:.1f} minutes)")
                    try:
                        await self.stop_container(project_id, user_id)
                        cleaned.append(project_key)

                        # Remove from activity tracker
                        self.activity_tracker.pop(project_key, None)

                    except Exception as e:
                        print(f"[ERROR] Failed to cleanup {project_key}: {e}")
                else:
                    print(f"[DEBUG] {project_key} is active (idle for {idle_minutes:.1f} minutes)")

        except Exception as e:
            print(f"[ERROR] Error during idle cleanup: {e}")

        print(f"[CLEANUP] Idle cleanup completed. Removed {len(cleaned)} idle containers")
        return cleaned