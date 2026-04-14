"""
Unit tests for TemplateBuilderService.

Tests cover:
- build_template happy path (end-to-end orchestration)
- build_template error handling (job failure, timeout, PVC bind failure)
- rebuild_template (lookup + delegation)
- build_all_official (feature flag, query, per-base failure isolation)
- get_build_status (record retrieval)
- _wait_for_pvc_bound (polling with Bound/timeout/ApiException)
- _get_remote_head_sha (success / failure)
- _delete_namespace_best_effort (success / swallows errors)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest

from app.models import MarketplaceBase, TemplateBuild
from app.services.template_builder import (
    _PVC_BIND_POLL_INTERVAL,
    _PVC_BIND_TIMEOUT,
    _TEMPLATE_BUILD_USER_ID,
    CSI_PROVISIONER,
    TemplateBuilderService,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Return a mock Settings object with sane defaults for template builds."""
    s = Mock()
    s.template_build_namespace_prefix = "tmpl-build-"
    s.k8s_storage_class = "tesslate-block-storage"
    s.k8s_devserver_image = "tesslate-devserver:latest"
    s.template_build_timeout = 300
    s.template_build_nodeops_address = "localhost:9741"
    s.template_build_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_base(**overrides):
    """Return a mock MarketplaceBase with default fields."""
    base = Mock(spec=MarketplaceBase)
    base.id = uuid4()
    base.slug = "nextjs-app"
    base.git_repo_url = "https://github.com/tesslate/nextjs-template.git"
    base.default_branch = "main"
    base.template_slug = None
    base.is_featured = True
    base.is_active = True
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_k8s_client():
    """Return an AsyncMock k8s client with all methods the service uses."""
    k8s = AsyncMock()
    k8s.create_namespace_if_not_exists = AsyncMock()
    k8s.apply_network_policy = AsyncMock()
    k8s.create_pvc = AsyncMock()
    k8s.create_job = AsyncMock()
    k8s.get_job_status = AsyncMock(return_value="succeeded")
    k8s.storage_class_exists = AsyncMock(return_value=False)
    k8s.create_storage_class = AsyncMock()

    # For _wait_for_pvc_bound
    mock_pvc = Mock()
    mock_pvc.status.phase = "Bound"
    mock_pvc.spec.volume_name = "pv-abc123"
    k8s.core_v1 = Mock()
    k8s.core_v1.read_namespaced_persistent_volume_claim = Mock(return_value=mock_pvc)
    k8s.core_v1.delete_namespace = Mock()

    return k8s


def _make_nodeops():
    """Return an AsyncMock NodeOpsClient with async context manager support."""
    nodeops = AsyncMock()
    nodeops.promote_to_template = AsyncMock()
    nodeops.__aenter__ = AsyncMock(return_value=nodeops)
    nodeops.__aexit__ = AsyncMock(return_value=False)
    return nodeops


# All patches target the import locations inside the module under test.
_MOD = "app.services.template_builder"


