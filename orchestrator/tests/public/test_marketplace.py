"""Unit tests for the desktop marketplace router helpers and endpoints."""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401 — register all ORM models
from app.routers.public._shared import (
    add_cache_headers,
    ownership_filter,
    paginated_response,
)
from app.routers.public.marketplace import (
    _agent_to_dict,
    _base_to_dict,
    _check_purchased,
    _theme_to_dict,
    get_agent,
    get_agent_manifest,
    get_base,
    get_mcp_server,
    get_skill,
    get_skill_body,
    get_theme,
    list_agents,
    list_bases,
    list_mcp_servers,
    list_skills,
    list_themes,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(default_team_id=None):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.default_team_id = default_team_id or uuid.uuid4()
    return user


def _make_agent(item_type="agent", pricing_type="free", **overrides):
    agent = MagicMock()
    agent.id = overrides.get("id", uuid.uuid4())
    agent.name = overrides.get("name", "Test Agent")
    agent.slug = overrides.get("slug", "test-agent")
    agent.description = overrides.get("description", "A test agent")
    agent.category = overrides.get("category", "general")
    agent.item_type = item_type
    agent.icon = overrides.get("icon", "icon.png")
    agent.avatar_url = overrides.get("avatar_url")
    agent.pricing_type = pricing_type
    agent.price = overrides.get("price", 0)
    agent.downloads = overrides.get("downloads", 42)
    agent.rating = overrides.get("rating", 4.5)
    agent.reviews_count = overrides.get("reviews_count", 10)
    agent.tags = overrides.get("tags", ["ai", "code"])
    agent.is_featured = overrides.get("is_featured", False)
    agent.created_by_user_id = overrides.get("created_by_user_id")
    agent.created_by_user = overrides.get("created_by_user")
    agent.updated_at = overrides.get("updated_at", "2025-01-01")
    # Detail fields
    agent.long_description = overrides.get("long_description", "Long desc")
    agent.system_prompt = overrides.get("system_prompt", "You are helpful.")
    agent.tools = overrides.get("tools", ["read_file"])
    agent.required_models = overrides.get("required_models")
    agent.features = overrides.get("features", ["feat1"])
    agent.preview_image = overrides.get("preview_image")
    agent.source_type = overrides.get("source_type", "official")
    agent.git_repo_url = overrides.get("git_repo_url")
    agent.is_forkable = overrides.get("is_forkable", True)
    agent.model = overrides.get("model", "gpt-4")
    agent.agent_type = overrides.get("agent_type", "coding")
    agent.skill_body = overrides.get("skill_body", "# Skill body")
    agent.config = overrides.get("config", {"env_vars": ["API_KEY"]})
    agent.tool_configs = overrides.get("tool_configs")
    return agent


def _make_base(**overrides):
    base = MagicMock()
    base.id = overrides.get("id", uuid.uuid4())
    base.name = overrides.get("name", "React Starter")
    base.slug = overrides.get("slug", "react-starter")
    base.description = overrides.get("description", "A React base")
    base.category = overrides.get("category", "frontend")
    base.icon = overrides.get("icon", "react.png")
    base.preview_image = overrides.get("preview_image")
    base.pricing_type = overrides.get("pricing_type", "free")
    base.price = overrides.get("price", 0)
    base.downloads = overrides.get("downloads", 100)
    base.rating = overrides.get("rating", 4.8)
    base.reviews_count = overrides.get("reviews_count", 20)
    base.tags = overrides.get("tags", ["react", "vite"])
    base.tech_stack = overrides.get("tech_stack", ["react", "typescript"])
    base.is_featured = overrides.get("is_featured", True)
    base.git_repo_url = overrides.get("git_repo_url", "https://github.com/test/repo")
    base.default_branch = overrides.get("default_branch", "main")
    base.updated_at = overrides.get("updated_at", "2025-01-01")
    # Detail fields
    base.long_description = overrides.get("long_description", "Long base desc")
    base.features = overrides.get("features", ["hot-reload"])
    base.source_type = overrides.get("source_type", "official")
    return base


def _make_theme(**overrides):
    theme = MagicMock()
    theme.id = overrides.get("id", uuid.uuid4())
    theme.name = overrides.get("name", "Dark Mode Pro")
    theme.slug = overrides.get("slug", "dark-mode-pro")
    theme.description = overrides.get("description", "A dark theme")
    theme.category = overrides.get("category", "dark")
    theme.mode = overrides.get("mode", "dark")
    theme.icon = overrides.get("icon", "moon.png")
    theme.preview_image = overrides.get("preview_image")
    theme.pricing_type = overrides.get("pricing_type", "free")
    theme.price = overrides.get("price", 0)
    theme.downloads = overrides.get("downloads", 200)
    theme.rating = overrides.get("rating", 4.9)
    theme.reviews_count = overrides.get("reviews_count", 50)
    theme.tags = overrides.get("tags", ["dark", "minimal"])
    theme.is_featured = overrides.get("is_featured", True)
    theme.author = overrides.get("author", "Tesslate")
    theme.version = overrides.get("version", "1.0.0")
    theme.theme_json = overrides.get(
        "theme_json",
        {
            "colors": {
                "primary": "#6366f1",
                "accent": "#a855f7",
                "background": "#0f172a",
                "surface": "#1e293b",
            }
        },
    )
    theme.updated_at = overrides.get("updated_at", "2025-01-01")
    # Detail fields
    theme.long_description = overrides.get("long_description", "Long theme desc")
    theme.source_type = overrides.get("source_type", "official")
    theme.parent_theme_id = overrides.get("parent_theme_id")
    return theme


def _make_api_key(scopes=None):
    key = MagicMock()
    key.id = uuid.uuid4()
    key.scopes = scopes or ["marketplace:read"]
    key.is_active = True
    return key


# ---------------------------------------------------------------------------
# Helper to build mock db execute side_effect for paginated list endpoints
# ---------------------------------------------------------------------------


def _mock_paginated_db(total: int, items: list):
    """Return an AsyncMock db whose execute returns count then rows."""
    mock_db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    rows_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    rows_result.scalars.return_value = scalars_mock

    mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])
    return mock_db


