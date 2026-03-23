"""
Unit tests for the audit trail service.

Tests non-blocking behavior, field extraction, and error handling.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit_service import cleanup_expired_audit_logs, log_event


@pytest.mark.mocked
class TestLogEvent:
    @pytest.mark.asyncio
    async def test_creates_audit_entry(self):
        """log_event should add an AuditLog to the session."""
        db = AsyncMock()

        await log_event(
            db=db,
            team_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="member.invited",
            resource_type="team_membership",
            details={"email": "test@example.com", "role": "editor"},
        )

        db.add.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_ip_and_user_agent_from_request(self):
        """log_event should extract IP and user-agent from the request."""
        db = AsyncMock()
        request = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers.get.return_value = "Mozilla/5.0 Test Agent"

        await log_event(
            db=db,
            team_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="project.created",
            resource_type="project",
            request=request,
        )

        # Verify the AuditLog entry was created with IP and user-agent
        call_args = db.add.call_args[0][0]
        assert call_args.ip_address == "192.168.1.100"
        assert call_args.user_agent == "Mozilla/5.0 Test Agent"

    @pytest.mark.asyncio
    async def test_works_without_request(self):
        """log_event should work when request=None."""
        db = AsyncMock()

        await log_event(
            db=db,
            team_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="billing.credits_purchased",
            resource_type="team",
        )

        call_args = db.add.call_args[0][0]
        assert call_args.ip_address is None
        assert call_args.user_agent is None

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self):
        """log_event should catch exceptions and not raise (non-blocking)."""
        db = AsyncMock()
        db.flush.side_effect = Exception("DB connection failed")

        # Should NOT raise
        await log_event(
            db=db,
            team_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="test.action",
            resource_type="test",
        )

    @pytest.mark.asyncio
    async def test_sets_project_id_when_provided(self):
        """log_event should set project_id for project-scoped events."""
        db = AsyncMock()
        project_id = uuid.uuid4()

        await log_event(
            db=db,
            team_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="container.started",
            resource_type="container",
            project_id=project_id,
        )

        call_args = db.add.call_args[0][0]
        assert call_args.project_id == project_id


@pytest.mark.mocked
class TestCleanupExpiredAuditLogs:
    @pytest.mark.asyncio
    async def test_executes_delete_and_commits(self):
        """cleanup_expired_audit_logs should execute a delete and commit."""
        db = AsyncMock()

        await cleanup_expired_audit_logs(db, retention_days=90)

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_raise_on_error(self):
        """cleanup should catch exceptions and not raise."""
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")

        # Should NOT raise
        await cleanup_expired_audit_logs(db)
