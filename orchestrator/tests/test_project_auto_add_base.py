"""
Unit tests for the auto-add base to library logic in project creation.

Tests the _ensure_user_has_base function's behavior when a user creates a project
with a base that is/isn't in their library.
"""

import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def mock_task():
    """Create a mock Task for progress tracking."""
    task = Mock()
    task.update_progress = Mock()
    return task


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = Mock()
    settings.deployment_mode = "docker"
    return settings


@pytest.fixture
def base_id():
    return uuid.uuid4()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def mock_base(base_id):
    """Create a mock free MarketplaceBase."""
    base = Mock()
    base.id = base_id
    base.name = "Next.js 16"
    base.slug = "nextjs-16"
    base.source_type = "git"
    base.pricing_type = "free"
    base.git_repo_url = "https://github.com/tesslate/nextjs-16.git"
    base.downloads = 5
    return base


@pytest.fixture
def mock_project(user_id):
    """Create a mock db project."""
    project = Mock()
    project.id = uuid.uuid4()
    project.name = "Test Project"
    project.slug = "test-project-abc123"
    project.owner_id = user_id
    return project


@pytest.fixture
def mock_project_data(base_id):
    """Create a mock ProjectCreate schema."""
    data = Mock()
    data.base_id = base_id
    data.source_type = "base"
    data.name = "Test Project"
    return data


def _make_db(base, purchase=None):
    """Helper to create a mock db session with base lookup and purchase query."""
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=base)
    mock_db.scalar = AsyncMock(return_value=purchase)
    mock_db.add = Mock()
    mock_db.flush = AsyncMock()
    return mock_db


async def _run_ensure(mock_project_data, mock_project, mock_base, mock_db):
    """Run _ensure_user_has_base from the new pipeline module."""
    from app.services.project_setup.pipeline import _ensure_user_has_base

    await _ensure_user_has_base(mock_base, mock_project_data, mock_db, mock_project)


# ============================================================================
# Auto-add free base to library
# ============================================================================


@pytest.mark.asyncio
async def test_auto_add_free_base_to_library(
    mock_project_data, mock_project, user_id, mock_settings, mock_task, mock_base
):
    """When user creates a project with a free base NOT in their library, it should be auto-added."""
    from app.models import UserPurchasedBase

    mock_db = _make_db(mock_base, purchase=None)

    await _run_ensure(mock_project_data, mock_project, mock_base, mock_db)

    # Verify db.add was called with a UserPurchasedBase
    assert mock_db.add.called, "db.add should have been called to auto-add base to library"
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, UserPurchasedBase)
    assert added_obj.user_id == user_id
    assert added_obj.base_id == mock_project_data.base_id
    assert added_obj.purchase_type == "free"
    assert added_obj.is_active is True

    # Verify download count was incremented
    assert mock_base.downloads == 6

    # Verify flush was called to persist before continuing
    assert mock_db.flush.called


# ============================================================================
# No duplicate when already in library
# ============================================================================


@pytest.mark.asyncio
async def test_no_duplicate_when_base_already_in_library(
    mock_project_data, mock_project, user_id, mock_settings, mock_task, mock_base
):
    """When user already has the active base in their library, no duplicate should be created."""
    existing_purchase = Mock()
    existing_purchase.user_id = user_id
    existing_purchase.base_id = mock_project_data.base_id
    existing_purchase.is_active = True

    mock_db = _make_db(mock_base, purchase=existing_purchase)
    original_downloads = mock_base.downloads

    await _run_ensure(mock_project_data, mock_project, mock_base, mock_db)

    # db.add should NOT have been called
    assert not mock_db.add.called, "db.add should NOT be called when base is already in library"

    # Download count should not change
    assert mock_base.downloads == original_downloads


# ============================================================================
# Re-activate deactivated purchase
# ============================================================================


@pytest.mark.asyncio
async def test_reactivate_deactivated_free_base(
    mock_project_data, mock_project, user_id, mock_settings, mock_task, mock_base
):
    """When user has a deactivated purchase of a free base, it should be re-activated."""
    deactivated_purchase = Mock()
    deactivated_purchase.user_id = user_id
    deactivated_purchase.base_id = mock_project_data.base_id
    deactivated_purchase.is_active = False

    mock_db = _make_db(mock_base, purchase=deactivated_purchase)

    await _run_ensure(mock_project_data, mock_project, mock_base, mock_db)

    # Purchase should be re-activated (not a new one created)
    assert not mock_db.add.called, "db.add should NOT be called for re-activation"
    assert deactivated_purchase.is_active is True
    assert deactivated_purchase.purchase_date is not None

    # Download count should increment
    assert mock_base.downloads == 6
    assert mock_db.flush.called


# ============================================================================
# Paid base rejection
# ============================================================================


@pytest.mark.asyncio
async def test_paid_base_not_in_library_raises_error(
    mock_project_data, mock_project, user_id, mock_settings, mock_task, mock_base
):
    """When user tries to create a project with a paid base not in their library, it should fail."""
    mock_base.pricing_type = "one_time"

    mock_db = _make_db(mock_base, purchase=None)

    with pytest.raises(ValueError, match="requires purchase"):
        await _run_ensure(mock_project_data, mock_project, mock_base, mock_db)


@pytest.mark.asyncio
async def test_paid_base_deactivated_raises_error(
    mock_project_data, mock_project, user_id, mock_settings, mock_task, mock_base
):
    """When user has a deactivated purchase of a paid base, it should not re-activate for free."""
    mock_base.pricing_type = "monthly"

    deactivated_purchase = Mock()
    deactivated_purchase.user_id = user_id
    deactivated_purchase.base_id = mock_project_data.base_id
    deactivated_purchase.is_active = False

    mock_db = _make_db(mock_base, purchase=deactivated_purchase)

    with pytest.raises(ValueError, match="requires purchase"):
        await _run_ensure(mock_project_data, mock_project, mock_base, mock_db)

    # Should NOT have been re-activated
    assert deactivated_purchase.is_active is False


# ============================================================================
# Base not found
# ============================================================================


@pytest.mark.asyncio
async def test_base_not_found_raises_error(
    mock_project_data, mock_project, user_id, mock_settings, mock_task
):
    """When the base_id doesn't exist, a ValueError should be raised."""
    from app.services.project_setup.pipeline import _build_source_spec

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="Project base not found"):
        await _build_source_spec(mock_project_data, mock_project, mock_settings, mock_db)
