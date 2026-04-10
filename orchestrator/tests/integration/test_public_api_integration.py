"""
Integration tests for Public API (marketplace, models, usage).

Tests the full HTTP request/response cycle with mocked DB and external services.
Exercises router + auth + serialization pipeline end-to-end.

Requires: pip install httpx pytest-asyncio
"""

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> MagicMock:
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.is_active = overrides.get("is_active", True)
    user.default_team_id = overrides.get("default_team_id")
    user.daily_credits = overrides.get("daily_credits", 100)
    user.bundled_credits = overrides.get("bundled_credits", 500)
    user.signup_bonus_credits = overrides.get("signup_bonus_credits", 0)
    user.purchased_credits = overrides.get("purchased_credits", 1000)
    user.total_credits = overrides.get("total_credits", 1600)
    key = MagicMock()
    key.scopes = overrides.get("scopes")  # None = all allowed
    key.key_prefix = "tsk_test"
    key.name = "test-key"
    key.id = uuid.uuid4()
    user._api_key_record = key
    return user


def _make_agent(**overrides) -> MagicMock:
    agent = MagicMock()
    agent.id = overrides.get("id", uuid.uuid4())
    agent.name = overrides.get("name", "Test Agent")
    agent.slug = overrides.get("slug", "test-agent")
    agent.description = overrides.get("description", "A test agent")
    agent.category = overrides.get("category", "coding")
    agent.item_type = overrides.get("item_type", "agent")
    agent.icon = overrides.get("icon", "robot")
    agent.avatar_url = overrides.get("avatar_url")
    agent.pricing_type = overrides.get("pricing_type", "free")
    agent.price = overrides.get("price", 0)
    agent.downloads = overrides.get("downloads", 42)
    agent.rating = overrides.get("rating", 4.5)
    agent.reviews_count = overrides.get("reviews_count", 10)
    agent.tags = overrides.get("tags", ["python", "ai"])
    agent.is_featured = overrides.get("is_featured", False)
    agent.created_by_user_id = overrides.get("created_by_user_id")
    agent.created_by_user = overrides.get("created_by_user")
    agent.updated_at = overrides.get("updated_at", datetime.now(UTC))
    agent.is_active = True
    agent.is_published = True
    # Detail fields
    agent.long_description = overrides.get("long_description", "Longer desc")
    agent.system_prompt = overrides.get("system_prompt", "You are helpful.")
    agent.tools = overrides.get("tools", ["read_write", "bash"])
    agent.required_models = overrides.get("required_models")
    agent.features = overrides.get("features", ["feature-a"])
    agent.preview_image = overrides.get("preview_image")
    agent.source_type = overrides.get("source_type", "official")
    agent.git_repo_url = overrides.get("git_repo_url")
    agent.is_forkable = overrides.get("is_forkable", False)
    agent.model = overrides.get("model", "gpt-4o")
    agent.agent_type = overrides.get("agent_type", "coding")
    agent.skill_body = overrides.get("skill_body", "# skill body")
    agent.config = overrides.get("config", {"transport": "stdio"})
    agent.tool_configs = overrides.get("tool_configs")
    return agent


def _make_base(**overrides) -> MagicMock:
    base = MagicMock()
    base.id = overrides.get("id", uuid.uuid4())
    base.name = overrides.get("name", "React Starter")
    base.slug = overrides.get("slug", "react-starter")
    base.description = overrides.get("description", "A React template")
    base.category = overrides.get("category", "frontend")
    base.icon = overrides.get("icon", "react")
    base.preview_image = overrides.get("preview_image")
    base.pricing_type = overrides.get("pricing_type", "free")
    base.price = overrides.get("price", 0)
    base.downloads = overrides.get("downloads", 100)
    base.rating = overrides.get("rating", 4.8)
    base.reviews_count = overrides.get("reviews_count", 20)
    base.tags = overrides.get("tags", ["react", "vite"])
    base.tech_stack = overrides.get("tech_stack", ["React", "Vite", "TypeScript"])
    base.is_featured = overrides.get("is_featured", True)
    base.git_repo_url = overrides.get("git_repo_url", "https://github.com/example/react")
    base.default_branch = overrides.get("default_branch", "main")
    base.updated_at = overrides.get("updated_at", datetime.now(UTC))
    base.is_active = True
    base.visibility = "public"
    # Detail fields
    base.long_description = overrides.get("long_description", "Longer base desc")
    base.features = overrides.get("features", ["hot-reload"])
    base.source_type = overrides.get("source_type", "official")
    return base