# ---------------------------------------------------------------------------
# build_template — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBuildTemplateHappyPath:
    """End-to-end success flow through build_template."""

    async def test_creates_record_and_returns_ready_build(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        nodeops = _make_nodeops()

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.NodeOpsClient", return_value=nodeops),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value="abc123def456",
            ),
        ):
            # asyncio.to_thread for PVC read should return a mock PVC
            mock_pvc_obj = Mock()
            mock_pvc_obj.status.phase = "Bound"
            mock_pvc_obj.spec.volume_name = "pv-abc123"
            mock_to_thread.return_value = mock_pvc_obj

            svc = TemplateBuilderService()
            await svc.build_template(base, db)

        # Record added and committed
        db.add.assert_called_once()
        added_build = db.add.call_args[0][0]
        assert isinstance(added_build, TemplateBuild)
        assert added_build.status == "ready"
        assert added_build.build_duration_seconds is not None

        # MarketplaceBase.template_slug set
        assert base.template_slug == base.slug

        # K8s resources created
        k8s.create_namespace_if_not_exists.assert_awaited_once()
        k8s.apply_network_policy.assert_awaited_once()
        k8s.create_pvc.assert_awaited_once()
        k8s.create_job.assert_awaited_once()

        # NodeOps promote called
        nodeops.promote_to_template.assert_awaited_once_with("pv-abc123", base.slug)

        # StorageClass created (storage_class_exists returned False)
        k8s.create_storage_class.assert_awaited_once()
        sc_call = k8s.create_storage_class.call_args
        assert sc_call.kwargs["name"] == f"tesslate-btrfs-{base.slug}"
        assert sc_call.kwargs["provisioner"] == CSI_PROVISIONER
        assert sc_call.kwargs["parameters"] == {"template": base.slug}

    async def test_skips_storage_class_when_already_exists(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        k8s.storage_class_exists = AsyncMock(return_value=True)
        nodeops = _make_nodeops()

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.NodeOpsClient", return_value=nodeops),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_pvc_obj = Mock()
            mock_pvc_obj.status.phase = "Bound"
            mock_pvc_obj.spec.volume_name = "pv-exists"
            mock_to_thread.return_value = mock_pvc_obj

            svc = TemplateBuilderService()
            await svc.build_template(base, db)

        k8s.create_storage_class.assert_not_awaited()

    async def test_namespace_cleaned_up_on_success(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        nodeops = _make_nodeops()

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.NodeOpsClient", return_value=nodeops),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_pvc_obj = Mock()
            mock_pvc_obj.status.phase = "Bound"
            mock_pvc_obj.spec.volume_name = "pv-x"
            mock_to_thread.return_value = mock_pvc_obj

            svc = TemplateBuilderService()
            await svc.build_template(base, db)

        # _delete_namespace_best_effort uses asyncio.to_thread to call
        # k8s.core_v1.delete_namespace.  The last to_thread call should be
        # the namespace cleanup (two calls total: PVC read + namespace delete).
        assert mock_to_thread.await_count >= 2

    async def test_uses_default_branch_when_base_has_none(self):
        """When base.default_branch is None, falls back to 'main'."""
        settings = _make_settings()
        base = _make_base(default_branch=None)
        db = AsyncMock()
        k8s = _make_k8s_client()
        nodeops = _make_nodeops()

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job") as mock_job,
            patch(f"{_MOD}.NodeOpsClient", return_value=nodeops),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_pvc_obj = Mock()
            mock_pvc_obj.status.phase = "Bound"
            mock_pvc_obj.spec.volume_name = "pv-y"
            mock_to_thread.return_value = mock_pvc_obj

            svc = TemplateBuilderService()
            await svc.build_template(base, db)

        # create_template_builder_job should have been called with git_branch="main"
        _, kwargs = mock_job.call_args
        assert (
            kwargs.get(
                "git_branch", mock_job.call_args[0][3] if len(mock_job.call_args[0]) > 3 else None
            )
            == "main"
            or mock_job.call_args[1].get("git_branch") == "main"
        )


# ---------------------------------------------------------------------------
# build_template — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBuildTemplateErrors:
    """Failure modes in build_template."""

    async def test_job_failure_sets_status_failed_and_increments_retry(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        k8s.get_job_status = AsyncMock(return_value="failed")

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock),
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            svc = TemplateBuilderService()
            with pytest.raises(RuntimeError, match="Builder job failed"):
                await svc.build_template(base, db)

        added_build = db.add.call_args[0][0]
        assert added_build.status == "failed"
        assert "Builder job failed" in added_build.error_message
        assert added_build.retry_count == 1
        assert added_build.completed_at is not None

    async def test_job_timeout_sets_status_failed(self):
        settings = _make_settings(template_build_timeout=0)  # Immediate timeout
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        # Job never succeeds — stays "running" (not "succeeded" or "failed")
        k8s.get_job_status = AsyncMock(return_value="running")

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock),
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            svc = TemplateBuilderService()
            with pytest.raises(RuntimeError, match="timed out"):
                await svc.build_template(base, db)

        added_build = db.add.call_args[0][0]
        assert added_build.status == "failed"
        assert added_build.retry_count == 1

    async def test_pvc_never_bound_sets_status_failed(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        nodeops = _make_nodeops()

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.NodeOpsClient", return_value=nodeops),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            # PVC never transitions to Bound
            mock_pvc_obj = Mock()
            mock_pvc_obj.status.phase = "Pending"
            mock_to_thread.return_value = mock_pvc_obj

            svc = TemplateBuilderService()
            with pytest.raises(RuntimeError, match="never became Bound"):
                await svc.build_template(base, db)

        added_build = db.add.call_args[0][0]
        assert added_build.status == "failed"
        assert added_build.retry_count == 1

    async def test_namespace_cleaned_up_on_failure(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        k8s.get_job_status = AsyncMock(return_value="failed")

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            svc = TemplateBuilderService()
            with pytest.raises(RuntimeError):
                await svc.build_template(base, db)

        # asyncio.to_thread should still be called for namespace cleanup
        # even though the job failed (the finally block runs).
        mock_to_thread.assert_awaited()

    async def test_error_message_truncated_to_1000_chars(self):
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()

        long_error = "x" * 2000

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock),
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                side_effect=RuntimeError(long_error),
            ),
        ):
            svc = TemplateBuilderService()
            with pytest.raises(RuntimeError):
                await svc.build_template(base, db)

        added_build = db.add.call_args[0][0]
        assert len(added_build.error_message) <= 1000

    async def test_retry_count_increments_from_existing_value(self):
        """When retry_count already has a value, it increments rather than resetting."""
        settings = _make_settings()
        base = _make_base()
        db = AsyncMock()
        k8s = _make_k8s_client()
        k8s.get_job_status = AsyncMock(return_value="failed")

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch(f"{_MOD}.get_k8s_client", return_value=k8s),
            patch(f"{_MOD}.create_builder_network_policy"),
            patch(f"{_MOD}.create_template_builder_job"),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock),
            patch.object(
                TemplateBuilderService,
                "_get_remote_head_sha",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            svc = TemplateBuilderService()

            # Simulate the build object already having retry_count=2
            # We need to intercept db.add to set retry_count before failure
            original_add = db.add

            def add_with_retry(obj):
                if isinstance(obj, TemplateBuild):
                    obj.retry_count = 2
                return original_add(obj)

            db.add = add_with_retry

            with pytest.raises(RuntimeError):
                await svc.build_template(base, db)

        # The TemplateBuild that was created should now have retry_count=3
        added_build = original_add.call_args[0][0]
        assert added_build.retry_count == 3


# ---------------------------------------------------------------------------
# rebuild_template
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRebuildTemplate:
    async def test_rebuilds_existing_base(self):
        base = _make_base(slug="vite-react")
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=base)

        with (
            patch(f"{_MOD}.get_settings", return_value=_make_settings()),
            patch.object(
                TemplateBuilderService,
                "build_template",
                new_callable=AsyncMock,
                return_value=Mock(spec=TemplateBuild),
            ) as mock_build,
        ):
            svc = TemplateBuilderService()
            result = await svc.rebuild_template("vite-react", db)

        mock_build.assert_awaited_once_with(base, db)
        assert result is not None

    async def test_raises_value_error_when_base_not_found(self):
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=None)

        with patch(f"{_MOD}.get_settings", return_value=_make_settings()):
            svc = TemplateBuilderService()
            with pytest.raises(ValueError, match="Base not found"):
                await svc.rebuild_template("nonexistent-slug", db)


