#!/usr/bin/env python3
"""
Complete cleanup script for LOCAL DEVELOPMENT (Docker mode).
Removes all projects, files, containers, and database entries.

IMPORTANT: This is for local Docker development only.
For Kubernetes/production cleanup, use kubectl commands directly.
"""

import sys
import os
import shutil
import subprocess
import sqlite3
from pathlib import Path

def log(message):
    print(f"[CLEANUP] {message}")

def cleanup_docker_containers():
    """Remove all Tesslate dev containers."""
    log("Cleaning up Docker containers...")

    try:
        # Stop and remove all tesslate dev containers
        result = subprocess.run([
            "docker", "ps", "-a",
            "--filter", "name=tesslate-dev-",
            "--format", "{{.Names}}"
        ], capture_output=True, text=True)

        if result.returncode == 0 and result.stdout.strip():
            containers = result.stdout.strip().split('\n')
            log(f"Found {len(containers)} Tesslate containers to remove")

            for container in containers:
                if container.strip():
                    log(f"Stopping and removing container: {container}")
                    subprocess.run(["docker", "stop", container], capture_output=True)
                    subprocess.run(["docker", "rm", "-f", container], capture_output=True)

        log("✓ All Docker containers cleaned up")

    except Exception as e:
        log(f"Error cleaning Docker containers: {e}")

def cleanup_docker_network():
    """Remove Tesslate Docker network."""
    log("Cleaning up Docker network...")

    try:
        network = "tesslate-network"
        result = subprocess.run([
            "docker", "network", "inspect", network
        ], capture_output=True)

        if result.returncode == 0:
            log(f"Removing network: {network}")
            subprocess.run(["docker", "network", "rm", network], capture_output=True)

        log("✓ Docker networks cleaned up")

    except Exception as e:
        log(f"Error cleaning Docker networks: {e}")

def cleanup_filesystem():
    """Remove all user project directories."""
    log("Cleaning up filesystem...")

    orchestrator_path = Path(__file__).parent.parent / "orchestrator"
    users_dir = orchestrator_path / "users"

    if users_dir.exists():
        log(f"Removing users directory: {users_dir}")
        try:
            shutil.rmtree(users_dir)
            log("✓ All user project files removed")
        except Exception as e:
            log(f"Error removing users directory: {e}")
    else:
        log("No users directory found")

def cleanup_database():
    """Clean all project data from database."""
    log("Cleaning up database...")

    orchestrator_path = Path(__file__).parent.parent / "orchestrator"
    db_path = orchestrator_path / "tesslate.db"

    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Get counts before cleanup
            cursor.execute("SELECT COUNT(*) FROM projects")
            project_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM project_files")
            file_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM chats")
            chat_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM messages")
            message_count = cursor.fetchone()[0]

            log(f"Found: {project_count} projects, {file_count} files, {chat_count} chats, {message_count} messages")

            # Clean up all project-related data
            cursor.execute("DELETE FROM messages")
            cursor.execute("DELETE FROM chats")
            cursor.execute("DELETE FROM project_files")
            cursor.execute("DELETE FROM projects")

            # Reset auto-increment counters
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('projects', 'project_files', 'chats', 'messages')")

            conn.commit()
            conn.close()

            log("✓ Database cleaned up - all projects, files, chats, and messages removed")

        except Exception as e:
            log(f"Error cleaning database: {e}")
    else:
        log("No database file found (this is normal if using PostgreSQL)")

def main():
    log("=== COMPLETE LOCAL CLEANUP (Docker Mode) ===")
    log("This will remove ALL projects, files, containers, and database entries!")
    log("")
    log("⚠️  WARNING: This script is for LOCAL DEVELOPMENT only (Docker mode).")
    log("⚠️  For Kubernetes/production, use kubectl commands instead.")
    log("")

    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    response = input("Are you sure you want to proceed? Type 'YES' to continue: ")
    if response != 'YES':
        log("Cleanup cancelled")
        return

    log("Starting complete cleanup...")

    # Clean up in order
    cleanup_docker_containers()
    cleanup_docker_network()
    cleanup_filesystem()
    cleanup_database()

    log("=== CLEANUP COMPLETE ===")
    log("✓ All Docker containers removed")
    log("✓ All Docker networks removed")
    log("✓ All project files removed")
    log("✓ All database entries removed")
    log("✓ System is now completely clean")
    log("")
    log("Next steps:")
    log("1. Clear browser localStorage (F12 > Console > localStorage.clear())")
    log("2. Restart the backend server")
    log("3. Create your first project - it will have ID 1")

if __name__ == "__main__":
    main()
