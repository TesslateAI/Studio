from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..database import get_db
from ..models import Project, User, ProjectFile, Chat, Message
from ..schemas import Project as ProjectSchema, ProjectCreate, ProjectFile as ProjectFileSchema
from ..auth import get_current_active_user
from ..dev_server_manager import dev_container_manager
import os
import shutil
import asyncio

router = APIRouter()

@router.get("/", response_model=List[ProjectSchema])
async def get_projects(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(Project.owner_id == current_user.id)
    )
    projects = result.scalars().all()
    return projects

@router.post("/", response_model=ProjectSchema)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    db_project = Project(
        name=project.name,
        description=project.description,
        owner_id=current_user.id
    )
    db.add(db_project)
    await db.commit()
    await db.refresh(db_project)
    
    # Create project directory with absolute paths for reliability
    project_dir = os.path.abspath(f"users/{current_user.id}/projects/{db_project.id}")
    
    try:
        # Ensure parent directories exist
        os.makedirs(os.path.dirname(project_dir), exist_ok=True)
        
        # Get absolute template directory path
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "template"))
        
        print(f"Creating project {db_project.id} for user {current_user.id}")
        print(f"Template directory: {template_dir}")
        print(f"Project directory: {project_dir}")
        print(f"Template exists: {os.path.exists(template_dir)}")
        
        # Verify template directory exists
        if not os.path.exists(template_dir):
            print(f"❌ Template directory not found: {template_dir}")
            raise HTTPException(
                status_code=500, 
                detail=f"Template directory not found. Please ensure the server is properly configured."
            )
        
        # Remove project directory if it exists to start fresh
        if os.path.exists(project_dir):
            print(f"Removing existing project directory: {project_dir}")
            shutil.rmtree(project_dir)
        
        # Copy template to project directory
        print(f"Copying template from {template_dir} to {project_dir}")
        shutil.copytree(template_dir, project_dir)
        
        # Verify the copy was successful
        required_files = ['package.json', 'index.html', 'vite.config.js']
        missing_files = []
        for required_file in required_files:
            file_path = os.path.join(project_dir, required_file)
            if not os.path.exists(file_path):
                missing_files.append(required_file)
        
        if missing_files:
            print(f"Missing required files after template copy: {missing_files}")
            raise HTTPException(
                status_code=500,
                detail=f"Template copy incomplete. Missing files: {', '.join(missing_files)}"
            )
        
        print(f"Template successfully copied to {project_dir}")
        
        # Save template files to database for tracking and editing
        files_saved = 0
        for root, dirs, files in os.walk(project_dir):
            # Skip node_modules, .git, dist, build directories for database storage
            dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]
            
            for file in files:
                # Skip system files, locks, and binary files
                if (file.startswith('.') or 
                    file.endswith(('.lock', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')) or 
                    file in ['package-lock.json']):
                    continue
                    
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, project_dir).replace('\\', '/')
                
                try:
                    # Read file content with proper encoding handling
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    
                    # Save to database
                    db_file = ProjectFile(
                        project_id=db_project.id,
                        file_path=relative_path,
                        content=content
                    )
                    db.add(db_file)
                    files_saved += 1
                    
                except Exception as e:
                    print(f"Warning: Could not read file {relative_path}: {e}")
                    continue
        
        # Commit all database changes
        await db.commit()
        print(f"Saved {files_saved} template files to database for project {db_project.id}")
        
        # Final verification that project is ready
        package_json_path = os.path.join(project_dir, 'package.json')
        node_modules_path = os.path.join(project_dir, 'node_modules')
        
        if not os.path.exists(package_json_path):
            raise HTTPException(
                status_code=500,
                detail="Project creation failed: package.json not found after template copy"
            )
        
        if not os.path.exists(node_modules_path):
            print(f"node_modules not found - will be installed when dev server starts")
        else:
            print(f"node_modules found in template")
        
        print(f"Project {db_project.id} created successfully!")
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"Critical error during project creation: {e}")
        import traceback
        traceback.print_exc()
        
        # Clean up failed project
        try:
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
            await db.delete(db_project)
            await db.commit()
        except Exception as cleanup_error:
            print(f"Error during cleanup: {cleanup_error}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create project: {str(e)}"
        )
    
    return db_project