def _make_theme(**overrides) -> MagicMock:
    theme = MagicMock()
    theme.id = overrides.get("id", uuid.uuid4())
    theme.name = overrides.get("name", "Midnight")
    theme.slug = overrides.get("slug", "midnight")
    theme.description = overrides.get("description", "A dark theme")
    theme.category = overrides.get("category", "dark")
    theme.mode = overrides.get("mode", "dark")
    theme.icon = overrides.get("icon", "moon")
    theme.preview_image = overrides.get("preview_image")
    theme.pricing_type = overrides.get("pricing_type", "free")
    theme.price = overrides.get("price", 0)
    theme.downloads = overrides.get("downloads", 50)
    theme.rating = overrides.get("rating", 4.2)
    theme.reviews_count = overrides.get("reviews_count", 5)
    theme.tags = overrides.get("tags", ["dark", "minimal"])
    theme.is_featured = overrides.get("is_featured", False)
    theme.author = overrides.get("author", "Tesslate")
    theme.version = overrides.get("version", "1.0.0")
    theme.is_active = True
    theme.is_published = True
    theme.updated_at = overrides.get("updated_at", datetime.now(UTC))
    theme.theme_json = overrides.get(
        "theme_json",
        {
            "colors": {
                "primary": "#6366f1",
                "accent": "#818cf8",
                "background": "#0f172a",
                "surface": "#1e293b",
            }
        },
    )
    # Detail fields
    theme.long_description = overrides.get("long_description", "Full theme desc")
    theme.source_type = overrides.get("source_type", "official")
    theme.parent_theme_id = overrides.get("parent_theme_id")
    return theme


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _scalar_one(value):
    """Mock result for .scalar_one() calls (count queries)."""
    m = MagicMock()
    m.scalar_one.return_value = value
    return m


def _scalars_all(items):
    """Mock result for .scalars().all() calls (list queries)."""
    m = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    m.scalars.return_value = scalars
    return m


def _scalar_one_or_none(value):
    """Mock result for .scalar_one_or_none() calls (detail queries)."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _row_result(rows):
    """Mock result for .all() returning tuples (usage aggregation)."""
    m = MagicMock()
    m.one.return_value = rows
    return m


def _rows_all(rows):
    """Mock result for .all() returning list of tuples."""
    m = MagicMock()
    m.all.return_value = rows
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_api_user():
    return _make_user()


@pytest.fixture(autouse=True)
def mock_database(mock_api_user):
    """Mock the database dependency for all tests."""
    from app.database import get_db
    from app.main import app

    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield mock_db
    # Don't clear here -- client fixture clears all overrides


@pytest.fixture
async def client(mock_api_user):
    from app.auth_external import get_external_api_user
    from app.main import app

    # Override auth to return our mock user
    app.dependency_overrides[get_external_api_user] = lambda: mock_api_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer tsk_test123"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def unauthed_client():
    """Client with no Authorization header."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestMarketplaceAuth:
    async def test_no_auth_returns_401(self, unauthed_client):
        resp = await unauthed_client.get("/api/public/marketplace/agents")
        assert resp.status_code == 401

    async def test_invalid_key_returns_401(self, unauthed_client, mock_database):
        # Auth code does db.execute(select(ExternalAPIKey)...).scalar_one_or_none()
        # Return None so key is "not found" → 401
        key_result = MagicMock()
        key_result.scalar_one_or_none.return_value = None
        mock_database.execute = AsyncMock(return_value=key_result)

        resp = await unauthed_client.get(
            "/api/public/marketplace/agents",
            headers={"Authorization": "Bearer tsk_invalid_garbage"},
        )
        assert resp.status_code == 401

    async def test_insufficient_scope_returns_403(self, mock_database):
        """Key with only chat.send scope cannot access marketplace.read."""
        user = _make_user(scopes=["chat.send"])

        from app.auth_external import get_external_api_user
        from app.main import app

        app.dependency_overrides[get_external_api_user] = lambda: user

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer tsk_scoped"},
        ) as ac:
            resp = await ac.get("/api/public/marketplace/agents")

        assert resp.status_code == 403
        assert "marketplace.read" in resp.json()["detail"]
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Marketplace Agents
# ---------------------------------------------------------------------------


