"""
Security tests for referral endpoints (GitHub issue #344).

Tests assert the SECURE behavior that the fix must provide:
- GET /api/referrals/stats requires authentication -> 401 when anonymous
- Response payload does not leak PII (email, username) of referral conversions
- POST /api/track-landing rejects unknown ref codes

These tests FAIL against the vulnerable code and PASS after the fix.
"""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# 1. Authentication requirement on GET /api/referrals/stats
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReferralStatsRequiresAuth:
    """GET /api/referrals/stats must reject anonymous requests."""

    def test_anonymous_returns_401(self, api_client):
        """Anonymous access to /api/referrals/stats must be blocked."""
        response = api_client.get("/api/referrals/stats")
        assert response.status_code == 401, (
            f"SECURITY: /api/referrals/stats accessible without auth (got {response.status_code})"
        )

    def test_authenticated_returns_200(self, authenticated_client):
        """Authenticated users can access referral stats."""
        client, _ = authenticated_client
        response = client.get("/api/referrals/stats")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. PII must not be present in the stats response
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReferralStatsNoPII:
    """Stats response must never expose email or username."""

    def test_no_email_or_username_in_response(self, authenticated_client, tmp_path):
        """latest_conversion must not contain email or username fields."""
        client, _ = authenticated_client

        # Get the user's referral code from their profile
        me_resp = client.get("/api/users/me")
        assert me_resp.status_code == 200
        referral_code = me_resp.json().get("referral_code")
        assert referral_code, "User should have a referral_code"

        # Seed referral data using the authenticated user's own referral code
        db_path = tmp_path / "referrals.db"
        with patch("app.referral_db.DB_PATH", db_path):
            from app.referral_db import init_db, save_conversion, save_landing

            init_db()
            save_landing(referral_code, "1.2.3.4", "TestAgent")
            save_conversion(
                referral_code,
                "uid-1",
                "secret_user",
                "secret@example.com",
                "Secret Name",
            )

            response = client.get("/api/referrals/stats")

        assert response.status_code == 200
        data = response.json()

        # There should be at least one stat entry (the seeded referral)
        stats = data.get("stats", [])
        assert len(stats) > 0, "Expected at least one stat entry for seeded referral"

        for stat in stats:
            lc = stat.get("latest_conversion")
            if lc is not None:
                assert "email" not in lc, "PII leak: email exposed in referral stats"
                assert "username" not in lc, "PII leak: username exposed in referral stats"


# ---------------------------------------------------------------------------
# 3. POST /api/track-landing must validate ref codes
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTrackLandingValidation:
    """POST /api/track-landing must reject unknown ref codes."""

    def test_unknown_ref_rejected(self, api_client):
        """track-landing with a ref code that belongs to no user must be rejected."""
        response = api_client.post(
            "/api/track-landing", params={"ref": "BOGUS_NONEXISTENT_CODE_XYZ"}
        )
        assert response.status_code in (400, 404), (
            f"track-landing accepted unknown ref code (got {response.status_code})"
        )
