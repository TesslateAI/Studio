"""
Background worker functions for project creation
This file contains the code to be inserted into projects.py before the create_project endpoint
"""

async def _perform_project_setup(
    project_data: ProjectCreate,
    db_project_id: UUID,
    db_project_slug: str,
    user_id: UUID,
    settings,
    task: Task
) -> None:
    """
    Background worker function that performs project setup operations.

    Args:
        project_data: Original project creation request
        db_project_id: Database project ID (already created)
        db_project_slug: Database project slug
        user_id: User ID
        settings: Application settings
        task: Task object for progress tracking
    """
    from ..database import AsyncSessionLocal

    # Create a new database session for this background task
    async with AsyncSessionLocal() as db:
        try:
            # Fetch the project from DB
            from sqlalchemy import select
            result = await db.execute(
                select(Project).where(Project.id == db_project_id)
            )
            db_project = result.scalar_one()

            project_path = os.path.abspath(get_project_path(user_id, db_project.id))

            # Step 1: Create directory (5%)
            task.update_progress(5, 100, "Creating project directory")
            if settings.deployment_mode == "docker":
                try:
                    await makedirs_async(project_path)
                    logger.info(f"[CREATE] Created project directory: {project_path}")
                except Exception as e:
                    logger.warning(f"[CREATE] mkdir failed: {e}, trying subprocess")
                    import subprocess
                    await asyncio.to_thread(
                        subprocess.run,
                        ['mkdir', '-p', project_path],
                        check=False,
                        capture_output=True
                    )
                await asyncio.sleep(0.1)

            # Handle different source types
            if project_data.source_type == "github":
                await _setup_github_project(project_data, db_project, user_id, settings, db, task, project_path)
            elif project_data.source_type == "base":
                await _setup_base_project(project_data, db_project, user_id, settings, db, task, project_path)
            else:
                # Template mode (default)
                task.update_progress(10, 100, "Initializing from template")
                await _setup_template_project(db_project, project_path, settings, db, task)

            # Final step: Complete
            task.update_progress(100, 100, "Project setup complete")
            logger.info(f"[CREATE] Project {db_project.id} setup completed successfully")

        except Exception as e:
            logger.error(f"[CREATE] Background task error: {e}", exc_info=True)
            raise


async def _setup_github_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str
) -> None:
    """Setup project from GitHub repository"""
    # Step 2: Clone repository (10-40%)
    task.update_progress(10, 100, f"Cloning repository from GitHub: {project_data.github_repo_url}")
    logger.info(f"[CREATE] Importing from GitHub: {project_data.github_repo_url}")

    # Get GitHub credentials
    from ..services.credential_manager import get_credential_manager
    credential_manager = get_credential_manager()
    access_token = await credential_manager.get_access_token(db, user_id)

    # Clone repository
    from ..services.git_manager import GitManager
    from ..services.github_client import GitHubClient
    from ..services.project_patcher import ProjectPatcher

    repo_info = GitHubClient.parse_repo_url(project_data.github_repo_url)
    if not repo_info:
        raise ValueError("Invalid GitHub repository URL")

    # Get default branch
    branch = project_data.github_branch or "main"
    if not project_data.github_branch and access_token:
        try:
            github_client = GitHubClient(access_token)
            branch = await github_client.get_default_branch(repo_info['owner'], repo_info['repo'])
        except:
            pass

    git_manager = GitManager(user_id, str(db_project.id))
    await git_manager.clone_repository(
        repo_url=project_data.github_repo_url,
        branch=branch,
        auth_token=access_token,
        direct_to_filesystem=(settings.deployment_mode == "docker")
    )

    task.update_progress(40, 100, "Repository cloned successfully")

    # Step 3: Auto-patch project (40-60%)
    task.update_progress(50, 100, "Patching project for Tesslate compatibility")
    if settings.deployment_mode == "docker":
        try:
            patcher = ProjectPatcher(project_path)
            await patcher.auto_patch()
        except Exception as patch_error:
            logger.warning(f"[CREATE] Auto-patch error: {patch_error}")

    task.update_progress(60, 100, "Patching complete")

    # Step 4: Save files to database (60-90%)
    if settings.deployment_mode == "docker":
        task.update_progress(65, 100, "Saving cloned files to database")
        files_saved = 0
        walk_results = await walk_directory_async(
            project_path,
            exclude_dirs=['node_modules', '.git', 'dist', 'build', '.next']
        )

        for root, dirs, files in walk_results:
            for file in files:
                if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')):
                    continue

                file_full_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_full_path, project_path).replace('\\', '/')

                try:
                    content = await read_file_async(file_full_path)
                    db_file = ProjectFile(
                        project_id=db_project.id,
                        file_path=relative_path,
                        content=content
                    )
                    db.add(db_file)
                    files_saved += 1
                except Exception as e:
                    logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")

        await db.commit()
        task.update_progress(90, 100, f"Saved {files_saved} files to database")

    # Update project with Git info
    db_project.has_git_repo = True
    db_project.git_remote_url = project_data.github_repo_url

    from ..models import GitRepository
    git_repo = GitRepository(
        project_id=db_project.id,
        user_id=user_id,
        repo_url=project_data.github_repo_url,
        repo_name=repo_info['repo'],
        repo_owner=repo_info['owner'],
        default_branch=branch,
        auth_method='pat' if access_token else 'none'
    )
    db.add(git_repo)
    await db.commit()