# ---------------------------------------------------------------------------
# build_all_official
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBuildAllOfficial:
    async def test_returns_empty_when_disabled(self):
        settings = _make_settings(template_build_enabled=False)
        db = AsyncMock()

        with patch(f"{_MOD}.get_settings", return_value=settings):
            svc = TemplateBuilderService()
            result = await svc.build_all_official(db)

        assert result == []
        db.execute.assert_not_awaited()

    async def test_builds_featured_bases_without_template_slug(self):
        base1 = _make_base(slug="next")
        base2 = _make_base(slug="vite")
        build1 = Mock(spec=TemplateBuild)
        build2 = Mock(spec=TemplateBuild)

        settings = _make_settings()
        db = AsyncMock()

        # Simulate db.execute().scalars().all() returning bases
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [base1, base2]
        db.execute = AsyncMock(return_value=mock_result)

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch.object(
                TemplateBuilderService,
                "build_template",
                new_callable=AsyncMock,
                side_effect=[build1, build2],
            ) as mock_build,
        ):
            svc = TemplateBuilderService()
            result = await svc.build_all_official(db)

        assert len(result) == 2
        assert result[0] is build1
        assert result[1] is build2
        assert mock_build.await_count == 2

    async def test_continues_on_individual_failure(self):
        base1 = _make_base(slug="fails")
        base2 = _make_base(slug="succeeds")
        build2 = Mock(spec=TemplateBuild)

        settings = _make_settings()
        db = AsyncMock()
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [base1, base2]
        db.execute = AsyncMock(return_value=mock_result)

        with (
            patch(f"{_MOD}.get_settings", return_value=settings),
            patch.object(
                TemplateBuilderService,
                "build_template",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("boom"), build2],
            ) as mock_build,
        ):
            svc = TemplateBuilderService()
            result = await svc.build_all_official(db)

        # Only the successful build is included
        assert len(result) == 1
        assert result[0] is build2
        # Both bases were attempted
        assert mock_build.await_count == 2

    async def test_returns_empty_when_no_bases_match(self):
        settings = _make_settings()
        db = AsyncMock()
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        with patch(f"{_MOD}.get_settings", return_value=settings):
            svc = TemplateBuilderService()
            result = await svc.build_all_official(db)

        assert result == []