def _mock_detail_db(item):
    """Return an AsyncMock db whose execute returns a single item or None."""
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    mock_db.execute = AsyncMock(return_value=result)
    return mock_db


# ===========================================================================
# TestHelpers
# ===========================================================================


@pytest.mark.unit
class TestHelpers:
    def test_agent_to_dict_basic(self):
        agent = _make_agent(price=999)
        d = _agent_to_dict(agent)
        assert d["name"] == "Test Agent"
        assert d["slug"] == "test-agent"
        assert d["price"] == 9.99
        assert d["downloads"] == 42
        assert d["rating"] == 4.5
        assert d["reviews_count"] == 10
        assert d["tags"] == ["ai", "code"]
        assert d["is_featured"] is False
        assert d["creator_type"] == "official"
        assert d["creator_name"] == "Tesslate"
        # Detail fields must NOT be present in basic mode
        assert "system_prompt" not in d
        assert "long_description" not in d

    def test_agent_to_dict_detail(self):
        agent = _make_agent(system_prompt="Be helpful.", long_description="More info")
        d = _agent_to_dict(agent, include_detail=True)
        assert d["system_prompt"] == "Be helpful."
        assert d["long_description"] == "More info"
        assert "tools" in d
        assert "model" in d
        assert "agent_type" in d

    def test_agent_to_dict_community_creator(self):
        creator = MagicMock()
        creator.username = "alice"
        agent = _make_agent(created_by_user_id=uuid.uuid4(), created_by_user=creator)
        d = _agent_to_dict(agent)
        assert d["creator_type"] == "community"
        assert d["creator_name"] == "alice"

    def test_base_to_dict_basic(self):
        base = _make_base()
        d = _base_to_dict(base)
        assert d["name"] == "React Starter"
        assert d["git_repo_url"] == "https://github.com/test/repo"
        assert d["tech_stack"] == ["react", "typescript"]
        assert "long_description" not in d

    def test_theme_to_dict_basic(self):
        theme = _make_theme()
        d = _theme_to_dict(theme)
        assert d["name"] == "Dark Mode Pro"
        assert d["color_swatches"]["primary"] == "#6366f1"
        assert d["color_swatches"]["accent"] == "#a855f7"
        assert d["color_swatches"]["background"] == "#0f172a"
        assert d["color_swatches"]["surface"] == "#1e293b"
        assert "theme_json" not in d

    def test_theme_to_dict_detail(self):
        theme = _make_theme()
        d = _theme_to_dict(theme, include_detail=True)
        assert "theme_json" in d
        assert d["theme_json"]["colors"]["primary"] == "#6366f1"
        assert d["long_description"] == "Long theme desc"
        assert d["parent_theme_id"] is None

    def test_ownership_filter_team(self):
        team_id = uuid.uuid4()
        user = _make_user(default_team_id=team_id)
        model_class = MagicMock()
        ownership_filter(user, model_class)
        model_class.team_id.__eq__.assert_called_once_with(team_id)

    def test_ownership_filter_user(self):
        user = _make_user(default_team_id=None)
        model_class = MagicMock()
        ownership_filter(user, model_class)
        model_class.user_id.__eq__.assert_called_once_with(user.id)

    @pytest.mark.asyncio
    async def test_check_purchased_free(self):
        agent = _make_agent(pricing_type="free")
        db = AsyncMock()
        result = await _check_purchased(_make_user(), agent, db)
        assert result is True
        # DB should not be queried for free items
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_purchased_paid_not_owned(self):
        agent = _make_agent(pricing_type="paid")
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=exec_result)
        result = await _check_purchased(_make_user(), agent, db)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_purchased_paid_owned(self):
        agent = _make_agent(pricing_type="paid")
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = uuid.uuid4()  # purchase exists
        db.execute = AsyncMock(return_value=exec_result)
        result = await _check_purchased(_make_user(), agent, db)
        assert result is True

    def testadd_cache_headers(self):
        response = MagicMock()
        response.headers = {}
        add_cache_headers(response, "test-source", max_age=600)
        expected_etag = hashlib.md5(b"test-source").hexdigest()
        assert response.headers["ETag"] == expected_etag
        assert response.headers["Cache-Control"] == "public, max-age=600"

    def testpaginated_response(self):
        items = [{"id": "1"}, {"id": "2"}]
        result = paginated_response(items, total=25, page=2, limit=10)
        assert result["items"] == items
        assert result["total"] == 25
        assert result["page"] == 2
        assert result["limit"] == 10
        assert result["total_pages"] == 3  # ceil(25/10)

    def test_paginated_response_single_page(self):
        result = paginated_response([], total=5, page=1, limit=20)
        assert result["total_pages"] == 1


