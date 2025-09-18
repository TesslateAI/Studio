#!/usr/bin/env python3
"""
Complete cleanup script - removes all projects, files, containers, and database entries.
This gives you a completely clean slate to start fresh.
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
    """Remove all builder dev containers."""
    log("Cleaning up Docker containers...")
    
    try:
        # Stop and remove all builder dev containers
        result = subprocess.run([
            "docker", "ps", "-a", 
            "--filter", "label=com.builder.devserver=true",
            "--format", "{{.Names}}"
        ], capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            containers = result.stdout.strip().split('\n')
            log(f"Found {len(containers)} builder containers to remove")
            
            for container in containers:
                if container.strip():
                    log(f"Stopping and removing container: {container}")
                    subprocess.run(["docker", "stop", container], capture_output=True)
                    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        
        # Also remove any containers with old naming pattern
        result = subprocess.run([
            "docker", "ps", "-a", 
            "--filter", "name=devserver-",
            "--format", "{{.Names}}"
        ], capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            old_containers = result.stdout.strip().split('\n')
            log(f"Found {len(old_containers)} old-style containers to remove")
            
            for container in old_containers:
                if container.strip():
                    log(f"Stopping and removing old container: {container}")
                    subprocess.run(["docker", "stop", container], capture_output=True)
                    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        
        log("✓ All Docker containers cleaned up")
        
    except Exception as e:
        log(f"Error cleaning Docker containers: {e}")

def cleanup_docker_network():
    """Remove builder Docker network."""
    log("Cleaning up Docker network...")
    
    try:
        networks = ["builder-devserver-network", "devserver-network"]
        for network in networks:
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
    
    backend_path = Path(__file__).parent / "builder" / "backend"
    users_dir = backend_path / "users"
    
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
    
    backend_path = Path(__file__).parent / "builder" / "backend"
    db_path = backend_path / "app" / "app.db"
    
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
        log("No database file found")

def cleanup_local_storage_info():
    """Provide info about cleaning browser localStorage."""
    log("Browser localStorage cleanup needed...")
    log("To complete the cleanup, open your browser's DevTools and run:")
    log("  // Clear all chat history")
    log("  Object.keys(localStorage).forEach(key => {")
    log("    if (key.startsWith('chat_history_')) {")
    log("      localStorage.removeItem(key);")
    log("    }")
    log("  });")
    log("  // Clear other app data")
    log("  localStorage.removeItem('token');")
    log("  localStorage.removeItem('active_tab_');")

def main():
    log("=== COMPLETE SYSTEM CLEANUP ===")
    log("This will remove ALL projects, files, containers, and database entries!")
    
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
    cleanup_local_storage_info()
    
    log("=== CLEANUP COMPLETE ===")
    log("✓ All Docker containers removed")
    log("✓ All Docker networks removed")
    log("✓ All project files removed")
    log("✓ All database entries removed")
    log("✓ System is now completely clean")
    log("")
    log("Next steps:")
    log("1. Clear browser localStorage using the commands above")
    log("2. Restart the backend server")
    log("3. Create your first project - it will have ID 1")
    log("4. All containers will start fresh with proper naming")

if __name__ == "__main__":
    main()