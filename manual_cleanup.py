#!/usr/bin/env python3
"""
Manual cleanup - for when the backend is running
"""

import sqlite3
import os
from pathlib import Path

def cleanup_database():
    """Clean all project data from database while backend is running."""
    print("Cleaning database...")
    
    backend_path = Path(__file__).parent / "builder" / "backend"
    db_path = backend_path / "builder.db"
    
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Get counts before cleanup
            cursor.execute("SELECT COUNT(*) FROM projects")
            project_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM project_files") 
            file_count = cursor.fetchone()[0]
            
            print(f"Removing {project_count} projects and {file_count} files from database...")
            
            # Clean up all project-related data
            cursor.execute("DELETE FROM messages")
            cursor.execute("DELETE FROM chats") 
            cursor.execute("DELETE FROM project_files")
            cursor.execute("DELETE FROM projects")
            
            # Reset auto-increment counters
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('projects', 'project_files', 'chats', 'messages')")
            
            conn.commit()
            conn.close()
            
            print("Database cleaned - all projects and files removed")
            
        except Exception as e:
            print(f"Error cleaning database: {e}")
    else:
        print("No database file found")

if __name__ == "__main__":
    cleanup_database()