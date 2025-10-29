"""
Command validation service for agent shell command execution.

This module provides security validation for commands before they are executed
in user development pods. It implements allowlists, blocklists, and pattern-based
detection to prevent malicious or dangerous commands.
"""

import re
import shlex
from typing import Tuple, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CommandRisk(Enum):
    """Risk levels for commands."""
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"
    BLOCKED = "blocked"


class ValidationResult:
    """Result of command validation."""

    def __init__(
        self,
        is_valid: bool,
        risk_level: CommandRisk,
        reason: Optional[str] = None,
        sanitized_command: Optional[List[str]] = None
    ):
        self.is_valid = is_valid
        self.risk_level = risk_level
        self.reason = reason
        self.sanitized_command = sanitized_command


class CommandValidator:
    """
    Validates shell commands for security before execution in user pods.

    Security layers:
    1. Command allowlist - only permit known safe commands
    2. Pattern blocklist - reject dangerous patterns (shell injection, etc.)
    3. Argument validation - check for suspicious arguments
    4. Length limits - prevent excessively long commands
    """

    # Safe commands that are allowed for agent execution
    SAFE_COMMANDS = {
        # File operations
        "cat", "ls", "mkdir", "touch", "rm", "cp", "mv", "pwd", "find", "tree",
        "head", "tail", "wc", "grep", "sed", "awk",

        # Build and package management
        "npm", "npx", "node", "yarn", "pnpm",
        "vite", "webpack", "esbuild", "rollup",

        # Git operations
        "git",

        # Process management (limited)
        "ps", "kill", "pkill",

        # Misc utilities
        "echo", "date", "whoami", "which", "basename", "dirname",

        # Archive operations
        "tar", "gzip", "gunzip", "zip", "unzip",
    }

    # Commands that should be blocked entirely
    BLOCKED_COMMANDS = {
        # Privilege escalation
        "sudo", "su", "doas",

        # System modification
        "systemctl", "service", "init", "reboot", "shutdown", "halt",
        "mount", "umount", "mkfs", "fdisk", "parted",

        # Package installation (system-level)
        "apt", "apt-get", "yum", "dnf", "apk", "pacman",

        # Network operations (can be enabled if needed)
        "nc", "netcat", "telnet", "nmap", "tcpdump", "wireshark",

        # Shell commands that can be abused
        "eval", "exec", "source", ".",

        # Compiler/interpreter that could be abused
        "gcc", "g++", "python3", "python", "perl", "ruby", "php",
    }

    # Dangerous patterns to detect
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",  # Recursive delete from root
        r">\s*/dev/",  # Writing to devices
        r";\s*rm\s+-rf",  # Chained dangerous delete
        r"\$\([^)]*\)",  # Command substitution
        r"`[^`]*`",  # Backtick command substitution
        r"&&\s*(sudo|rm\s+-rf)",  # Chained dangerous commands
        r"\|\s*sh",  # Piping to shell
        r"\|\s*bash",  # Piping to bash
        r"2>&1.*curl",  # Redirecting output to curl (potential exfiltration)
        r">\s*/etc/",  # Writing to system directories
        r"/var/run/docker\.sock",  # Docker socket access
    ]

    MAX_COMMAND_LENGTH = 1000
    MAX_ARGS = 50

    def __init__(self, allow_network: bool = False, custom_allowed: Optional[List[str]] = None):
        """
        Initialize the command validator.

        Args:
            allow_network: If True, allow network commands like curl, wget
            custom_allowed: Additional commands to allow beyond defaults
        """
        self.allow_network = allow_network
        self.allowed_commands = self.SAFE_COMMANDS.copy()

        if allow_network:
            self.allowed_commands.update({"curl", "wget", "fetch"})

        if custom_allowed:
            self.allowed_commands.update(custom_allowed)

        logger.info(f"CommandValidator initialized - network_allowed={allow_network}, "
                   f"total_allowed_commands={len(self.allowed_commands)}")

    def validate(self, command: str, working_dir: str = ".") -> ValidationResult:
        """
        Validate a command for security.

        Args:
            command: The command string to validate
            working_dir: The working directory (for path validation)

        Returns:
            ValidationResult with validation status and details
        """
        # 1. Length check
        if len(command) > self.MAX_COMMAND_LENGTH:
            return ValidationResult(
                is_valid=False,
                risk_level=CommandRisk.BLOCKED,
                reason=f"Command exceeds maximum length of {self.MAX_COMMAND_LENGTH} characters"
            )

        # 2. Empty command check
        command = command.strip()
        if not command:
            return ValidationResult(
                is_valid=False,
                risk_level=CommandRisk.BLOCKED,
                reason="Empty command"
            )

        # 3. Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return ValidationResult(
                    is_valid=False,
                    risk_level=CommandRisk.BLOCKED,
                    reason=f"Command contains dangerous pattern: {pattern}"
                )

        # 4. Parse command into tokens
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return ValidationResult(
                is_valid=False,
                risk_level=CommandRisk.BLOCKED,
                reason=f"Failed to parse command: {str(e)}"
            )

        if len(tokens) > self.MAX_ARGS:
            return ValidationResult(
                is_valid=False,
                risk_level=CommandRisk.BLOCKED,
                reason=f"Command has too many arguments (max {self.MAX_ARGS})"
            )

        # 5. Extract base command (handle command chaining)
        base_commands = self._extract_base_commands(command)

        # 6. Check each base command
        for base_cmd in base_commands:
            # Check if blocked
            if base_cmd in self.BLOCKED_COMMANDS:
                return ValidationResult(
                    is_valid=False,
                    risk_level=CommandRisk.BLOCKED,
                    reason=f"Command '{base_cmd}' is explicitly blocked for security"
                )

            # Check if allowed
            if base_cmd not in self.allowed_commands:
                return ValidationResult(
                    is_valid=False,
                    risk_level=CommandRisk.HIGH,
                    reason=f"Command '{base_cmd}' is not in the allowed list"
                )

        # 7. Check for risky arguments
        risk_level = self._assess_risk_level(tokens)

        # 8. Sanitize command (ensure it runs in correct directory)
        sanitized = self._sanitize_command(command, working_dir)

        logger.info(f"Command validated successfully: {command[:100]} - risk_level={risk_level.value}")

        return ValidationResult(
            is_valid=True,
            risk_level=risk_level,
            sanitized_command=sanitized,
            reason="Command passed validation"
        )

    def _extract_base_commands(self, command: str) -> List[str]:
        """
        Extract base commands from a potentially chained command.

        Handles: &&, ||, ;, |
        """
        # Split by common command separators
        parts = re.split(r'[;&|]+', command)

        base_commands = []
        for part in parts:
            part = part.strip()
            if part:
                tokens = shlex.split(part)
                if tokens:
                    base_commands.append(tokens[0])

        return base_commands

    def _assess_risk_level(self, tokens: List[str]) -> CommandRisk:
        """
        Assess the risk level of a command based on its tokens.
        """
        # Check for potentially dangerous arguments
        dangerous_flags = {
            "-rf", "--force", "--recursive", "--no-preserve-root",
            "-exec", "--exec", "-o", "--output"
        }

        for token in tokens:
            if token in dangerous_flags:
                return CommandRisk.MODERATE

        # Check for file deletion
        if "rm" in tokens:
            return CommandRisk.MODERATE

        return CommandRisk.SAFE

    def _sanitize_command(self, command: str, working_dir: str) -> List[str]:
        """
        Sanitize command to ensure it runs in the correct directory.

        Returns command as list suitable for execution.
        """
        # Ensure working_dir is safe (prevent directory traversal)
        safe_working_dir = working_dir.replace("..", "").strip("/")
        if not safe_working_dir or safe_working_dir == ".":
            full_path = "/app"
        else:
            full_path = f"/app/{safe_working_dir}"

        # Return command wrapped in shell with cd
        return ["/bin/sh", "-c", f"cd {shlex.quote(full_path)} && {command}"]


# Global validator instance
_validator_instance: Optional[CommandValidator] = None


def get_command_validator(allow_network: bool = False) -> CommandValidator:
    """Get or create the global command validator instance."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = CommandValidator(allow_network=allow_network)
    return _validator_instance