# ===========================================================================
# TestAgentEndpoints
# ===========================================================================


@pytest.mark.unit
class TestAgentEndpoints:
    @pytest.mark.asyncio
    async def test_list_agents_basic(self):
        agents = [_make_agent(name="Agent A"), _make_agent(name="Agent B")]
        mock_db = _mock_paginated_db(total=2, items=agents)
        response = MagicMock()
        response.headers = {}

        result = await list_agents(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search=None,
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "Agent A"
        assert result["items"][1]["name"] == "Agent B"
        assert "ETag" in response.headers

    @pytest.mark.asyncio
    async def test_list_agents_search(self):
        agents = [_make_agent(name="Search Hit")]
        mock_db = _mock_paginated_db(total=1, items=agents)
        response = MagicMock()
        response.headers = {}

        result = await list_agents(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search="search",
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 1
        assert result["items"][0]["name"] == "Search Hit"

    @pytest.mark.asyncio
    async def test_get_agent_detail(self):
        agent = _make_agent(system_prompt="Be great.")
        mock_db = _mock_detail_db(agent)
        response = MagicMock()
        response.headers = {}

        result = await get_agent(
            slug="test-agent",
            response=response,
            user=_make_user(),
            db=mock_db,
        )
        assert result["name"] == "Test Agent"
        assert result["system_prompt"] == "Be great."

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        mock_db = _mock_detail_db(None)
        response = MagicMock()
        response.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            await get_agent(
                slug="nonexistent",
                response=response,
                user=_make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 404


# ===========================================================================
# TestManifestEndpoint
# ===========================================================================


@pytest.mark.unit
class TestManifestEndpoint:
    @pytest.mark.asyncio
    async def test_manifest_free_agent(self):
        agent = _make_agent(
            pricing_type="free",
            system_prompt="Prompt here",
            tools=["bash_exec"],
            model="claude-sonnet",
            agent_type="coding",
        )

        mock_db = AsyncMock()

        # Call 1: get agent by slug
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent

        # Call 2: skill assignments (empty)
        skill_assign_result = MagicMock()
        skill_scalars = MagicMock()
        skill_scalars.all.return_value = []
        skill_assign_result.scalars.return_value = skill_scalars

        # Call 3: mcp assignments (empty)
        mcp_assign_result = MagicMock()
        mcp_scalars = MagicMock()
        mcp_scalars.all.return_value = []
        mcp_assign_result.scalars.return_value = mcp_scalars

        mock_db.execute = AsyncMock(
            side_effect=[agent_result, skill_assign_result, mcp_assign_result]
        )

        result = await get_agent_manifest(
            slug="test-agent",
            user=_make_user(),
            db=mock_db,
        )
        assert result["version"] == "1.0"
        assert result["agent"]["system_prompt"] == "Prompt here"
        assert result["skills"] == []
        assert result["mcp_servers"] == []

    @pytest.mark.asyncio
    async def test_manifest_paid_not_purchased(self):
        agent = _make_agent(pricing_type="paid", price=999)

        mock_db = AsyncMock()

        # Call 1: get agent by slug
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent

        # Call 2: purchase check returns None (not purchased)
        purchase_result = MagicMock()
        purchase_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[agent_result, purchase_result])

        with pytest.raises(HTTPException) as exc_info:
            await get_agent_manifest(
                slug="test-agent",
                user=_make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 403


# ===========================================================================
# TestSkillEndpoints
# ===========================================================================


@pytest.mark.unit
class TestSkillEndpoints:
    @pytest.mark.asyncio
    async def test_list_skills(self):
        skills = [_make_agent(item_type="skill", name="Skill A")]
        mock_db = _mock_paginated_db(total=1, items=skills)
        response = MagicMock()
        response.headers = {}

        result = await list_skills(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search=None,
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 1
        assert result["items"][0]["item_type"] == "skill"

    @pytest.mark.asyncio
    async def test_get_skill_body_free(self):
        skill = _make_agent(
            item_type="skill",
            pricing_type="free",
            skill_body="# Do the thing",
        )
        mock_db = _mock_detail_db(skill)

        result = await get_skill_body(
            slug="test-skill",
            user=_make_user(),
            db=mock_db,
        )
        assert result["skill_body"] == "# Do the thing"
        assert result["slug"] == "test-agent"

    @pytest.mark.asyncio
    async def test_get_skill_body_paid_403(self):
        skill = _make_agent(item_type="skill", pricing_type="paid", price=500)

        mock_db = AsyncMock()

        # Call 1: get skill
        skill_result = MagicMock()
        skill_result.scalar_one_or_none.return_value = skill

        # Call 2: purchase check returns None
        purchase_result = MagicMock()
        purchase_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[skill_result, purchase_result])

        with pytest.raises(HTTPException) as exc_info:
            await get_skill_body(
                slug="test-skill",
                user=_make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_skill_detail_no_body(self):
        """Detail endpoint returns include_detail=True but does NOT include skill_body."""
        skill = _make_agent(item_type="skill", skill_body="secret body")
        mock_db = _mock_detail_db(skill)
        response = MagicMock()
        response.headers = {}

        result = await get_skill(
            slug="test-skill",
            response=response,
            user=_make_user(),
            db=mock_db,
        )
        # _agent_to_dict with include_detail=True does NOT add skill_body
        assert "skill_body" not in result
        # But detail fields should be present
        assert "system_prompt" in result


# ===========================================================================
# TestBaseEndpoints
# ===========================================================================


@pytest.mark.unit
class TestBaseEndpoints:
    @pytest.mark.asyncio
    async def test_list_bases(self):
        bases = [_make_base(name="Base A"), _make_base(name="Base B")]
        mock_db = _mock_paginated_db(total=2, items=bases)
        response = MagicMock()
        response.headers = {}

        result = await list_bases(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search=None,
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 2
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_base_detail(self):
        base = _make_base(git_repo_url="https://github.com/example/base")
        mock_db = _mock_detail_db(base)
        response = MagicMock()
        response.headers = {}

        result = await get_base(
            slug="react-starter",
            response=response,
            user=_make_user(),
            db=mock_db,
        )
        assert result["git_repo_url"] == "https://github.com/example/base"
        assert "long_description" in result


# ===========================================================================
# TestMcpServerEndpoints
# ===========================================================================


@pytest.mark.unit
class TestMcpServerEndpoints:
    @pytest.mark.asyncio
    async def test_list_mcp_servers(self):
        servers = [_make_agent(item_type="mcp_server", name="MCP A")]
        mock_db = _mock_paginated_db(total=1, items=servers)
        response = MagicMock()
        response.headers = {}

        result = await list_mcp_servers(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search=None,
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 1
        assert result["items"][0]["item_type"] == "mcp_server"

    @pytest.mark.asyncio
    async def test_get_mcp_server_detail_has_config(self):
        server = _make_agent(
            item_type="mcp_server",
            config={"env_vars": ["GITHUB_TOKEN"]},
        )
        mock_db = _mock_detail_db(server)
        response = MagicMock()
        response.headers = {}

        result = await get_mcp_server(
            slug="test-mcp",
            response=response,
            user=_make_user(),
            db=mock_db,
        )
        assert result["config"] == {"env_vars": ["GITHUB_TOKEN"]}
        assert "system_prompt" in result  # detail fields present


# ===========================================================================
# TestThemeEndpoints
# ===========================================================================


@pytest.mark.unit
class TestThemeEndpoints:
    @pytest.mark.asyncio
    async def test_list_themes_no_json(self):
        themes = [_make_theme(name="Theme A")]
        mock_db = _mock_paginated_db(total=1, items=themes)
        response = MagicMock()
        response.headers = {}

        result = await list_themes(
            response=response,
            page=1,
            limit=20,
            category=None,
            pricing_type=None,
            search=None,
            sort="featured",
            user=_make_user(),
            db=mock_db,
        )
        assert result["total"] == 1
        # theme_json should be excluded from list view
        assert "theme_json" not in result["items"][0]
        # color_swatches should still be present
        assert "color_swatches" in result["items"][0]

    @pytest.mark.asyncio
    async def test_get_theme_detail_has_json(self):
        theme = _make_theme()
        mock_db = _mock_detail_db(theme)
        response = MagicMock()
        response.headers = {}

        result = await get_theme(
            slug="dark-mode-pro",
            response=response,
            user=_make_user(),
            db=mock_db,
        )
        assert "theme_json" in result
        assert result["theme_json"]["colors"]["primary"] == "#6366f1"
        assert result["long_description"] == "Long theme desc"
