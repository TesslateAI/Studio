"""
Unit tests for file placement — tar-based volume upload.

Tests cover:
- _build_source_tar: tar creation from source directory with SKIP_DIRS filtering
- _build_source_tar: config injection into tar archive
- _place_kubernetes: wires tar_extract instead of per-file writes
"""

import importlib
import io
import sys
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import file_placement module directly (avoids heavy app dependency chain)
_mod_path = (
    Path(__file__).resolve().parents[2] / "app" / "services" / "project_setup" / "file_placement.py"
)
_spec = importlib.util.spec_from_file_location(
    "app.services.project_setup.file_placement", _mod_path
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.services.project_setup.file_placement"] = _mod

# Stub out the config parser imports before exec_module
_config_mod = MagicMock()
_config_mod.TesslateProjectConfig = type("TesslateProjectConfig", (), {})
_config_mod.serialize_config_to_json = MagicMock(return_value='{"containers":[]}')
_config_mod.write_tesslate_config = MagicMock()
sys.modules["app.services.base_config_parser"] = _config_mod

_spec.loader.exec_module(_mod)

# Clean up the stub modules so they don't pollute other tests in the session.
# The file_placement module has already resolved its imports above.
sys.modules.pop("app.services.base_config_parser", None)
sys.modules.pop("app.services.project_setup.file_placement", None)

_build_source_tar = _mod._build_source_tar
SKIP_DIRS = _mod.SKIP_DIRS
PlacedFiles = _mod.PlacedFiles


# ---------------------------------------------------------------------------
# _build_source_tar
# ---------------------------------------------------------------------------


class TestBuildSourceTar:
    """Verify tar archive creation from a source directory."""

    def test_creates_tar_with_files(self, tmp_path):
        """Source files end up in the tar with correct relative paths."""
        (tmp_path / "index.ts").write_text("console.log('hi');")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.tsx").write_text("<App />")

        tar_bytes, count = _build_source_tar(str(tmp_path))

        assert count == 2
        assert len(tar_bytes) > 0

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            names = sorted(tar.getnames())
            assert "index.ts" in names
            assert "src/app.tsx" in names

    def test_excludes_skip_dirs(self, tmp_path):
        """Directories in SKIP_DIRS are not included in the tar."""
        (tmp_path / "keep.txt").write_text("keep")
        for skip in ["node_modules", ".git", "__pycache__", ".next"]:
            d = tmp_path / skip
            d.mkdir()
            (d / "should_skip.txt").write_text("skip")

        tar_bytes, count = _build_source_tar(str(tmp_path))

        assert count == 1  # only keep.txt
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            names = tar.getnames()
            assert "keep.txt" in names
            for skip in ["node_modules", ".git", "__pycache__", ".next"]:
                assert not any(skip in n for n in names), f"{skip} should be excluded"

    def test_injects_config_when_provided(self, tmp_path):
        """When config is provided, .tesslate/config.json is added to the tar."""
        (tmp_path / "app.js").write_text("// app")

        config = _config_mod.TesslateProjectConfig()
        _config_mod.serialize_config_to_json.return_value = '{"containers":[]}'

        tar_bytes, count = _build_source_tar(str(tmp_path), config=config)

        assert count == 2  # app.js + config.json
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            names = tar.getnames()
            assert ".tesslate/config.json" in names
            member = tar.getmember(".tesslate/config.json")
            content = tar.extractfile(member).read().decode()
            assert content == '{"containers":[]}'

    def test_no_config_when_none(self, tmp_path):
        """When config is None, .tesslate/config.json is NOT added."""
        (tmp_path / "app.js").write_text("// app")

        tar_bytes, count = _build_source_tar(str(tmp_path), config=None)

        assert count == 1
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            names = tar.getnames()
            assert ".tesslate/config.json" not in names

    def test_empty_directory_produces_empty_tar(self, tmp_path):
        """An empty source directory produces a valid tar with zero files."""
        tar_bytes, count = _build_source_tar(str(tmp_path))

        assert count == 0
        assert len(tar_bytes) > 0  # tar header is still present
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            assert tar.getnames() == []

    def test_binary_files_preserved(self, tmp_path):
        """Binary file content survives tar round-trip."""
        binary_data = bytes(range(256))
        (tmp_path / "binary.bin").write_bytes(binary_data)

        tar_bytes, count = _build_source_tar(str(tmp_path))

        assert count == 1
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            extracted = tar.extractfile("binary.bin").read()
            assert extracted == binary_data

    def test_nested_directories(self, tmp_path):
        """Deeply nested files get correct relative paths."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("deep")

        tar_bytes, count = _build_source_tar(str(tmp_path))

        assert count == 1
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            assert "a/b/c/deep.txt" in tar.getnames()


# ---------------------------------------------------------------------------
# _place_kubernetes (integration-style with mocked gRPC)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPlaceKubernetes:
    """Verify _place_kubernetes uses tar_extract instead of per-file writes."""

    async def test_calls_tar_extract_once(self, tmp_path):
        """File placement sends a single tar_extract call, not N write_file calls."""
        (tmp_path / "index.ts").write_text("console.log('hi');")
        (tmp_path / "package.json").write_text('{"name":"test"}')

        mock_client = AsyncMock()
        mock_vm = MagicMock()
        mock_vm.create_empty_volume = AsyncMock(return_value=("vol-test", "node-1"))
        mock_discovery = MagicMock()
        mock_discovery.get_fileops_address = AsyncMock(return_value="node-1:9742")

        mock_client_cls = MagicMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        config = _config_mod.TesslateProjectConfig()

        with (
            patch.dict(
                sys.modules,
                {
                    "app.services.volume_manager": MagicMock(
                        get_volume_manager=MagicMock(return_value=mock_vm)
                    ),
                    "app.services.node_discovery": MagicMock(
                        NodeDiscovery=MagicMock(return_value=mock_discovery)
                    ),
                    "app.services.fileops_client": MagicMock(FileOpsClient=mock_client_cls),
                },
            ),
        ):
            # Re-exec the function so it picks up our mocked modules
            result = await _mod._place_kubernetes(str(tmp_path), config, "test-slug")

        # Should call tar_extract exactly once
        mock_client.tar_extract.assert_awaited_once()
        call_args = mock_client.tar_extract.call_args
        assert call_args[0][0] == "vol-test"  # volume_id
        assert call_args[0][1] == "."  # extract to root

        # Tar data should be valid and contain our files + config
        tar_data = call_args[0][2]
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r") as tar:
            names = tar.getnames()
            assert "index.ts" in names
            assert "package.json" in names
            assert ".tesslate/config.json" in names

        # Should NOT call write_file at all
        mock_client.write_file.assert_not_awaited()

        # Result should have volume info
        assert result.volume_id == "vol-test"
        assert result.node_name == "node-1"

    async def test_skip_config_when_write_config_false(self, tmp_path):
        """When write_config=False, .tesslate/config.json is not in the tar."""
        (tmp_path / "app.js").write_text("// app")

        mock_client = AsyncMock()
        mock_vm = MagicMock()
        mock_vm.create_empty_volume = AsyncMock(return_value=("vol-test", "node-1"))
        mock_discovery = MagicMock()
        mock_discovery.get_fileops_address = AsyncMock(return_value="node-1:9742")

        mock_client_cls = MagicMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        config = _config_mod.TesslateProjectConfig()

        with (
            patch.dict(
                sys.modules,
                {
                    "app.services.volume_manager": MagicMock(
                        get_volume_manager=MagicMock(return_value=mock_vm)
                    ),
                    "app.services.node_discovery": MagicMock(
                        NodeDiscovery=MagicMock(return_value=mock_discovery)
                    ),
                    "app.services.fileops_client": MagicMock(FileOpsClient=mock_client_cls),
                },
            ),
        ):
            await _mod._place_kubernetes(str(tmp_path), config, "test-slug", write_config=False)

        tar_data = mock_client.tar_extract.call_args[0][2]
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r") as tar:
            names = tar.getnames()
            assert "app.js" in names
            assert ".tesslate/config.json" not in names
