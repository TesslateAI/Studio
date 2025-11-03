#!/usr/bin/env python3
"""
Script to update all router files to use fastapi-users authentication dependencies.

This script replaces old JWT authentication dependencies with fastapi-users dependencies:
- get_current_user → current_active_user
- get_current_active_user → current_active_user
- admin_required → current_superuser (from ..users import)
"""
import re
from pathlib import Path

# Router files to update (excluding auth.py which we already updated)
ROUTER_FILES = [
    "app/routers/admin.py",
    "app/routers/agent.py",
    "app/routers/agents.py",
    "app/routers/chat.py",
    "app/routers/git.py",
    "app/routers/github.py",
    "app/routers/kanban.py",
    "app/routers/marketplace.py",
    "app/routers/projects.py",
    "app/routers/referrals.py",
    "app/routers/secrets.py",
    "app/routers/shell.py",
    "app/routers/users.py",
]


def update_router_file(filepath: Path):
    """Update a single router file."""
    print(f"Updating {filepath}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # Replace imports
    # Remove old auth imports
    content = re.sub(
        r'from \.\.auth import.*?\n',
        '',
        content
    )

    # Add new imports from users if not already there
    if 'from ..users import' not in content:
        # Find the last import line from ..
        import_lines = []
        for line in content.split('\n'):
            if line.startswith('from ..'):
                import_lines.append(line)

        if import_lines:
            last_import = import_lines[-1]
            # Insert new import after last .. import
            content = content.replace(
                last_import,
                last_import + '\nfrom ..users import current_active_user, current_superuser'
            )

    # Replace function parameters
    # get_current_user → current_active_user
    content = re.sub(
        r'get_current_user',
        'current_active_user',
        content
    )

    # get_current_active_user → current_active_user (might already be replaced above)
    content = re.sub(
        r'get_current_active_user',
        'current_active_user',
        content
    )

    # admin_required → current_superuser
    content = re.sub(
        r'admin_required',
        'current_superuser',
        content
    )

    # Check if changes were made
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] Updated {filepath}")
        return True
    else:
        print(f"  [SKIP] No changes needed for {filepath}")
        return False


def main():
    """Main entry point."""
    base_path = Path(__file__).parent

    print("=" * 60)
    print("Updating Router Files for fastapi-users")
    print("=" * 60)
    print()

    updated_count = 0

    for router_file in ROUTER_FILES:
        filepath = base_path / router_file
        if filepath.exists():
            if update_router_file(filepath):
                updated_count += 1
        else:
            print(f"  [WARN] File not found: {filepath}")

    print()
    print("=" * 60)
    print(f"[SUCCESS] Updated {updated_count} router files")
    print("=" * 60)


if __name__ == "__main__":
    main()