async def _setup_base_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str
) -> None:
    """Setup project from marketplace base"""
    task.update_progress(10, 100, f"Cloning marketplace base: {project_data.base_id}")

    if not project_data.base_id:
        raise ValueError("base_id is required for source_type 'base'")

    # Verify purchase
    from ..models import UserPurchasedBase, MarketplaceBase
    from sqlalchemy import select
    purchase = await db.scalar(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == user_id,
            UserPurchasedBase.base_id == project_data.base_id,
            UserPurchasedBase.is_active == True
        )
    )
    if not purchase:
        raise ValueError("You have not acquired this project base.")

    base_repo = await db.get(MarketplaceBase, project_data.base_id)
    if not base_repo:
        raise ValueError("Project base not found.")

    try:
        from ..services.git_manager import GitManager
        from ..services.credential_manager import get_credential_manager

        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, user_id)

        git_manager = GitManager(user_id, str(db_project.id))
        await git_manager.clone_repository(
            repo_url=base_repo.git_repo_url,
            branch=base_repo.default_branch,
            auth_token=access_token,
            direct_to_filesystem=(settings.deployment_mode == "docker")
        )

        task.update_progress(40, 100, "Base cloned successfully")

        # Save files if Docker mode
        if settings.deployment_mode == "docker":
            task.update_progress(65, 100, "Saving base files to database")
            files_saved = 0
            walk_results = await walk_directory_async(
                project_path,
                exclude_dirs=['node_modules', '.git', 'dist', 'build', '.next']
            )

            for root, dirs, files in walk_results:
                for file in files:
                    if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')):
                        continue

                    file_full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_full_path, project_path).replace('\\', '/')

                    try:
                        content = await read_file_async(file_full_path)
                        db_file = ProjectFile(
                            project_id=db_project.id,
                            file_path=relative_path,
                            content=content
                        )
                        db.add(db_file)
                        files_saved += 1
                    except Exception as e:
                        logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")

            await db.commit()
            task.update_progress(90, 100, f"Saved {files_saved} files to database")

        db_project.has_git_repo = True
        db_project.git_remote_url = base_repo.git_repo_url
        await db.commit()

    except Exception as git_error:
        logger.error(f"[CREATE] Failed to clone base: {git_error}", exc_info=True)
        # Fallback to template
        task.update_progress(40, 100, "Base clone failed, using fallback template")
        await _setup_template_project(db_project, project_path, settings, db, task)


async def _setup_template_project(
    db_project: Project,
    project_path: str,
    settings,
    db: AsyncSession,
    task: Task
) -> None:
    """Setup project from template"""
    logger.info(f"[CREATE] Initializing from template")

    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "template"))

    if not os.path.exists(template_dir):
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Step 1: Save template files to database (10-70%)
    task.update_progress(20, 100, "Reading template files")
    files_saved = 0

    walk_results = await walk_directory_async(
        template_dir,
        exclude_dirs=['node_modules', '.git', 'dist', 'build', '.next']
    )

    for root, dirs, files in walk_results:
        for file in files:
            if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')):
                continue

            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, template_dir).replace('\\', '/')

            try:
                content = await read_file_async(file_path)
                db_file = ProjectFile(
                    project_id=db_project.id,
                    file_path=relative_path,
                    content=content
                )
                db.add(db_file)
                files_saved += 1
            except Exception as e:
                logger.warning(f"[CREATE] Could not read template file {relative_path}: {e}")

    await db.commit()
    task.update_progress(70, 100, f"Saved {files_saved} template files to database")

    # Step 2: In Docker mode, copy template files to filesystem (70-95%)
    if settings.deployment_mode == "docker":
        task.update_progress(75, 100, "Copying template files to filesystem")
        try:
            walk_results = await walk_directory_async(
                template_dir,
                exclude_dirs=['node_modules', '.git', 'dist', 'build', '.next']
            )

            for root, dirs, files in walk_results:
                for file in files:
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, template_dir)
                    dst_path = os.path.join(project_path, rel_path)

                    parent_dir = os.path.dirname(dst_path)
                    if parent_dir:
                        await makedirs_async(parent_dir)

                    await copy_file_async(src_path, dst_path)

            task.update_progress(95, 100, "Template files copied to filesystem")
        except Exception as copy_error:
            logger.error(f"[CREATE] Failed to copy template files: {copy_error}", exc_info=True)
