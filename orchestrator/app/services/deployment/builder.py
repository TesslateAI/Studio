"""
Deployment Builder Service.

This module handles building projects inside containers and collecting the built files
for deployment to various providers.
"""

import asyncio
import base64
import io
import logging
import os
import tarfile
import textwrap
from uuid import UUID

import docker

from ...services.framework_detector import FrameworkDetector
from .base import DeploymentFile

# Legacy container manager removed - multi-container projects only

logger = logging.getLogger(__name__)


class BuildError(Exception):
    """Exception raised when build fails."""

    pass


class DeploymentBuilder:
    """
    Handles building projects and collecting deployment files.

    This service integrates with the existing container management system
    to run builds inside project containers and collect the resulting files.
    """

    def __init__(self):
        """Initialize the deployment builder."""
        self.container_manager = None  # TODO: Update for multi-container system
        self.docker_client = None
        self.dev_server_image = "tesslate-devserver:latest"

    def _get_docker_client(self):
        """Get or create Docker client."""
        if self.docker_client is None:
            self.docker_client = docker.from_env()
        return self.docker_client

    async def trigger_build(
        self,
        user_id: str,
        project_id: str,
        project_slug: str,
        framework: str | None = None,
        custom_build_command: str | None = None,
        project_settings: dict | None = None,
        container_name: str | None = None,
        volume_name: str | None = None,
        container_directory: str | None = None,
        deployment_mode: str | None = None,
    ) -> tuple[bool, str]:
        """
        Trigger a build inside the project container.

        Args:
            user_id: User ID
            project_id: Project ID
            project_slug: Project slug (for container naming)
            framework: Framework type (auto-detected if not provided)
            custom_build_command: Custom build command override
            project_settings: Project settings dict (for cached framework info)
            container_name: Specific container name to build in (for multi-container projects)
            volume_name: Docker volume name
            container_directory: Subdirectory within the project (for multi-container projects)
            deployment_mode: "pre-built" or "source" — pre-built forces static export for Next.js

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            BuildError: If build fails
        """
        try:
            # Get project path
            project_path = self._get_project_path(user_id, project_id)

            # Detect framework using priority: parameter > cached > auto-detect
            if not framework:
                # Try to use cached framework from project settings
                if project_settings and project_settings.get("framework"):
                    framework = project_settings["framework"]
                    logger.info(f"Using cached framework from project settings: {framework}")
                else:
                    # Fallback: Auto-detect from package.json
                    package_json_path = os.path.join(project_path, "package.json")
                    if os.path.exists(package_json_path):
                        with open(package_json_path) as f:
                            package_json_content = f.read()
                        framework, _ = FrameworkDetector.detect_from_package_json(
                            package_json_content
                        )
                        logger.info(f"Auto-detected framework: {framework}")
                    else:
                        framework = "vite"
                        logger.warning("No package.json found, defaulting to vite")

            # Get build command with priority: custom > cached > framework default
            if custom_build_command:
                build_command = custom_build_command
            elif project_settings and project_settings.get("build_command"):
                build_command = project_settings["build_command"]
                logger.info(f"Using cached build command from project settings: {build_command}")
            else:
                build_command = self._get_build_command(framework)

            if not build_command:
                logger.warning(f"Framework {framework} does not require a build step")
                return True, "No build required for this framework"

            # Compute working directory for multi-container projects
            if container_directory and container_directory not in (".", ""):
                work_dir = f"/app/{container_directory}"
            else:
                work_dir = "/app"

            logger.info(f"Running build command in container: {build_command} (work_dir: {work_dir})")

            # Execute build command in container using orchestrator
            # This works with both Docker and Kubernetes modes
            try:
                from ..orchestration import get_orchestrator

                orchestrator = get_orchestrator()
                effective_container = container_name or project_slug
                logger.info(f"Executing build in container: {effective_container}")

                # Install deps safety net (only if node_modules is missing)
                # Detect package manager from lockfile: bun.lock → bun, pnpm-lock.yaml → pnpm, else npm
                # set -e ensures the shell exits on any command failure
                install_cmd = (
                    "if [ -f bun.lock ] || [ -f bun.lockb ]; then bun install --frozen-lockfile; "
                    "elif [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; "
                    "else npm install --prefer-offline --no-audit; fi"
                )

                # For pre-built Next.js deployments, temporarily patch the project
                # so `next build` produces the static `out/` directory:
                # 1. Set output:'export' in next.config
                # 2. Add force-static to API route files (incompatible with static export)
                # All changes are backed up and restored after build.
                pre_build_cmd = ""
                if framework and framework.lower() == "nextjs" and deployment_mode == "pre-built":
                    logger.info("Injecting Next.js static export config for pre-built deployment")
                    write_scripts_cmd = self._get_nextjs_export_scripts_cmd()
                    pre_build_cmd = f"&& {write_scripts_cmd} && node /tmp/_deploy_inject.js "
                    # Wrap build in subshell: set +e ensures restore always runs
                    # even if build fails, then exit with build's exit code
                    build_command = (
                        f"(set +e; {build_command}; _E=$?; node /tmp/_deploy_restore.js; exit $_E)"
                    )

                full_cmd = (
                    f"set -e && cd {work_dir} "
                    f"&& ([ -d node_modules ] || ({install_cmd})) "
                    f"{pre_build_cmd}"
                    f"&& {build_command} "
                    f"&& echo BUILD_EXIT_CODE=0"
                )

                # Use orchestrator's execute_command method which handles both Docker and K8s
                output = await orchestrator.execute_command(
                    user_id=UUID(user_id),
                    project_id=UUID(project_id),
                    container_name=effective_container,
                    command=["/bin/sh", "-c", full_cmd],
                    timeout=300,
                )
            except RuntimeError as e:
                error_msg = f"Build failed: {str(e)}"
                logger.error(error_msg)
                raise BuildError(error_msg) from e

            # Verify the build actually produced output
            if "BUILD_EXIT_CODE=0" not in output:
                logger.error(f"Build command did not complete successfully. Output: {output[:1000]}")
                raise BuildError(f"Build command failed. Output: {output[:1000]}")

            logger.info(f"Build completed successfully for project {project_id}")
            return True, output

        except Exception as e:
            logger.error(f"Build failed for project {project_id}: {e}", exc_info=True)
            raise BuildError(f"Build failed: {e}") from e

    async def collect_deployment_files(
        self,
        user_id: str,
        project_id: str,
        framework: str | None = None,
        custom_output_dir: str | None = None,
        project_settings: dict | None = None,
        collect_source: bool = False,
        container_directory: str | None = None,
        volume_name: str | None = None,
        container_name: str | None = None,
    ) -> list[DeploymentFile]:
        """
        Collect files from the project for deployment.

        Uses the orchestrator to collect files from inside the project container/pod.
        This works in both Docker and Kubernetes modes.

        Args:
            user_id: User ID
            project_id: Project ID
            framework: Framework type (auto-detected if not provided)
            custom_output_dir: Custom output directory override
            project_settings: Project settings dict (for cached framework info)
            collect_source: If True, collect source files; if False, collect built files
            container_directory: Subdirectory within project (for multi-container projects)
            volume_name: Project slug (used for Docker shared volume path)
            container_name: Container name for orchestrator commands

        Returns:
            List of DeploymentFile objects

        Raises:
            FileNotFoundError: If build output directory doesn't exist
        """
        try:
            # Compute the target directory inside the container
            if container_directory and container_directory not in (".", ""):
                base_dir = f"/app/{container_directory}"
            else:
                base_dir = "/app"

            if collect_source:
                # Collect source files (Vercel will build remotely)
                target_dir = base_dir
                logger.info(f"Collecting source files from container at {target_dir}")
            else:
                # Collect built files — determine output directory
                if not framework:
                    if project_settings and project_settings.get("framework"):
                        framework = project_settings["framework"]
                    else:
                        framework = "vite"

                if custom_output_dir:
                    output_dir = custom_output_dir
                elif project_settings and project_settings.get("output_directory"):
                    output_dir = project_settings["output_directory"]
                else:
                    output_dir = self._get_build_output_dir(framework)

                target_dir = f"{base_dir}/{output_dir}"
                logger.info(f"Collecting built files from container at {target_dir}")

            # Primary: use orchestrator to collect files (works for both Docker and K8s)
            if container_name:
                files = await self._collect_files_via_orchestrator(
                    user_id=user_id,
                    project_id=project_id,
                    container_name=container_name,
                    target_dir=target_dir,
                )
                logger.info(f"Collected {len(files)} files via orchestrator")
                return files

            # Fallback: direct filesystem for Docker shared volume
            if volume_name:
                volume_dir = f"/projects/{volume_name}"
                if container_directory and container_directory not in (".", ""):
                    volume_dir = f"{volume_dir}/{container_directory}"

                if not collect_source:
                    if not framework:
                        framework = "vite"
                    if custom_output_dir:
                        out = custom_output_dir
                    elif project_settings and project_settings.get("output_directory"):
                        out = project_settings["output_directory"]
                    else:
                        out = self._get_build_output_dir(framework)
                    volume_dir = f"{volume_dir}/{out}"

                logger.info(f"Collecting files from shared volume at {volume_dir}")
                if not os.path.exists(volume_dir):
                    raise FileNotFoundError(
                        f"Build output directory not found: {volume_dir}"
                    )
                files = await self._collect_files_recursive(volume_dir, ".")
                logger.info(f"Collected {len(files)} files from volume")
                return files

            raise FileNotFoundError(
                "No container_name or volume_name provided for file collection"
            )

        except Exception as e:
            logger.error(f"Failed to collect deployment files: {e}", exc_info=True)
            raise

    async def _collect_files_recursive(self, directory: str, base_dir: str) -> list[DeploymentFile]:
        """
        Recursively collect all files from a directory.

        Args:
            directory: Absolute path to directory to scan
            base_dir: Base directory name for relative paths

        Returns:
            List of DeploymentFile objects
        """
        files = []
        ignored_patterns = {
            ".git",
            "node_modules",
            "__pycache__",
            ".DS_Store",
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            "thumbs.db",
            ".next",
            "out",
            "dist",
            "build",
            ".turbo",
        }

        for root, dirs, filenames in os.walk(directory):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_patterns]

            for filename in filenames:
                # Skip ignored files
                if filename in ignored_patterns or filename.startswith("."):
                    continue

                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory)

                # Read file content
                try:
                    # Use async file reading for better performance
                    content = await self._read_file_async(file_path)

                    files.append(DeploymentFile(path=relative_path, content=content))

                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

        return files

    async def _collect_files_via_orchestrator(
        self,
        user_id: str,
        project_id: str,
        container_name: str,
        target_dir: str,
    ) -> list[DeploymentFile]:
        """
        Collect files from the project container via orchestrator execute_command.

        Runs tar+base64 inside the pod/container and decodes the result.
        Works in both Docker and Kubernetes modes.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name for orchestrator
            target_dir: Absolute path inside the container to collect from

        Returns:
            List of DeploymentFile objects
        """
        from ..orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        # First verify the directory exists; if not, list parent contents for debugging
        check_output = await orchestrator.execute_command(
            user_id=UUID(user_id),
            project_id=UUID(project_id),
            container_name=container_name,
            command=["/bin/sh", "-c",
                     f"if [ -d {target_dir} ]; then echo EXISTS; "
                     f"else echo NOT_FOUND; echo '---'; ls -la $(dirname {target_dir}) 2>&1 || true; fi"],
            timeout=10,
        )

        if "NOT_FOUND" in check_output:
            raise FileNotFoundError(
                f"Directory not found in container: {target_dir}\n"
                f"Container contents:\n{check_output}"
            )

        # Tar the directory, base64 encode, and stream back
        excludes = (
            "--exclude=node_modules --exclude=.git --exclude=__pycache__ "
            "--exclude=.DS_Store --exclude=.env --exclude=.env.local "
            "--exclude=.env.production --exclude=.env.development "
            "--exclude=thumbs.db --exclude=.next --exclude=out "
            "--exclude=dist --exclude=build --exclude=.turbo"
        )
        cmd = f"tar -cf - -C {target_dir} {excludes} . 2>/dev/null | base64"

        output = await orchestrator.execute_command(
            user_id=UUID(user_id),
            project_id=UUID(project_id),
            container_name=container_name,
            command=["/bin/sh", "-c", cmd],
            timeout=120,
        )

        if not output or not output.strip():
            raise FileNotFoundError(f"No files found in {target_dir}")

        # Decode base64 and extract tar
        tar_bytes = base64.b64decode(output.strip())
        files = []

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if name.startswith("./"):
                    name = name[2:]
                if not name:
                    continue
                # Skip hidden files
                if any(part.startswith(".") for part in name.split("/")):
                    continue

                f = tar.extractfile(member)
                if f:
                    content = f.read()
                    files.append(DeploymentFile(path=name, content=content))

        return files

    async def _read_file_async(self, file_path: str) -> bytes:
        """
        Read a file asynchronously.

        Args:
            file_path: Path to file

        Returns:
            File content as bytes
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_file_sync, file_path)

    @staticmethod
    def _read_file_sync(file_path: str) -> bytes:
        """
        Read a file synchronously (for executor).

        Args:
            file_path: Path to file

        Returns:
            File content as bytes
        """
        with open(file_path, "rb") as f:
            return f.read()

    def _get_project_path(self, user_id: str, project_id: str) -> str:
        """
        Get the filesystem path to a project.

        Args:
            user_id: User ID
            project_id: Project ID

        Returns:
            Absolute path to project directory
        """
        from ..orchestration import is_kubernetes_mode

        if is_kubernetes_mode():
            # Kubernetes uses shared PVC
            base_path = "/mnt/shared"
        else:
            # Docker uses local filesystem
            base_path = os.path.join(os.path.dirname(__file__), "../../../users")

        return os.path.join(base_path, f"{user_id}/{project_id}")

    def _get_build_command(self, framework: str) -> str | None:
        """
        Get the build command for a framework.

        Args:
            framework: Framework type

        Returns:
            Build command string or None if no build needed
        """
        commands = {
            "vite": "npm run build",
            "nextjs": "npm run build",
            "react": "npm run build",
            "vue": "npm run build",
            "svelte": "npm run build",
            "angular": "npm run build",
            "go": "go build -o main",
            "python": None,  # No build for Python
            "node": None,  # No build for plain Node.js
        }

        return commands.get(framework.lower(), "npm run build")

    def _get_build_output_dir(self, framework: str) -> str:
        """
        Get the build output directory for a framework.

        Args:
            framework: Framework type

        Returns:
            Output directory name
        """
        output_dirs = {
            "vite": "dist",
            "nextjs": "out",  # Next.js static export (output: 'export' in next.config)
            "react": "build",
            "vue": "dist",
            "svelte": "dist",
            "angular": "dist",
            "go": ".",
            "python": ".",
        }

        return output_dirs.get(framework.lower(), "dist")

    @staticmethod
    def _get_nextjs_export_scripts_cmd() -> str:
        """
        Return a shell command that writes the inject and restore Node.js scripts
        to /tmp inside the container. Uses base64 encoding to avoid shell escaping.

        Scripts:
        - inject: set output:'export' in next.config + add force-static to API routes
        - restore: revert all changes using .deploy-bak files
        """
        inject_js = textwrap.dedent("""\
            const fs = require('fs');
            const path = require('path');
            const configs = ['next.config.ts', 'next.config.mjs', 'next.config.js'];
            for (const f of configs) {
              if (fs.existsSync(f)) {
                let c = fs.readFileSync(f, 'utf8');
                fs.copyFileSync(f, f + '.deploy-bak');
                if (/output\\s*:\\s*['"]/.test(c)) {
                  c = c.replace(/output\\s*:\\s*['"][^'"]*['"]/, "output: 'export'");
                  console.log('Replaced output value with export in ' + f);
                } else {
                  c = c.replace(/(const\\s+\\w+\\s*[=:]\\s*\\{)/, "$1\\n  output: 'export',");
                  c = c.replace(/(export\\s+default\\s*\\{)/, "$1\\n  output: 'export',");
                  console.log('Injected output:export into ' + f);
                }
                fs.writeFileSync(f, c);
                break;
              }
            }
            function findRoutes(dir) {
              const results = [];
              if (!fs.existsSync(dir)) return results;
              for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
                const full = path.join(dir, e.name);
                if (e.isDirectory() && e.name !== 'node_modules' && e.name !== '.next') {
                  results.push(...findRoutes(full));
                } else if (e.isFile() && /^route\\.(ts|js|tsx|jsx)$/.test(e.name)) {
                  results.push(full);
                }
              }
              return results;
            }
            for (const r of findRoutes('app')) {
              let c = fs.readFileSync(r, 'utf8');
              if (!c.includes("dynamic")) {
                fs.copyFileSync(r, r + '.deploy-bak');
                fs.writeFileSync(r, 'export const dynamic = "force-static";\\n' + c);
                console.log('Added force-static to ' + r);
              }
            }
            console.log('Static export injection complete');
        """)

        restore_js = textwrap.dedent("""\
            const fs = require('fs');
            const path = require('path');
            function findBaks(dir) {
              const results = [];
              if (!fs.existsSync(dir)) return results;
              for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
                const full = path.join(dir, e.name);
                if (e.isDirectory() && e.name !== 'node_modules' && e.name !== '.next') {
                  results.push(...findBaks(full));
                } else if (e.isFile() && e.name.endsWith('.deploy-bak')) {
                  results.push(full);
                }
              }
              return results;
            }
            for (const f of ['next.config.ts', 'next.config.mjs', 'next.config.js']) {
              const bak = f + '.deploy-bak';
              if (fs.existsSync(bak)) {
                fs.renameSync(bak, f);
                console.log('Restored ' + f);
                break;
              }
            }
            for (const b of findBaks('app')) {
              const orig = b.replace('.deploy-bak', '');
              fs.renameSync(b, orig);
              console.log('Restored ' + orig);
            }
            console.log('Restore complete');
        """)

        inject_b64 = base64.b64encode(inject_js.encode()).decode()
        restore_b64 = base64.b64encode(restore_js.encode()).decode()

        return (
            f"echo '{inject_b64}' | base64 -d > /tmp/_deploy_inject.js "
            f"&& echo '{restore_b64}' | base64 -d > /tmp/_deploy_restore.js"
        )

    async def verify_build_output(
        self, user_id: str, project_id: str, framework: str | None = None
    ) -> bool:
        """
        Verify that build output exists and is valid.

        Args:
            user_id: User ID
            project_id: Project ID
            framework: Framework type

        Returns:
            True if build output is valid
        """
        try:
            project_path = self._get_project_path(user_id, project_id)

            if not framework:
                # Read package.json to detect framework
                package_json_path = os.path.join(project_path, "package.json")
                if os.path.exists(package_json_path):
                    with open(package_json_path) as f:
                        package_json_content = f.read()
                    framework, _ = FrameworkDetector.detect_from_package_json(package_json_content)
                else:
                    framework = "vite"

            output_dir = self._get_build_output_dir(framework)
            build_path = os.path.join(project_path, output_dir)

            # Check if directory exists and has files
            if not os.path.exists(build_path):
                logger.error(f"Build output directory does not exist: {build_path}")
                return False

            # Check if directory has at least one file
            has_files = any(
                os.path.isfile(os.path.join(build_path, f)) for f in os.listdir(build_path)
            )

            if not has_files:
                logger.error(f"Build output directory is empty: {build_path}")
                return False

            logger.info(f"Build output verified for project {project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to verify build output: {e}", exc_info=True)
            return False

    async def _collect_files_from_volume(
        self, project_slug: str, subdirectory: str | None = None
    ) -> list[DeploymentFile]:
        """
        Collect files from the shared projects volume using direct filesystem access.

        With the new architecture, orchestrator has direct access to /projects/{slug}/.

        Args:
            project_slug: Project slug (used as volume_name for backwards compatibility)
            subdirectory: Optional subdirectory within the project to collect from

        Returns:
            List of DeploymentFile objects
        """
        # Build the path within the shared volume
        base_path = f"/projects/{project_slug}"
        if subdirectory and subdirectory != ".":
            base_path = f"{base_path}/{subdirectory}"

        logger.info(f"Collecting files from shared volume at {base_path}")

        if not os.path.exists(base_path):
            raise FileNotFoundError(f"Project path not found: {base_path}")

        try:
            files = await self._collect_files_recursive(base_path, ".")
            logger.info(f"Collected {len(files)} files from {base_path}")
            return files
        except Exception as e:
            logger.error(f"Failed to collect files from {base_path}: {e}", exc_info=True)
            raise FileNotFoundError(f"Failed to read from {base_path}: {str(e)}") from e

    async def _read_file_from_volume(self, project_slug: str, file_path: str) -> bytes | None:
        """
        Read a single file from the shared projects volume.

        With the new architecture, orchestrator has direct access to /projects/{slug}/.

        Args:
            project_slug: Project slug (used as volume_name for backwards compatibility)
            file_path: Path to the file within the project

        Returns:
            File content as bytes, or None if file doesn't exist
        """
        full_path = f"/projects/{project_slug}/{file_path}"

        try:
            if os.path.exists(full_path):
                with open(full_path, "rb") as f:
                    return f.read()
            return None
        except Exception as e:
            logger.warning(f"Failed to read file {full_path}: {e}")
            return None

    async def _directory_exists_in_volume(self, project_slug: str, directory_path: str) -> bool:
        """
        Check if a directory exists in the shared projects volume.

        With the new architecture, orchestrator has direct access to /projects/{slug}/.

        Args:
            project_slug: Project slug (used as volume_name for backwards compatibility)
            directory_path: Path to the directory within the project

        Returns:
            True if directory exists, False otherwise
        """
        full_path = f"/projects/{project_slug}/{directory_path}"
        return os.path.isdir(full_path)


# Global singleton instance
_deployment_builder: DeploymentBuilder | None = None


def get_deployment_builder() -> DeploymentBuilder:
    """
    Get or create the global deployment builder instance.

    Returns:
        The global DeploymentBuilder instance
    """
    global _deployment_builder

    if _deployment_builder is None:
        logger.debug("Initializing global deployment builder")
        _deployment_builder = DeploymentBuilder()

    return _deployment_builder
