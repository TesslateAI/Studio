#!/usr/bin/env python3
"""
Tesslate Studio - Environment Configuration Verifier
Cross-platform Python script to verify .env configuration
"""

import os
import sys
import re
from pathlib import Path

# Set UTF-8 encoding for Windows
if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8')

# ANSI color codes for terminal output (works on Windows 10+ and Unix)
class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'

def enable_windows_ansi():
    """Enable ANSI color codes on Windows."""
    if os.name == 'nt':
        os.system('')  # Enables ANSI escape sequences on Windows

def read_env_file(filepath='.env'):
    """Read and parse .env file."""
    env_vars = {}

    if not Path(filepath).exists():
        return None

    with open(filepath, 'r') as f:
        for line in f:
            # Skip comments and empty lines
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Parse key=value pairs
            match = re.match(r'^([^=]+)=(.*)$', line)
            if match:
                key, value = match.groups()
                key = key.strip()
                value = value.strip()

                # Handle variable substitution
                # Replace ${VAR} patterns with actual values
                def replace_var(match):
                    var_name = match.group(1)
                    return env_vars.get(var_name, match.group(0))

                value = re.sub(r'\$\{([^}]+)\}', replace_var, value)
                env_vars[key] = value

    return env_vars

def print_header():
    """Print the header."""
    print(f"{Colors.CYAN}{'='*60}")
    print("Tesslate Studio - Environment Configuration Check")
    print(f"{'='*60}{Colors.RESET}")
    print()

def check_configuration():
    """Check the environment configuration."""
    enable_windows_ansi()
    print_header()

    # Check if .env exists
    if not Path('.env').exists():
        print(f"{Colors.RED}❌ ERROR: .env file not found!")
        print(f"{Colors.YELLOW}   Run: copy .env.example .env (Windows)")
        print(f"   Run: cp .env.example .env (Mac/Linux){Colors.RESET}")
        return False

    print(f"{Colors.GREEN}✅ .env file found{Colors.RESET}")
    print()

    # Read environment variables
    env_vars = read_env_file()

    if not env_vars:
        print(f"{Colors.RED}❌ ERROR: Could not parse .env file!{Colors.RESET}")
        return False

    # Display current configuration
    print(f"{Colors.WHITE}Current Configuration:")
    print("-" * 30)

    domain = env_vars.get('APP_DOMAIN', 'localhost')
    protocol = env_vars.get('APP_PROTOCOL', 'http')
    app_url = f"{protocol}://{domain}"

    print(f"{Colors.CYAN}🌐 Domain: {domain}")
    print(f"🔒 Protocol: {protocol}")
    print(f"🔗 Full URL: {app_url}")
    print(f"🚪 Ports:")
    print(f"{Colors.GRAY}   - Web: {env_vars.get('APP_PORT', '80')}")
    print(f"   - Secure: {env_vars.get('APP_SECURE_PORT', '443')}")
    print(f"   - Backend: {env_vars.get('BACKEND_PORT', '8000')}")
    print(f"   - Frontend: {env_vars.get('FRONTEND_PORT', '5173')}")
    print(f"   - Traefik: {env_vars.get('TRAEFIK_DASHBOARD_PORT', '8080')}{Colors.RESET}")
    print()

    # Check required variables
    print(f"{Colors.WHITE}Required Variables Check:")
    print("-" * 30)

    has_errors = False
    has_warnings = False

    # Check SECRET_KEY
    secret_key = env_vars.get('SECRET_KEY', '')
    if not secret_key or secret_key == 'change-this-to-a-random-secret-key-for-security':
        print(f"{Colors.RED}❌ SECRET_KEY not configured (using default is insecure){Colors.RESET}")
        has_errors = True
    else:
        print(f"{Colors.GREEN}✅ SECRET_KEY is configured{Colors.RESET}")

    # Check LiteLLM Configuration
    litellm_base = env_vars.get('LITELLM_API_BASE', '')
    litellm_key = env_vars.get('LITELLM_MASTER_KEY', '')
    litellm_models = env_vars.get('LITELLM_DEFAULT_MODELS', '')

    if not litellm_key or litellm_key == 'your-litellm-master-key-here':
        print(f"{Colors.YELLOW}⚠️  LITELLM_MASTER_KEY not configured (AI features won't work){Colors.RESET}")
        print(f"{Colors.GRAY}      Using LiteLLM proxy at: {litellm_base}{Colors.RESET}")
        has_warnings = True
    else:
        print(f"{Colors.GREEN}✅ LiteLLM proxy configured at {litellm_base}{Colors.RESET}")

        # Display configured models
        if litellm_models:
            models_list = [m.strip() for m in litellm_models.split(',')]
            print(f"{Colors.GREEN}   Configured AI models:{Colors.RESET}")
            for model in models_list:
                print(f"{Colors.GRAY}      - {model}{Colors.RESET}")

    print()

    # Check optional features
    print(f"{Colors.WHITE}Optional Features:")
    print("-" * 30)

    # GitHub OAuth
    github_id = env_vars.get('GITHUB_CLIENT_ID', '')
    if github_id and github_id != 'your_github_client_id_here':
        print(f"{Colors.GREEN}✅ GitHub OAuth configured{Colors.RESET}")
    else:
        print(f"{Colors.GRAY}ℹ️  GitHub OAuth not configured (optional){Colors.RESET}")

    print()
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")

    # Final status
    if has_errors:
        print(f"{Colors.RED}❌ Configuration has errors. Please fix them before starting.{Colors.RESET}")
        return False
    elif has_warnings:
        print(f"{Colors.YELLOW}⚠️  Configuration has warnings. Some features may not work.{Colors.RESET}")
    else:
        print(f"{Colors.GREEN}✅ Configuration is perfect!{Colors.RESET}")

    print()
    print(f"{Colors.WHITE}To start the application:")
    print(f"{Colors.GRAY}  docker-compose up -d{Colors.RESET}")
    print()
    print(f"{Colors.WHITE}Then access at:")
    print(f"{Colors.GREEN}  🚀 Application: {app_url}")
    print(f"  📊 Traefik Dashboard: {app_url}/traefik (admin:admin){Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")

    return not has_errors

if __name__ == '__main__':
    # Change to project root directory if running from scripts/deployment folder
    script_dir = Path(__file__).parent
    if script_dir.name == 'deployment':
        # We're in scripts/deployment, go up two levels to project root
        os.chdir(script_dir.parent.parent)
    elif script_dir.name == 'scripts':
        # Legacy path handling in case script is moved back to scripts/
        os.chdir(script_dir.parent)

    success = check_configuration()
    sys.exit(0 if success else 1)