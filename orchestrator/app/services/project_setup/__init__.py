"""Project setup pipeline — public API.

Usage::

    from app.services.project_setup import setup_project

    result = await setup_project(project_data, db_project, user_id, settings, db, task)
    # result.container_id  — primary container ID
    # result.container_ids — all container IDs
"""

from .pipeline import SetupResult, setup_project

__all__ = ["SetupResult", "setup_project"]
