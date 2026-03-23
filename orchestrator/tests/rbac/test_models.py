"""
Unit tests for RBAC model definitions and constraints.

Verifies that models are correctly defined with the expected fields,
constraints, and relationships.
"""

import uuid

import pytest

from app.models_team import (
    AuditLog,
    ProjectMembership,
    Team,
    TeamInvitation,
    TeamMembership,
)


@pytest.mark.mocked
class TestTeamModel:
    def test_team_table_name(self):
        assert Team.__tablename__ == "teams"

    def test_team_has_billing_fields(self):
        """Team should have all billing fields moved from User."""
        billing_fields = [
            "subscription_tier",
            "stripe_customer_id",
            "stripe_subscription_id",
            "total_spend",
            "bundled_credits",
            "purchased_credits",
            "daily_credits",
            "signup_bonus_credits",
            "signup_bonus_expires_at",
            "credits_reset_date",
            "daily_credits_reset_date",
            "support_tier",
            "deployed_projects_count",
        ]
        for field in billing_fields:
            assert hasattr(Team, field), f"Team missing billing field: {field}"

    def test_team_total_credits_property(self):
        """Test the total_credits computed property."""
        team = Team()
        team.daily_credits = 5
        team.bundled_credits = 100
        team.purchased_credits = 50
        team.signup_bonus_credits = 25
        team.signup_bonus_expires_at = None
        assert team.total_credits == 180


@pytest.mark.mocked
class TestTeamMembershipModel:
    def test_table_name(self):
        assert TeamMembership.__tablename__ == "team_memberships"

    def test_has_role_field(self):
        assert hasattr(TeamMembership, "role")

    def test_has_is_active_field(self):
        assert hasattr(TeamMembership, "is_active")


@pytest.mark.mocked
class TestProjectMembershipModel:
    def test_table_name(self):
        assert ProjectMembership.__tablename__ == "project_memberships"

    def test_has_role_field(self):
        assert hasattr(ProjectMembership, "role")


@pytest.mark.mocked
class TestTeamInvitationModel:
    def test_table_name(self):
        assert TeamInvitation.__tablename__ == "team_invitations"

    def test_has_token_field(self):
        assert hasattr(TeamInvitation, "token")

    def test_has_max_uses_field(self):
        assert hasattr(TeamInvitation, "max_uses")


@pytest.mark.mocked
class TestAuditLogModel:
    def test_table_name(self):
        assert AuditLog.__tablename__ == "audit_logs"

    def test_has_action_field(self):
        assert hasattr(AuditLog, "action")

    def test_has_details_json_field(self):
        assert hasattr(AuditLog, "details")