# ---------------------------------------------------------------------------
# get_build_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetBuildStatus:
    async def test_returns_build_when_found(self):
        build = Mock(spec=TemplateBuild)
        build_id = uuid4()
        db = AsyncMock()
        db.get = AsyncMock(return_value=build)

        with patch(f"{_MOD}.get_settings", return_value=_make_settings()):
            svc = TemplateBuilderService()
            result = await svc.get_build_status(build_id, db)

        assert result is build
        db.get.assert_awaited_once_with(TemplateBuild, build_id)

    async def test_returns_none_when_not_found(self):
        build_id = uuid4()
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with patch(f"{_MOD}.get_settings", return_value=_make_settings()):
            svc = TemplateBuilderService()
            result = await svc.get_build_status(build_id, db)

        assert result is None


# ---------------------------------------------------------------------------
# _wait_for_pvc_bound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWaitForPvcBound:
    async def test_returns_pv_name_when_bound(self):
        k8s = _make_k8s_client()
        mock_pvc = Mock()
        mock_pvc.status.phase = "Bound"
        mock_pvc.spec.volume_name = "pv-test-123"

        with (
            patch(f"{_MOD}.get_settings", return_value=_make_settings()),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_pvc),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
        ):
            svc = TemplateBuilderService()
            result = await svc._wait_for_pvc_bound(k8s, "my-pvc", "my-ns")

        assert result == "pv-test-123"

    async def test_returns_none_on_timeout(self):
        k8s = _make_k8s_client()
        mock_pvc = Mock()
        mock_pvc.status.phase = "Pending"

        with (
            patch(f"{_MOD}.get_settings", return_value=_make_settings()),
            patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_pvc),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
        ):
            svc = TemplateBuilderService()
            result = await svc._wait_for_pvc_bound(k8s, "stuck-pvc", "my-ns")

        assert result is None

    async def test_retries_on_api_exception(self):
        """ApiException on PVC read is caught and retried."""
        from kubernetes.client.rest import ApiException

        k8s = _make_k8s_client()

        # First call raises ApiException, second call returns Bound PVC
        mock_pvc = Mock()
        mock_pvc.status.phase = "Bound"
        mock_pvc.spec.volume_name = "pv-retry-ok"

        call_count = [0]

        async def mock_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ApiException(status=404, reason="Not Found")
            return mock_pvc

        with (
            patch(f"{_MOD}.get_settings", return_value=_make_settings()),
            patch(f"{_MOD}.asyncio.to_thread", side_effect=mock_to_thread),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
        ):
            svc = TemplateBuilderService()
            result = await svc._wait_for_pvc_bound(k8s, "pvc", "ns")

        assert result == "pv-retry-ok"
        assert call_count[0] == 2

    async def test_polls_until_bound(self):
        """PVC transitions from Pending to Bound after several polls."""
        k8s = _make_k8s_client()

        call_count = [0]

        async def mock_to_thread(fn, *args, **kwargs):
            call_count[0] += 1
            pvc = Mock()
            if call_count[0] < 3:
                pvc.status.phase = "Pending"
            else:
                pvc.status.phase = "Bound"
                pvc.spec.volume_name = "pv-delayed"
            return pvc

        with (
            patch(f"{_MOD}.get_settings", return_value=_make_settings()),
            patch(f"{_MOD}.asyncio.to_thread", side_effect=mock_to_thread),
            patch(f"{_MOD}.asyncio.sleep", new_callable=AsyncMock),
        ):
            svc = TemplateBuilderService()
            result = await svc._wait_for_pvc_bound(k8s, "pvc", "ns")

        assert result == "pv-delayed"
        assert call_count[0] == 3


