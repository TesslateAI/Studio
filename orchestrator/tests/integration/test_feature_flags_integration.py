"""
Integration tests for the /api/feature-flags endpoint.

Tests the full HTTP request/response cycle through FastAPI.
The endpoint only serves public flags — backend-only flags are excluded.
"""

import pytest


@pytest.mark.integration
class TestFeatureFlagsEndpoint:
    """Test the GET /api/feature-flags endpoint."""

    def test_returns_200(self, api_client):
        response = api_client.get("/api/feature-flags")
        assert response.status_code == 200

    def test_response_shape(self, api_client):
        response = api_client.get("/api/feature-flags")
        data = response.json()
        assert "env" in data
        assert "flags" in data
        assert isinstance(data["env"], str)
        assert isinstance(data["flags"], dict)

    def test_flags_are_all_booleans(self, api_client):
        response = api_client.get("/api/feature-flags")
        data = response.json()
        for key, value in data["flags"].items():
            assert isinstance(value, bool), f"Flag '{key}' is {type(value).__name__}, expected bool"

    def test_only_public_flags_returned(self, api_client):
        """Endpoint should only return flags listed in the public list."""
        from app.services.feature_flags import get_feature_flags

        ff = get_feature_flags()
        response = api_client.get("/api/feature-flags")
        returned_flags = response.json()["flags"]

        assert returned_flags == ff.public_flags
        assert len(returned_flags) <= len(ff.flags)

    def test_backend_only_flags_excluded(self, api_client):
        """Agent capability flags should not be exposed."""
        response = api_client.get("/api/feature-flags")
        returned_flags = response.json()["flags"]
        for key in returned_flags:
            assert not key.startswith("agent_"), f"Backend-only flag '{key}' leaked to API"

    def test_no_auth_required(self, api_client):
        """Feature flags endpoint is public — no auth headers needed."""
        response = api_client.get("/api/feature-flags")
        assert response.status_code == 200

    def test_env_reflects_deployment_env(self, api_client):
        """The env field should match the DEPLOYMENT_ENV setting."""
        from app.config import get_settings

        settings = get_settings()
        response = api_client.get("/api/feature-flags")
        data = response.json()
        assert data["env"] == settings.deployment_env