class TestMarketplaceAgents:
    async def test_list_agents_returns_200(self, client, mock_database):
        agents = [_make_agent(name="Agent A"), _make_agent(name="Agent B")]
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(2), _scalars_all(agents)])

        resp = await client.get("/api/public/marketplace/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["items"][0]["name"] == "Agent A"
        assert "id" in body["items"][0]

    async def test_list_agents_pagination(self, client, mock_database):
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(50), _scalars_all([])])

        resp = await client.get("/api/public/marketplace/agents?page=3&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 50
        assert body["page"] == 3
        assert body["limit"] == 10
        assert body["total_pages"] == 5

    async def test_list_agents_has_cache_headers(self, client, mock_database):
        mock_database.execute = AsyncMock(
            side_effect=[_scalar_one(1), _scalars_all([_make_agent()])]
        )

        resp = await client.get("/api/public/marketplace/agents")
        assert resp.status_code == 200
        assert "etag" in resp.headers
        assert "max-age" in resp.headers.get("cache-control", "")

    async def test_get_agent_detail_200(self, client, mock_database):
        agent = _make_agent(system_prompt="Be precise.")
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(agent))

        resp = await client.get("/api/public/marketplace/agents/test-agent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["system_prompt"] == "Be precise."
        assert "long_description" in body

    async def test_get_agent_404(self, client, mock_database):
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        resp = await client.get("/api/public/marketplace/agents/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Agent Manifest
# ---------------------------------------------------------------------------


class TestAgentManifest:
    async def test_manifest_free_agent_200(self, client, mock_database, mock_api_user):
        agent = _make_agent(pricing_type="free", system_prompt="Manifest prompt")

        # Calls: find agent, _check_purchased (skipped for free), skills query, then
        # per-skill lookup(s), mcp query — with zero assignments the loop bodies
        # are never entered.
        mock_database.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(agent),  # find agent
                _scalars_all([]),  # skill assignments
                _scalars_all([]),  # mcp assignments
            ]
        )

        resp = await client.get("/api/public/marketplace/agents/test-agent/manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "1.0"
        assert body["agent"]["system_prompt"] == "Manifest prompt"
        assert isinstance(body["skills"], list)
        assert isinstance(body["mcp_servers"], list)

    async def test_manifest_paid_403(self, client, mock_database, mock_api_user):
        agent = _make_agent(pricing_type="paid", price=999)

        mock_database.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(agent),  # find agent
                _scalar_one_or_none(None),  # _check_purchased returns no purchase
            ]
        )

        resp = await client.get("/api/public/marketplace/agents/test-agent/manifest")
        assert resp.status_code == 403
        assert "Purchase required" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class TestSkills:
    async def test_list_skills_200(self, client, mock_database):
        skill = _make_agent(item_type="skill", name="Docker Skill")
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(1), _scalars_all([skill])])

        resp = await client.get("/api/public/marketplace/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Docker Skill"

    async def test_skill_body_free_200(self, client, mock_database):
        skill = _make_agent(
            item_type="skill",
            pricing_type="free",
            skill_body="# How to Docker",
        )
        # Calls: find skill, (free => no purchase check)
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(skill))

        resp = await client.get("/api/public/marketplace/skills/test-agent/body")
        assert resp.status_code == 200
        assert resp.json()["skill_body"] == "# How to Docker"

    async def test_skill_body_paid_403(self, client, mock_database):
        skill = _make_agent(item_type="skill", pricing_type="paid", price=499)
        mock_database.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(skill),  # find skill
                _scalar_one_or_none(None),  # no purchase record
            ]
        )

        resp = await client.get("/api/public/marketplace/skills/test-agent/body")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------


class TestBases:
    async def test_list_bases_200(self, client, mock_database):
        base = _make_base()
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(1), _scalars_all([base])])

        resp = await client.get("/api/public/marketplace/bases")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"][0]["git_repo_url"] == "https://github.com/example/react"

    async def test_base_detail_200(self, client, mock_database):
        base = _make_base(tech_stack=["Next.js", "Prisma"])
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(base))

        resp = await client.get("/api/public/marketplace/bases/react-starter")
        assert resp.status_code == 200
        body = resp.json()
        assert "Next.js" in body["tech_stack"]


# ---------------------------------------------------------------------------
# MCP Servers
# ---------------------------------------------------------------------------


class TestMcpServers:
    async def test_list_mcp_servers_200(self, client, mock_database):
        mcp = _make_agent(item_type="mcp_server", name="GitHub MCP")
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(1), _scalars_all([mcp])])

        resp = await client.get("/api/public/marketplace/mcp-servers")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["name"] == "GitHub MCP"

    async def test_mcp_server_detail_has_config(self, client, mock_database):
        mcp = _make_agent(
            item_type="mcp_server",
            config={"transport": "stdio", "command": "node"},
        )
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(mcp))

        resp = await client.get("/api/public/marketplace/mcp-servers/test-agent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["transport"] == "stdio"


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


class TestThemes:
    async def test_list_themes_no_json(self, client, mock_database):
        theme = _make_theme()
        mock_database.execute = AsyncMock(side_effect=[_scalar_one(1), _scalars_all([theme])])

        resp = await client.get("/api/public/marketplace/themes")
        assert resp.status_code == 200
        body = resp.json()
        # theme_json is excluded from list view
        assert "theme_json" not in body["items"][0]
        assert "color_swatches" in body["items"][0]

    async def test_theme_detail_has_json(self, client, mock_database):
        theme = _make_theme()
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(theme))

        resp = await client.get("/api/public/marketplace/themes/midnight")
        assert resp.status_code == 200
        body = resp.json()
        assert "theme_json" in body
        assert body["theme_json"]["colors"]["primary"] == "#6366f1"


