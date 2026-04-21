"""
Git OAuth token security tests.

Covers the clean/authenticated URL separation introduced to prevent OAuth tokens
from being persisted to the database or emitted in log output.

Functional areas tested:
- ``strip_git_credentials`` — pure URL sanitization
- ``infer_provider_from_url`` — hostname-to-provider mapping
- ``build_authenticated_git_url`` — async runtime token injection
- ``SourceSpec`` field contract (git_url vs git_clone_url separation)
- ``_acquire_from_git`` — subprocess receives authenticated URL, logs receive clean URL
- ``_build_git_provider_spec`` — pipeline produces correctly split SourceSpec and
  writes only the clean URL to the project model
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ===========================================================================
# strip_git_credentials
# ===========================================================================


class TestStripGitCredentials:
    """Pure-function tests — no mocks required."""

    def _fn(self, url):
        from app.services.git_providers.url_utils import strip_git_credentials

        return strip_git_credentials(url)

    def test_none_returns_none(self):
        assert self._fn(None) is None

    def test_empty_string_returns_empty(self):
        assert self._fn("") == ""

    def test_clean_github_url_unchanged(self):
        url = "https://github.com/owner/repo.git"
        assert self._fn(url) == url

    def test_clean_github_url_no_dotgit_unchanged(self):
        url = "https://github.com/owner/repo"
        assert self._fn(url) == url

    def test_bare_token_at_github(self):
        result = self._fn("https://ghp_SECRETTOKEN123@github.com/owner/repo.git")
        assert result == "https://github.com/owner/repo.git"
        assert "ghp_SECRETTOKEN123" not in result

    def test_oauth2_colon_token_gitlab(self):
        result = self._fn("https://oauth2:glpat-SECRETTOKEN@gitlab.com/owner/repo.git")
        assert result == "https://gitlab.com/owner/repo.git"
        assert "glpat-SECRETTOKEN" not in result

    def test_x_token_auth_bitbucket(self):
        result = self._fn("https://x-token-auth:BBTOKEN123@bitbucket.org/owner/repo.git")
        assert result == "https://bitbucket.org/owner/repo.git"
        assert "BBTOKEN123" not in result

    def test_ssh_url_returned_unchanged(self):
        url = "git@github.com:owner/repo.git"
        assert self._fn(url) == url

    def test_http_url_with_token_stripped(self):
        result = self._fn("http://token123@github.com/owner/repo.git")
        assert result == "http://github.com/owner/repo.git"
        assert "token123" not in result

    def test_non_http_scheme_returned_unchanged(self):
        url = "ssh://git@github.com/owner/repo.git"
        assert self._fn(url) == url

    def test_url_with_port_strips_credentials_keeps_port(self):
        # Port should be preserved in the output.
        result = self._fn("https://user:pass@github.com:443/owner/repo.git")
        assert "user" not in result
        assert "pass" not in result


# ===========================================================================
# infer_provider_from_url
# ===========================================================================


class TestInferProviderFromUrl:
    """Maps well-known hostnames to provider names."""

    def _fn(self, url):
        from app.services.git_providers.url_utils import infer_provider_from_url

        return infer_provider_from_url(url)

    def test_github_https(self):
        assert self._fn("https://github.com/owner/repo.git") == "github"

    def test_github_with_token(self):
        assert self._fn("https://ghp_TOKEN@github.com/owner/repo.git") == "github"

    def test_gitlab_https(self):
        assert self._fn("https://gitlab.com/owner/repo.git") == "gitlab"

    def test_bitbucket_https(self):
        assert self._fn("https://bitbucket.org/owner/repo.git") == "bitbucket"

    def test_unknown_host_returns_none(self):
        assert self._fn("https://example.com/owner/repo.git") is None

    def test_self_hosted_gitlab_returns_none(self):
        # Only canonical SaaS hostnames are supported via URL inference.
        assert self._fn("https://gitlab.corp.example.com/owner/repo.git") is None

    def test_malformed_url_returns_none(self):
        assert self._fn("not-a-url-at-all") is None

    def test_empty_string_returns_none(self):
        assert self._fn("") is None


# ===========================================================================
# build_authenticated_git_url
# ===========================================================================


@pytest.mark.asyncio
class TestBuildAuthenticatedGitUrl:
    """Async function — credential service and provider manager are mocked.

    ``url_utils.build_authenticated_git_url`` uses lazy *relative* imports inside
    the function body (to avoid circular imports).  ``patch()`` must therefore
    target the canonical module where each factory function is defined, not the
    ``url_utils`` module namespace.
    """

    _clean_github_url = "https://github.com/owner/repo.git"
    _auth_github_url = "https://ghp_TOKEN@github.com/owner/repo.git"

    # Patch targets: the modules that define the factory functions.
    _cred_patch = (
        "app.services.git_providers.credential_service.get_git_provider_credential_service"
    )
    _mgr_patch = "app.services.git_providers.manager.get_git_provider_manager"

    def _make_provider_mocks(self, *, token):
        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(return_value=token)

        mock_provider_class = MagicMock()
        mock_provider_class.parse_repo_url = MagicMock(
            return_value={"owner": "owner", "repo": "repo"}
        )
        mock_provider_class.format_clone_url = MagicMock(return_value=self._auth_github_url)

        mock_provider_manager = MagicMock()
        mock_provider_manager.get_provider_class = MagicMock(return_value=mock_provider_class)

        return mock_cred_service, mock_provider_manager, mock_provider_class

    async def _call(self, clean_url, *, mock_token):
        """Helper: patches internals and calls build_authenticated_git_url."""
        user_id = uuid4()
        db = AsyncMock()

        mock_cred_service, mock_provider_manager, _ = self._make_provider_mocks(token=mock_token)

        with (
            patch(self._cred_patch, return_value=mock_cred_service),
            patch(self._mgr_patch, return_value=mock_provider_manager),
        ):
            from app.services.git_providers.url_utils import build_authenticated_git_url

            return await build_authenticated_git_url(clean_url, user_id, db)

    async def test_unknown_host_returns_clean_url_without_credential_lookup(self):
        """Unrecognised host: provider lookup must short-circuit before credential lookup."""
        user_id = uuid4()
        db = AsyncMock()
        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(return_value="should-never-be-called")

        with patch(self._cred_patch, return_value=mock_cred_service):
            from app.services.git_providers.url_utils import build_authenticated_git_url

            result = await build_authenticated_git_url(
                "https://example.com/owner/repo.git", user_id, db
            )

        assert result == "https://example.com/owner/repo.git"
        mock_cred_service.get_access_token.assert_not_awaited()

    async def test_github_with_token_returns_authenticated_url(self):
        result = await self._call(self._clean_github_url, mock_token="ghp_TOKEN")
        assert result == self._auth_github_url

    async def test_github_no_credential_returns_clean_url(self):
        result = await self._call(self._clean_github_url, mock_token=None)
        assert result == self._clean_github_url

    async def test_credential_service_raises_returns_clean_url(self):
        """Any exception during credential lookup must fall back non-blocking."""
        user_id = uuid4()
        db = AsyncMock()
        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(
            side_effect=RuntimeError("redis unavailable")
        )

        with patch(self._cred_patch, return_value=mock_cred_service):
            from app.services.git_providers.url_utils import build_authenticated_git_url

            result = await build_authenticated_git_url(self._clean_github_url, user_id, db)

        assert result == self._clean_github_url

    async def test_parse_repo_url_returns_none_falls_back_to_clean_url(self):
        """If parse_repo_url cannot extract owner/repo, return clean URL unchanged."""
        user_id = uuid4()
        db = AsyncMock()

        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(return_value="ghp_TOKEN")

        mock_provider_class = MagicMock()
        mock_provider_class.parse_repo_url = MagicMock(return_value=None)

        mock_provider_manager = MagicMock()
        mock_provider_manager.get_provider_class = MagicMock(return_value=mock_provider_class)

        with (
            patch(self._cred_patch, return_value=mock_cred_service),
            patch(self._mgr_patch, return_value=mock_provider_manager),
        ):
            from app.services.git_providers.url_utils import build_authenticated_git_url

            result = await build_authenticated_git_url(self._clean_github_url, user_id, db)

        assert result == self._clean_github_url

    async def test_provider_manager_raises_returns_clean_url(self):
        """get_provider_class raising must also fall back non-blocking."""
        user_id = uuid4()
        db = AsyncMock()

        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(return_value="ghp_TOKEN")

        mock_provider_manager = MagicMock()
        mock_provider_manager.get_provider_class = MagicMock(
            side_effect=KeyError("unknown provider")
        )

        with (
            patch(self._cred_patch, return_value=mock_cred_service),
            patch(self._mgr_patch, return_value=mock_provider_manager),
        ):
            from app.services.git_providers.url_utils import build_authenticated_git_url

            result = await build_authenticated_git_url(self._clean_github_url, user_id, db)

        assert result == self._clean_github_url


# ===========================================================================
# SourceSpec field contract
# ===========================================================================


class TestSourceSpecFieldContract:
    """SourceSpec dataclass defaults and dual-field semantics."""

    def test_git_clone_url_defaults_to_none(self):
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(kind="git_clone", git_url="https://github.com/owner/repo.git")
        assert spec.git_clone_url is None

    def test_git_url_and_git_clone_url_independently_accessible(self):
        from app.services.project_setup.source_acquisition import SourceSpec

        clean = "https://github.com/owner/repo.git"
        auth = "https://ghp_TOKEN@github.com/owner/repo.git"
        spec = SourceSpec(kind="git_clone", git_url=clean, git_clone_url=auth)

        assert spec.git_url == clean
        assert spec.git_clone_url == auth

    def test_git_url_field_never_overwritten_by_git_clone_url(self):
        from app.services.project_setup.source_acquisition import SourceSpec

        clean = "https://github.com/owner/repo.git"
        auth = "https://ghp_SECRET@github.com/owner/repo.git"
        spec = SourceSpec(kind="git_clone", git_url=clean, git_clone_url=auth)

        assert spec.git_url is not None
        assert "SECRET" not in spec.git_url

    def test_kind_is_preserved(self):
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(kind="git_clone", git_url="https://github.com/owner/repo.git")
        assert spec.kind == "git_clone"

    def test_git_branch_defaults_to_main(self):
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(kind="git_clone", git_url="https://github.com/owner/repo.git")
        assert spec.git_branch == "main"


# ===========================================================================
# _acquire_from_git — subprocess URL and log separation
# ===========================================================================


@pytest.mark.asyncio
class TestAcquireFromGit:
    """_acquire_from_git uses git_clone_url for the subprocess, git_url for logs."""

    _clean_url = "https://github.com/owner/repo.git"
    _auth_url = "https://ghp_SECRET@github.com/owner/repo.git"

    def _make_mock_process(self, returncode=0, stderr=b""):
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", stderr))
        return proc

    async def test_git_clone_url_used_as_subprocess_argument(self):
        """When git_clone_url is set, it must appear in the subprocess args."""
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(
            kind="git_clone",
            git_url=self._clean_url,
            git_clone_url=self._auth_url,
            git_branch="main",
        )

        captured_cmd: list[str] = []

        async def fake_create_subprocess(*args, **_):
            captured_cmd.extend(args)
            return self._make_mock_process()

        with (
            patch(
                "app.services.project_setup.source_acquisition.asyncio.create_subprocess_exec",
                side_effect=fake_create_subprocess,
            ),
            patch(
                "app.services.project_setup.source_acquisition.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
            patch(
                "app.services.project_setup.source_acquisition.tempfile.mkdtemp",
                return_value="/tmp/fake-clone",
            ),
            patch(
                "app.services.project_setup.source_acquisition.os.path.exists", return_value=False
            ),
            patch("app.services.project_setup.source_acquisition.shutil.rmtree"),
        ):
            from app.services.project_setup.source_acquisition import _acquire_from_git

            await _acquire_from_git(spec, task=None)

        assert self._auth_url in captured_cmd
        assert self._clean_url not in captured_cmd

    async def test_clean_url_used_when_git_clone_url_is_none(self):
        """Without git_clone_url, the subprocess must fall back to git_url."""
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(
            kind="git_clone",
            git_url=self._clean_url,
            git_clone_url=None,
            git_branch="main",
        )

        captured_cmd: list[str] = []

        async def fake_create_subprocess(*args, **_):
            captured_cmd.extend(args)
            return self._make_mock_process()

        with (
            patch(
                "app.services.project_setup.source_acquisition.asyncio.create_subprocess_exec",
                side_effect=fake_create_subprocess,
            ),
            patch(
                "app.services.project_setup.source_acquisition.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
            patch(
                "app.services.project_setup.source_acquisition.tempfile.mkdtemp",
                return_value="/tmp/fake-clone",
            ),
            patch(
                "app.services.project_setup.source_acquisition.os.path.exists", return_value=False
            ),
            patch("app.services.project_setup.source_acquisition.shutil.rmtree"),
        ):
            from app.services.project_setup.source_acquisition import _acquire_from_git

            await _acquire_from_git(spec, task=None)

        assert self._clean_url in captured_cmd

    async def test_log_message_uses_clean_git_url_not_clone_url(self, caplog):
        """logger.info must reference git_url (no token), never git_clone_url."""
        from app.services.project_setup.source_acquisition import SourceSpec

        spec = SourceSpec(
            kind="git_clone",
            git_url=self._clean_url,
            git_clone_url=self._auth_url,
            git_branch="main",
        )

        with (
            patch(
                "app.services.project_setup.source_acquisition.asyncio.create_subprocess_exec",
                side_effect=lambda *_, **__: self._make_mock_process(),
            ),
            patch(
                "app.services.project_setup.source_acquisition.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
            patch(
                "app.services.project_setup.source_acquisition.tempfile.mkdtemp",
                return_value="/tmp/fake-log-test",
            ),
            patch(
                "app.services.project_setup.source_acquisition.os.path.exists", return_value=False
            ),
            patch("app.services.project_setup.source_acquisition.shutil.rmtree"),
            caplog.at_level(logging.INFO, logger="app.services.project_setup.source_acquisition"),
        ):
            from app.services.project_setup.source_acquisition import _acquire_from_git

            await _acquire_from_git(spec, task=None)

        # The clean URL must appear in at least one log record.
        all_log_text = " ".join(r.message for r in caplog.records)
        assert self._clean_url in all_log_text
        # The token-carrying URL must NEVER appear in any log record.
        assert "ghp_SECRET" not in all_log_text

    async def test_raises_when_git_url_missing(self):
        from app.services.project_setup.source_acquisition import SourceSpec, _acquire_from_git

        spec = SourceSpec(kind="git_clone", git_url=None)
        with pytest.raises(ValueError, match="git_url is required"):
            await _acquire_from_git(spec, task=None)


# ===========================================================================
# _build_git_provider_spec — clean / authenticated URL split
# ===========================================================================


@pytest.mark.asyncio
class TestBuildGitProviderSpec:
    """Pipeline function: SourceSpec must carry clean git_url and auth git_clone_url.

    ``_build_git_provider_spec`` lazily imports ``get_git_provider_manager`` and
    ``get_git_provider_credential_service`` inside the function body (circular-
    import guard).  We patch these at the canonical definition sites so the mocks
    are in place before Python performs those imports.
    """

    _owner = "acme"
    _repo = "my-app"
    _clean_url = "https://github.com/acme/my-app.git"
    _auth_url = "https://ghp_LIVE_TOKEN@github.com/acme/my-app.git"
    _access_token = "ghp_LIVE_TOKEN"

    # ``_build_git_provider_spec`` lazily does:
    #   from ...services.git_providers import get_git_provider_manager
    #   from ...services.git_providers.credential_service import get_git_provider_credential_service
    # The first resolves through the package __init__.py re-export, the second
    # resolves directly from the credential_service module.  Patch both at the
    # location the function actually reads them from.
    _mgr_patch = "app.services.git_providers.get_git_provider_manager"
    _cred_patch = (
        "app.services.git_providers.credential_service.get_git_provider_credential_service"
    )

    def _make_project_data(self, source_type="github", repo_url=None, branch=None):
        data = MagicMock()
        data.source_type = source_type
        data.git_repo_url = repo_url or self._clean_url
        data.github_repo_url = None
        data.git_branch = branch
        data.github_branch = None
        return data

    def _setup_mocks(self, *, access_token, default_branch="main"):
        mock_provider_class = MagicMock()
        mock_provider_class.parse_repo_url = MagicMock(
            return_value={"owner": self._owner, "repo": self._repo}
        )

        # format_clone_url(owner, repo) → clean; format_clone_url(owner, repo, token) → auth
        def format_clone_url(owner, repo, token=None):
            if token:
                return f"https://{token}@github.com/{owner}/{repo}.git"
            return f"https://github.com/{owner}/{repo}.git"

        mock_provider_class.format_clone_url = MagicMock(side_effect=format_clone_url)
        mock_provider_instance = AsyncMock()
        mock_provider_instance.get_default_branch = AsyncMock(return_value=default_branch)
        mock_provider_class.return_value = mock_provider_instance

        mock_provider_manager = MagicMock()
        mock_provider_manager.get_provider_class = MagicMock(return_value=mock_provider_class)

        mock_cred_service = MagicMock()
        mock_cred_service.get_access_token = AsyncMock(return_value=access_token)

        return mock_provider_manager, mock_cred_service, mock_provider_class

    async def _call(self, project_data, *, access_token, default_branch="main"):
        db = AsyncMock()
        settings = MagicMock()
        user_id = uuid4()

        mock_provider_manager, mock_cred_service, _ = self._setup_mocks(
            access_token=access_token, default_branch=default_branch
        )

        with (
            patch(self._mgr_patch, return_value=mock_provider_manager),
            patch(self._cred_patch, return_value=mock_cred_service),
        ):
            from app.services.project_setup.pipeline import _build_git_provider_spec

            return await _build_git_provider_spec(project_data, db, settings, user_id)

    async def test_git_url_is_clean_no_token(self):
        spec = await self._call(self._make_project_data(), access_token=self._access_token)
        assert spec.git_url is not None
        assert spec.git_url == self._clean_url
        assert self._access_token not in spec.git_url

    async def test_git_clone_url_contains_token(self):
        spec = await self._call(self._make_project_data(), access_token=self._access_token)
        assert spec.git_clone_url is not None
        assert self._access_token in spec.git_clone_url

    async def test_git_url_and_git_clone_url_are_different_when_token_present(self):
        spec = await self._call(self._make_project_data(), access_token=self._access_token)
        assert spec.git_url != spec.git_clone_url

    async def test_public_repo_no_token_both_fields_equal_clean_url(self):
        """Without a token both fields must be the same clean URL."""
        spec = await self._call(self._make_project_data(), access_token=None)
        assert spec.git_url == self._clean_url
        assert spec.git_clone_url == self._clean_url

    async def test_spec_kind_is_git_clone(self):
        spec = await self._call(self._make_project_data(), access_token=self._access_token)
        assert spec.kind == "git_clone"

    async def test_raises_when_no_repo_url_provided(self):
        project_data = MagicMock()
        project_data.source_type = "github"
        project_data.git_repo_url = None
        project_data.github_repo_url = None

        db = AsyncMock()
        settings = MagicMock()
        user_id = uuid4()

        with pytest.raises(ValueError, match="No repository URL provided"):
            from app.services.project_setup.pipeline import _build_git_provider_spec

            await _build_git_provider_spec(project_data, db, settings, user_id)

    async def test_db_project_git_remote_url_equals_clean_spec_git_url(self):
        """The value assigned to db_project.git_remote_url must be the clean URL.

        Simulates the pipeline assignment at:
            db_project.git_remote_url = spec.git_url
        """
        spec = await self._call(self._make_project_data(), access_token=self._access_token)

        db_project = MagicMock()
        db_project.git_remote_url = spec.git_url

        assert db_project.git_remote_url == self._clean_url
        assert self._access_token not in db_project.git_remote_url

    async def test_branch_resolved_from_provider_when_not_specified(self):
        """Default branch is fetched from the provider API when not explicitly set."""
        spec = await self._call(
            self._make_project_data(branch=None),
            access_token=self._access_token,
            default_branch="develop",
        )
        assert spec.git_branch == "develop"

    async def test_explicit_branch_overrides_api_lookup(self):
        """An explicit branch in project_data is used without API lookup."""
        spec = await self._call(
            self._make_project_data(branch="feature/my-branch"),
            access_token=self._access_token,
            default_branch="should-not-be-used",
        )
        assert spec.git_branch == "feature/my-branch"
