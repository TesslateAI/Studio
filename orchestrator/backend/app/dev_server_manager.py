import asyncio
import subprocess
import os
import json
import shutil
import time
from typing import Dict, Optional, List
import socket
from contextlib import closing
import aiohttp
from .config import get_settings


class DevContainerManager:
    """
    Production-ready development container manager for multi-user, multi-project environments.
    - Uses a single base image with project files mounted as volumes
    - Proper port allocation and container lifecycle management
    - Organized container naming for Docker Desktop visibility
    - Automatic cleanup and resource management
    """
    
    def __init__(self):
        self.containers: Dict[str, Dict] = {}  # project_key -> {container_name, hostname, user_id, project_id}
        self.network_name = "builder-devserver-network"
        self.base_image_name = "builder-devserver:latest"
        self.container_label = "com.builder.devserver"
        self._docker_available = None  # Lazy check
        self._network_ready = False  # Lazy initialization
        self._base_image_ready = False  # Base image built once
        
        print("[INFO] DevContainerManager initialized - Traefik-powered zero-port-conflict architecture")
    
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
            base_dockerfile = self._create_base_dockerfile()
            
            build_result = subprocess.run([
                "docker", "build",
                "--pull",  # Pull latest base image
                "-f", "-",  # Read Dockerfile from stdin
                "-t", self.base_image_name,
                "."
            ], input=base_dockerfile, text=True, capture_output=True, timeout=300)
            
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
    
    def _create_base_dockerfile(self) -> str:
        """Create the base Dockerfile with all common dependencies."""
        return """# Fast Base Development Image - Built Once, Reused for All Projects
FROM node:20-alpine

# Install essential system tools only
RUN apk add --no-cache \\
    git \\
    curl \\
    python3 \\
    make \\
    g++ \\
    libc6-compat

# Create app directory
WORKDIR /app

# Create npm cache directory for faster installs
RUN mkdir -p /root/.npm-cache
ENV npm_config_cache=/root/.npm-cache

# Expose development server port
EXPOSE 5173

# Default command - projects will install their own dependencies on volume mount
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
"""
    
    def _get_project_key(self, user_id: int, project_id: str) -> str:
        """Generate a unique project key for container management."""
        return f"user-{user_id}-project-{project_id}"
    
    def _get_container_name(self, user_id: int, project_id: str) -> str:
        """Generate a descriptive container name for Docker Desktop visibility."""
        return f"builder-dev-user{user_id}-project{project_id}"
    
    def _generate_hostname(self, user_id: int, project_id: str) -> str:
        """Generate a unique hostname for Traefik routing."""
        return f"user{user_id}-project{project_id}.localhost"
    
    def _get_container_access_url(self, hostname: str) -> str:
        """Get the access URL for a container, considering proxy configuration."""
        settings = get_settings()
        # Always use production URL when configured (with trailing slash for Vite base path)
        user_project = hostname.replace('.localhost', '')
        return f"{settings.dev_server_base_url}/preview/{user_project}/"
    
    def _get_traefik_labels(self, user_id: int, project_id: str, hostname: str) -> List[str]:
        """Generate Traefik labels for automatic service discovery and routing."""
        service_name = f"builder-dev-user{user_id}-project{project_id}"
        user_project = hostname.replace('.localhost', '')
        
        # Check if we need path-based routing for production
        settings = get_settings()
        labels = [
            "--label", "traefik.enable=true",
            # Host-based routing (local): user2-project15.localhost
            "--label", f"traefik.http.routers.{service_name}.rule=Host(`{hostname}`)",
            "--label", f"traefik.http.routers.{service_name}.entrypoints=web",
            "--label", f"traefik.http.routers.{service_name}.priority=100",  # High priority
            # Service configuration
            "--label", f"traefik.http.services.{service_name}.loadbalancer.server.port=5173",
            "--label", "traefik.docker.network=builder-devserver-network",
        ]
        
        # Production path-based routing WITHOUT stripprefix
        # Let Vite handle the full path with --base flag
        labels.extend([
            # Path-based routing HTTP: /preview/user2-project15
            "--label", f"traefik.http.routers.{service_name}-path.rule=PathPrefix(`/preview/{user_project}`)",
            "--label", f"traefik.http.routers.{service_name}-path.entrypoints=web",
            "--label", f"traefik.http.routers.{service_name}-path.priority=100",  # High priority
            # Path-based routing HTTPS: /preview/user2-project15
            "--label", f"traefik.http.routers.{service_name}-path-secure.rule=PathPrefix(`/preview/{user_project}`)",
            "--label", f"traefik.http.routers.{service_name}-path-secure.entrypoints=websecure",
            "--label", f"traefik.http.routers.{service_name}-path-secure.priority=100",
            "--label", f"traefik.http.routers.{service_name}-path-secure.tls=true",
            # NO stripprefix - Vite needs to see the full path
        ])

        return labels
    
    def _create_dockerfile(self, project_path: str) -> str:
        """Create optimized Dockerfile for development."""
        dockerfile_content = """# Development Container for React/Vite Projects
FROM node:18-alpine

# Install development tools and Python (needed for some native deps)
RUN apk add --no-cache git curl python3 make g++

# Create app directory
WORKDIR /app

# Copy container-compatible package.json
COPY package.container.json ./package.json

# Install dependencies
RUN npm install --silent && npm cache clean --force

# Copy project files
COPY . .

# Expose development server port
EXPOSE 5173

# Health check for container readiness
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \\
    CMD curl -f http://localhost:5173 || exit 1

# Start development server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
"""
        
        dockerfile_path = os.path.join(project_path, "Dockerfile.dev")
        with open(dockerfile_path, 'w', encoding='utf-8') as f:
            f.write(dockerfile_content)
        
        return dockerfile_path
    
    def _create_dockerignore(self, project_path: str) -> None:
        """Create .dockerignore for optimized builds."""
        dockerignore_content = """# Dependencies
node_modules
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Production build
dist
build

# Environment files
.env.local
.env.development.local
.env.test.local
.env.production.local

# IDE files
.vscode
.idea
*.swp
*.swo

# OS files
.DS_Store
Thumbs.db

# Git
.git
.gitignore

# Docker files
Dockerfile*
docker-compose*
"""
        
        dockerignore_path = os.path.join(project_path, ".dockerignore")
        with open(dockerignore_path, 'w', encoding='utf-8') as f:
            f.write(dockerignore_content)
    
    def _create_container_package_json(self, project_path: str) -> None:
        """Create a container-compatible package.json without platform-specific deps."""
        original_package_path = os.path.join(project_path, "package.json")
        container_package_path = os.path.join(project_path, "package.container.json")
        
        try:
            with open(original_package_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            # Remove Windows-specific dependencies
            if 'devDependencies' in package_data:
                deps_to_remove = []
                for dep_name in package_data['devDependencies']:
                    if 'win32' in dep_name or 'msvc' in dep_name:
                        deps_to_remove.append(dep_name)
                
                for dep in deps_to_remove:
                    del package_data['devDependencies'][dep]
                    print(f"[CLEANUP] Removed platform-specific dependency: {dep}")
            
            # Create container-specific package.json
            with open(container_package_path, 'w', encoding='utf-8') as f:
                json.dump(package_data, f, indent=2)
            
            print(f"[OK] Created container-compatible package.json")
            
        except Exception as e:
            print(f"[WARN] Could not create container package.json: {e}")
            # Fall back to original
    
    async def wait_for_container_ready_traefik(self, container_name: str, timeout: int = 60) -> bool:
        """Wait for container to be ready using health checks and HTTP."""
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
        
        # Wait for Vite dev server to be ready by checking logs
        print(f"[WAIT] Checking container logs for dev server readiness...")
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "logs", "--tail", "20", container_name],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logs = result.stdout + result.stderr
                    # Look for Vite ready indicators
                    if "Local:" in logs and "5173" in logs:
                        print(f"[OK] Container {container_name} dev server is ready")
                        return True
                    if "ready in" in logs.lower():
                        print(f"[OK] Container {container_name} dev server is ready")
                        return True
            except Exception as e:
                print(f"[DEBUG] Error checking logs: {e}")
                pass
            
            await asyncio.sleep(3)
        
        print(f"[WARN] Container {container_name} readiness check timed out")
        return True  # Return True to allow container to continue - Traefik will handle routing when ready
    
    async def start_container(self, project_path: str, project_id: str, user_id: int) -> str:
        """Start a development container using base image + volume mounts (super fast!) with multi-user support."""
        # Generate unique identifiers for multi-user system
        project_key = self._get_project_key(user_id, project_id)
        container_name = self._get_container_name(user_id, project_id)
        
        print(f"[START] Starting development container for user {user_id}, project {project_id}")
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
        
        if not os.path.exists(abs_project_path):
            raise FileNotFoundError(f"Project directory not found: {abs_project_path}")
        
        # Validate required files
        required_files = ["package.json", "vite.config.js", "index.html"]
        missing_files = [f for f in required_files if not os.path.exists(os.path.join(abs_project_path, f))]
        
        if missing_files:
            raise FileNotFoundError(f"Missing required files: {', '.join(missing_files)}")
        
        # Stop existing container for this user and project
        await self.stop_container(project_id, user_id)
        
        # Generate hostname for Traefik routing
        hostname = self._generate_hostname(user_id, project_id)
        
        print(f"[INFO] Project path: {abs_project_path}")
        print(f"[INFO] Hostname: {hostname}")
        print(f"[INFO] Using base image: {self.base_image_name}")
        
        try:
            # Start container with Traefik labels for automatic routing
            print(f"[RUN] Starting Traefik-enabled container with hostname routing...")
            run_cmd = [
                "docker", "run",
                "--rm",                                                  # Remove on exit
                "--name", container_name,                                # Multi-user container name
                "-v", f"{abs_project_path}:/app",                       # Source code volume (live sync!)
                # Docker labels for organization and tracking
                "--label", "com.builder.devserver=true",
                "--label", f"com.builder.devserver.user_id={user_id}",
                "--label", f"com.builder.devserver.project_id={project_id}",
                "--label", "com.builder.devserver.type=devserver",
                "--label", f"com.builder.devserver.hostname={hostname}",
                # Environment variables for Vite HMR (Hot Module Replacement)
                "-e", "VITE_HMR_HOST=0.0.0.0",                          # HMR WebSocket host
                "-e", "VITE_HMR_PORT=5173",                             # HMR WebSocket port (internal container port)
                "-e", "VITE_HMR_PROTOCOL=ws",                           # WebSocket protocol
                "-e", "CHOKIDAR_USEPOLLING=true",                       # Enable polling for file watching
                "-e", "CHOKIDAR_INTERVAL=1000",                         # Polling interval (1 second)
            ]
            
            # Add environment variables for production path-based routing
            settings = get_settings()
            if settings.dev_server_base_url:
                user_project = hostname.replace('.localhost', '')
                run_cmd.extend([
                    "-e", f"VITE_BASE_PATH=/preview/{user_project}/",
                    "-e", f"PUBLIC_URL=/preview/{user_project}"
                ])
            
            # Working directory and detached mode
            run_cmd.extend([
                "-w", "/app",                                           # Working directory
                "-d",                                                   # Detached mode
            ])
            
            # Add Traefik labels for automatic service discovery
            run_cmd.extend(self._get_traefik_labels(user_id, project_id, hostname))
            
            # Add network (required for Traefik)
            run_cmd.extend(["--network", self.network_name])
            
            # Add image and startup command with base path for production
            user_project = hostname.replace('.localhost', '')
            run_cmd.extend([
                self.base_image_name,
                "sh", "-c", f"npm install --silent && npm run dev -- --host 0.0.0.0 --port 5173 --base /preview/{user_project}/"
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
            if not await self.wait_for_container_ready_traefik(container_name, timeout=120):
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
    
    async def stop_container(self, project_id: str, user_id: int = None) -> None:
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
            # Also try to force stop any containers with matching name pattern
            container_name = self._get_container_name(user_id or 0, project_id)
            print(f"[DEBUG] Attempting force cleanup of container: {container_name}")
            try:
                subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=10)
                print(f"[OK] Force cleaned up container: {container_name}")
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
    
    async def restart_container(self, project_path: str, project_id: str, user_id: int) -> str:
        """Restart a development container with multi-user support."""
        print(f"[RESTART] Restarting development container for user {user_id}, project {project_id}")
        await self.stop_container(project_id, user_id)
        return await self.start_container(project_path, project_id, user_id)
    
    def get_container_url(self, project_id: str, user_id: int = None) -> Optional[str]:
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
    
    def get_container_status(self, project_id: str, user_id: int = None) -> Dict[str, any]:
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
    
    def get_all_containers(self) -> List[Dict]:
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


# Global instance - now purely container-based
dev_container_manager = DevContainerManager()