# ---------------------------------------------------------------------------
# Model Proxy
# ---------------------------------------------------------------------------


class TestModelProxy:
    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    @patch("app.routers.public_models.deduct_credits", return_value={})
    @patch("app.routers.public_models.resolve_model_name", return_value="gpt-4o")
    async def test_chat_completions_non_streaming_200(
        self, mock_resolve, mock_deduct, mock_credits, mock_llm, client
    ):
        mock_client = AsyncMock()
        completion = MagicMock()
        completion.model_dump.return_value = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        completion.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        mock_client.chat.completions.create = AsyncMock(return_value=completion)
        mock_llm.return_value = mock_client

        resp = await client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        mock_deduct.assert_called_once()

    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    @patch("app.routers.public_models.resolve_model_name", return_value="gpt-4o")
    async def test_chat_completions_streaming_200(
        self, mock_resolve, mock_credits, mock_llm, client
    ):
        mock_client = AsyncMock()

        async def _fake_stream(**kwargs):
            chunk = MagicMock()
            chunk.model_dump.return_value = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Hi"}}],
            }
            chunk.usage = None
            yield chunk

        mock_client.chat.completions.create = AsyncMock(return_value=_fake_stream())
        mock_llm.return_value = mock_client

        resp = await client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @patch("app.routers.public_models.get_llm_client")
    @patch("app.routers.public_models.check_credits", return_value=(False, "Insufficient credits"))
    async def test_chat_completions_credit_failure_402(
        self, mock_credits, mock_llm, client, mock_database
    ):
        # Team lookup returns None
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        resp = await client.post(
            "/api/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert resp.status_code == 402

    @patch("app.routers.public_models.get_llm_client", side_effect=ValueError("Unknown model"))
    @patch("app.routers.public_models.check_credits", return_value=(True, ""))
    async def test_chat_completions_bad_model_400(
        self, mock_credits, mock_llm, client, mock_database
    ):
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        resp = await client.post(
            "/api/v1/chat/completions",
            json={
                "model": "nonexistent-model",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert resp.status_code == 400
        assert "Unknown model" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------


class TestModelsEndpoint:
    @patch("app.routers.public_models.LiteLLMService")
    async def test_list_models_200(self, mock_litellm_cls, client, mock_database):
        svc = AsyncMock()
        svc.get_available_models.return_value = [{"id": "gpt-4o"}]
        svc.get_model_info.return_value = [
            {
                "model_name": "gpt-4o",
                "model_info": {
                    "input_cost_per_token": 0.000005,
                    "output_cost_per_token": 0.000015,
                },
            }
        ]
        mock_litellm_cls.return_value = svc

        # Mock BYOK provider query returning no keys
        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert isinstance(body["data"], list)

    @patch("app.routers.public_models.LiteLLMService")
    async def test_list_models_cache_header(self, mock_litellm_cls, client, mock_database):
        svc = AsyncMock()
        svc.get_available_models.return_value = []
        svc.get_model_info.return_value = []
        mock_litellm_cls.return_value = svc

        mock_database.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        resp = await client.get("/api/v1/models")
        assert resp.status_code == 200
        assert "max-age" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# Usage endpoint
# ---------------------------------------------------------------------------


class TestUsageEndpoint:
    async def test_usage_returns_credits(self, client, mock_database, mock_api_user):
        # Calls: 30d total summary, per-model breakdown
        mock_database.execute = AsyncMock(
            side_effect=[
                _row_result((150, 4200, 50000, 12000)),  # total summary
                _rows_all([("gpt-4o", 100, 3000), ("claude-3", 50, 1200)]),  # by model
            ]
        )

        resp = await client.get("/api/v1/usage")
        assert resp.status_code == 200
        body = resp.json()
        credits = body["credits"]
        assert credits["daily"] == 100
        assert credits["bundled"] == 500
        assert credits["total"] == 1600

    async def test_usage_30d_summary(self, client, mock_database):
        mock_database.execute = AsyncMock(
            side_effect=[
                _row_result((75, 1500, 30000, 8000)),
                _rows_all([("gpt-4o", 75, 1500)]),
            ]
        )

        resp = await client.get("/api/v1/usage")
        assert resp.status_code == 200
        body = resp.json()
        usage = body["usage_30d"]
        assert usage["total_requests"] == 75
        assert usage["total_cost_cents"] == 1500
        assert usage["total_tokens_in"] == 30000
        assert usage["total_tokens_out"] == 8000
        assert len(usage["by_model"]) == 1
        assert usage["by_model"][0]["model"] == "gpt-4o"