@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/files", response_model=List[ProjectFileSchema])
async def get_project_files(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get files
    result = await db.execute(
        select(ProjectFile).where(ProjectFile.project_id == project_id)
    )
    files = result.scalars().all()
    return files

@router.post("/{project_id}/start-dev-container")
async def start_dev_container(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Start dev container
    project_path = f"users/{current_user.id}/projects/{project_id}"
    try:
        port = await dev_container_manager.start_container(project_path, str(project_id), current_user.id)
        return {"url": f"http://127.0.0.1:{port}", "port": port}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{project_id}/restart-dev-container")
async def restart_dev_container(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Restart dev container
    project_path = f"users/{current_user.id}/projects/{project_id}"
    try:
        hostname = await dev_container_manager.restart_container(project_path, str(project_id), current_user.id)
        return {"url": hostname, "hostname": hostname, "message": "Dev container restarted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart dev container: {str(e)}")

@router.post("/{project_id}/stop-dev-container")
async def stop_dev_container(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Stop dev container
    try:
        await dev_container_manager.stop_container(str(project_id), current_user.id)
        return {"message": "Dev container stopped successfully", "project_id": project_id}
    except Exception as e:
        # Don't fail if container is already stopped
        return {"message": "Container stop attempted", "project_id": project_id}

@router.get("/{project_id}/dev-server-url")
async def get_dev_server_url(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    url = dev_container_manager.get_container_url(str(project_id), current_user.id)
    if url:
        print(f"Dev container already running for user {current_user.id}, project {project_id}: {url}")
        return {"url": url}
    else:
        # Try to start the container
        project_path = os.path.abspath(f"users/{current_user.id}/projects/{project_id}")
        print(f"Starting dev container for user {current_user.id}, project {project_id} at {project_path}")
        
        # Check if project has required files, if not, fix it by copying template
        required_files = ["package.json", "vite.config.js", "index.html"]
        missing_files = []
        
        for required_file in required_files:
            file_path = os.path.join(project_path, required_file)
            if not os.path.exists(file_path):
                missing_files.append(required_file)
        
        if missing_files:
            print(f"Project {project_id} missing required files: {missing_files}")
            print(f"Fixing project by copying template...")
            
            try:
                # Get template directory
                template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "template"))
                
                if not os.path.exists(template_dir):
                    raise HTTPException(
                        status_code=500,
                        detail="Template directory not found. Cannot fix broken project."
                    )
                
                # Ensure project directory exists
                os.makedirs(project_path, exist_ok=True)
                
                # Copy template files to project (preserving any existing files)
                for root, dirs, files in os.walk(template_dir):
                    # Skip node_modules for now - will be installed by container build
                    if 'node_modules' in root:
                        continue
                        
                    rel_dir = os.path.relpath(root, template_dir)
                    dest_dir = os.path.join(project_path, rel_dir) if rel_dir != '.' else project_path
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    for file in files:
                        src_file = os.path.join(root, file)
                        dest_file = os.path.join(dest_dir, file)
                        
                        # Only copy if file doesn't exist or is a required file
                        if not os.path.exists(dest_file) or file in required_files:
                            shutil.copy2(src_file, dest_file)
                
                # Verify the fix worked
                still_missing = []
                for required_file in required_files:
                    file_path = os.path.join(project_path, required_file)
                    if not os.path.exists(file_path):
                        still_missing.append(required_file)
                
                if still_missing:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to fix project. Still missing: {', '.join(still_missing)}"
                    )
                
                print(f"Successfully fixed project {project_id}")
                
                # Save copied files to database for tracking
                files_saved = 0
                for root, dirs, files in os.walk(project_path):
                    # Skip node_modules, .git, dist, build directories for database storage
                    dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]
                    
                    for file in files:
                        # Skip system files, locks, and binary files
                        if (file.startswith('.') or 
                            file.endswith(('.lock', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')) or 
                            file in ['package-lock.json']):
                            continue
                            
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, project_path).replace('\\', '/')
                        
                        try:
                            # Check if file already exists in database
                            existing_result = await db.execute(
                                select(ProjectFile).where(
                                    ProjectFile.project_id == project_id,
                                    ProjectFile.file_path == relative_path
                                )
                            )
                            existing_file = existing_result.scalar_one_or_none()
                            
                            if not existing_file:
                                # Read file content with proper encoding handling
                                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()
                                
                                # Save to database
                                db_file = ProjectFile(
                                    project_id=project_id,
                                    file_path=relative_path,
                                    content=content
                                )
                                db.add(db_file)
                                files_saved += 1
                                
                        except Exception as e:
                            print(f"Warning: Could not save file {relative_path} to database: {e}")
                            continue
                
                if files_saved > 0:
                    await db.commit()
                    print(f"Saved {files_saved} new files to database for project {project_id}")
                        
            except HTTPException:
                raise
            except Exception as e:
                print(f"Error fixing project: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(
                    status_code=500, 
                    detail=f"Failed to fix broken project: {str(e)}"
                )
        
        try:
            url = await dev_container_manager.start_container(project_path, str(project_id), current_user.id)
            return {"url": url}
        except Exception as e:
            print(f"[ERROR] Dev container startup error: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Dev container failed to start: {str(e)}")

@router.get("/{project_id}/container-status")
async def get_container_status(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    status = dev_container_manager.get_container_status(str(project_id), current_user.id)
    return status

@router.post("/{project_id}/files/save")
async def save_project_file(
    project_id: int,
    file_data: dict,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    file_path = file_data.get('file_path')
    content = file_data.get('content')
    
    if not file_path or content is None:
        raise HTTPException(status_code=400, detail="file_path and content are required")
    
    # Write to disk (for container to see changes)
    project_dir = os.path.abspath(f"users/{current_user.id}/projects/{project_id}")
    full_file_path = os.path.join(project_dir, file_path)
    
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(full_file_path), exist_ok=True)
        
        # Write file to disk
        with open(full_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"[FILE] Saved {file_path} to disk ({len(content)} chars)")
        
        # Update database
        result = await db.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.file_path == file_path
            )
        )
        existing_file = result.scalar_one_or_none()
        
        if existing_file:
            existing_file.content = content
        else:
            new_file = ProjectFile(
                project_id=project_id,
                file_path=file_path,
                content=content
            )
            db.add(new_file)
        
        await db.commit()
        
        return {"message": "File saved successfully", "file_path": file_path}
        
    except Exception as e:
        print(f"[ERROR] Failed to save file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@router.get("/containers/all")
async def get_all_dev_containers(
    current_user: User = Depends(get_current_active_user)
):
    """Get all running development containers (for admin/debugging)."""
    try:
        containers = dev_container_manager.get_all_containers()
        # Filter to show only containers for current user unless admin
        user_containers = [c for c in containers if c.get('user_id') == current_user.id]
        return {
            "containers": user_containers,
            "total": len(user_containers),
            "user_id": current_user.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get containers: {str(e)}")

@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a project and ALL associated data including chats, messages, files, and containers."""
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    try:
        print(f"[DELETE] Starting deletion of project {project_id} for user {current_user.id}")
        
        # 1. Stop and remove any running containers
        try:
            await dev_container_manager.stop_container(str(project_id), current_user.id)
            print(f"[DELETE] Stopped containers for project {project_id}")
        except Exception as e:
            print(f"[DELETE] Error stopping containers: {e}")
        
        # 2. Delete all chats associated with this project (and their messages will cascade)
        chats_result = await db.execute(
            select(Chat).where(Chat.project_id == project_id)
        )
        project_chats = chats_result.scalars().all()
        
        for chat in project_chats:
            print(f"[DELETE] Deleting chat {chat.id} with messages")
            # Delete messages first (explicit cleanup)
            await db.execute(delete(Message).where(Message.chat_id == chat.id))
            await db.execute(delete(Chat).where(Chat.id == chat.id))
        
        print(f"[DELETE] Deleted {len(project_chats)} chats and their messages")
        
        # 3. Delete project files from database (cascade should handle this, but be explicit)
        await db.execute(delete(ProjectFile).where(ProjectFile.project_id == project_id))
        print(f"[DELETE] Deleted project files from database")
        
        # 4. Delete project from database
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()
        print(f"[DELETE] Deleted project from database")
        
        # 5. Delete filesystem directory
        project_dir = f"users/{current_user.id}/projects/{project_id}"
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            print(f"[DELETE] Deleted filesystem directory: {project_dir}")
        
        print(f"[DELETE] Successfully deleted project {project_id}")
        return {"message": "Project deleted successfully", "project_id": project_id}
        
    except Exception as e:
        await db.rollback()
        print(f"[DELETE] Error during project deletion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")