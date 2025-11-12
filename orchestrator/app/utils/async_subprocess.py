"""
Async subprocess utilities
Replaces synchronous subprocess.run() calls with async alternatives.
"""
import asyncio
from typing import Optional, List, Tuple
from dataclasses import dataclass


@dataclass
class SubprocessResult:
    """Result from subprocess execution (mirrors subprocess.CompletedProcess)"""
    returncode: int
    stdout: str
    stderr: str
    args: List[str]

    @property
    def success(self) -> bool:
        return self.returncode == 0


async def run_async(
    cmd: List[str],
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False
) -> SubprocessResult:
    """
    Async replacement for subprocess.run()

    Args:
        cmd: Command and arguments as list
        timeout: Optional timeout in seconds
        cwd: Working directory
        env: Environment variables
        capture_output: Capture stdout/stderr
        text: Return output as text (not bytes)
        check: Raise exception on non-zero exit code

    Returns:
        SubprocessResult with returncode, stdout, stderr

    Raises:
        asyncio.TimeoutError: If timeout is exceeded
        RuntimeError: If check=True and returncode != 0
    """
    try:
        # Create subprocess
        if capture_output:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=env
            )

        # Wait for completion with optional timeout
        try:
            if timeout:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            else:
                stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.TimeoutError:
            # Kill process on timeout
            process.kill()
            await process.wait()
            raise

        # Decode output if text mode
        if text and stdout_bytes:
            stdout = stdout_bytes.decode('utf-8', errors='replace')
        else:
            stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""

        if text and stderr_bytes:
            stderr = stderr_bytes.decode('utf-8', errors='replace')
        else:
            stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""

        result = SubprocessResult(
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            args=cmd
        )

        # Raise exception if check=True and failed
        if check and result.returncode != 0:
            raise RuntimeError(
                f"Command {' '.join(cmd)} failed with exit code {result.returncode}: {stderr}"
            )

        return result

    except Exception as e:
        # Re-raise with more context
        if not isinstance(e, (asyncio.TimeoutError, RuntimeError)):
            raise RuntimeError(f"Subprocess execution failed: {e}") from e
        raise


async def run_async_stream(
    cmd: List[str],
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    stdout_callback: Optional[callable] = None,
    stderr_callback: Optional[callable] = None
) -> SubprocessResult:
    """
    Run subprocess with real-time output streaming

    Args:
        cmd: Command and arguments
        timeout: Optional timeout
        cwd: Working directory
        env: Environment variables
        stdout_callback: Function to call with each stdout line
        stderr_callback: Function to call with each stderr line

    Returns:
        SubprocessResult
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env
    )

    stdout_lines = []
    stderr_lines = []

    async def read_stream(stream, callback, lines_list):
        """Read stream line by line"""
        while True:
            line = await stream.readline()
            if not line:
                break
            line_text = line.decode('utf-8', errors='replace').rstrip()
            lines_list.append(line_text)
            if callback:
                if asyncio.iscoroutinefunction(callback):
                    await callback(line_text)
                else:
                    callback(line_text)

    # Read both streams concurrently
    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(process.stdout, stdout_callback, stdout_lines),
                read_stream(process.stderr, stderr_callback, stderr_lines),
                process.wait()
            ),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise

    return SubprocessResult(
        returncode=process.returncode,
        stdout='\n'.join(stdout_lines),
        stderr='\n'.join(stderr_lines),
        args=cmd
    )


async def check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH"""
    try:
        if command == "docker":
            # Special handling for docker on Windows
            result = await run_async(
                ["docker", "--version"],
                timeout=5,
                capture_output=True
            )
            return result.returncode == 0
        else:
            # Generic command check
            import shutil
            return await asyncio.to_thread(shutil.which, command) is not None
    except Exception:
        return False


# Compatibility helpers for common patterns
async def docker_inspect(container_name: str, format_str: str = "{{.State.Running}}", timeout: float = 5) -> SubprocessResult:
    """Helper for docker inspect commands"""
    return await run_async(
        ["docker", "inspect", f"--format={format_str}", container_name],
        timeout=timeout,
        capture_output=True,
        text=True
    )


async def docker_exec(container_name: str, command: List[str], timeout: float = 30) -> SubprocessResult:
    """Helper for docker exec commands"""
    return await run_async(
        ["docker", "exec", container_name] + command,
        timeout=timeout,
        capture_output=True,
        text=True
    )


async def docker_logs(container_name: str, tail: Optional[int] = None, timeout: float = 10) -> SubprocessResult:
    """Helper for docker logs commands"""
    cmd = ["docker", "logs", container_name]
    if tail:
        cmd.extend(["--tail", str(tail)])
    return await run_async(cmd, timeout=timeout, capture_output=True, text=True)