# ---------------------------------------------------------------------------
# _get_remote_head_sha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetRemoteHeadSha:
    async def test_returns_sha_on_success(self):
        sha = "a" * 40 + "  refs/heads/main\n"
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(sha.encode(), b""))
        mock_proc.returncode = 0

        with patch(f"{_MOD}.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://github.com/test/repo.git", "main"
            )

        assert result == "a" * 40

    async def test_returns_none_on_nonzero_exit(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 128

        with patch(f"{_MOD}.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://bad-url.git", "main"
            )

        assert result is None

    async def test_returns_none_on_empty_stdout(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(f"{_MOD}.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://github.com/test/repo.git", "nonexistent"
            )

        assert result is None

    async def test_returns_none_on_exception(self):
        with patch(
            f"{_MOD}.asyncio.create_subprocess_exec",
            side_effect=OSError("git not found"),
        ):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://github.com/test/repo.git", "main"
            )

        assert result is None

    async def test_returns_none_on_timeout(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

        with patch(f"{_MOD}.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://github.com/test/repo.git", "main"
            )

        assert result is None

    async def test_truncates_sha_to_40_chars(self):
        sha_long = "b" * 50 + "\trefs/heads/main\n"
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(sha_long.encode(), b""))
        mock_proc.returncode = 0

        with patch(f"{_MOD}.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await TemplateBuilderService._get_remote_head_sha(
                "https://github.com/test/repo.git", "main"
            )

        assert result is not None
        assert len(result) == 40


# ---------------------------------------------------------------------------
# _delete_namespace_best_effort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteNamespaceBestEffort:
    async def test_deletes_namespace(self):
        k8s = _make_k8s_client()

        with patch(f"{_MOD}.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            await TemplateBuilderService._delete_namespace_best_effort(k8s, "tmpl-build-abc")

        mock_to_thread.assert_awaited_once()
        # The function passed to to_thread should be k8s.core_v1.delete_namespace
        call_args = mock_to_thread.call_args
        assert call_args[0][0] == k8s.core_v1.delete_namespace

    async def test_swallows_errors(self):
        k8s = _make_k8s_client()

        with patch(
            f"{_MOD}.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=Exception("namespace already deleted"),
        ):
            # Should not raise
            await TemplateBuilderService._delete_namespace_best_effort(k8s, "tmpl-build-gone")


# ---------------------------------------------------------------------------
# Constants and sentinel values
# ---------------------------------------------------------------------------


class TestConstants:
    def test_template_build_user_id_is_nil_uuid(self):
        assert UUID("00000000-0000-0000-0000-000000000000") == _TEMPLATE_BUILD_USER_ID

    def test_csi_provisioner_value(self):
        assert CSI_PROVISIONER == "btrfs.csi.tesslate.io"

    def test_pvc_bind_timeout_is_reasonable(self):
        assert _PVC_BIND_TIMEOUT > 0
        assert _PVC_BIND_POLL_INTERVAL > 0
        assert _PVC_BIND_TIMEOUT > _PVC_BIND_POLL_INTERVAL
