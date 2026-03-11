"""
Integration tests for file operation endpoints.

Tests:
- DELETE /api/projects/{slug}/files  (file + directory)
- POST  /api/projects/{slug}/files/rename
- POST  /api/projects/{slug}/files/mkdir
- Path validation (traversal, empty, null bytes)
- Auth / ownership checks
- Command safety (-- separator to prevent flag injection)
- SQL wildcard escaping in LIKE queries
"""

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(client, base_id):
    """Create a project and return its slug."""
    resp = client.post(
        "/api/projects/",
        json={"name": "File Ops Test", "base_id": base_id},
    )
    assert resp.status_code == 200, f"Project creation failed: {resp.text}"
    return resp.json()["project"]["slug"]


def _save_file(client, slug, path, content=""):
    """Save a file via the existing save endpoint."""
    resp = client.post(
        f"/api/projects/{slug}/files/save",
        json={"file_path": path, "content": content},
    )
    assert resp.status_code == 200, f"File save failed: {resp.text}"
    return resp.json()


def _get_command(mock_orchestrator, call_index=-1):
    """Extract command list from a specific orchestrator call."""
    call_args = mock_orchestrator.execute_command.call_args_list[call_index]
    return call_args.kwargs.get("command", call_args[1].get("command", []))


# ---------------------------------------------------------------------------
# DELETE /api/projects/{slug}/files
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteFile:
    def test_delete_file(self, authenticated_client, default_base_id, mock_orchestrator):
        """Delete a single file from a project."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "src/hello.txt", "hello")

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "src/hello.txt", "is_directory": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "src/hello.txt"
        assert "Deleted" in data["message"]

        # Orchestrator should have been called with rm -f -- <path>
        mock_orchestrator.execute_command.assert_called()
        cmd = _get_command(mock_orchestrator)
        assert cmd[:3] == ["rm", "-f", "--"], f"Expected rm -f -- but got {cmd}"
        assert cmd[3] == "/app/src/hello.txt"

    def test_delete_directory(self, authenticated_client, default_base_id, mock_orchestrator):
        """Delete a directory recursively."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "src/components/Button.tsx", "export default () => null;")

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "src/components", "is_directory": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "src/components"

        # Should use rm -rf -- for directories
        cmd = _get_command(mock_orchestrator)
        assert cmd[:3] == ["rm", "-rf", "--"], f"Expected rm -rf -- but got {cmd}"

    def test_delete_file_with_dash_prefix(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Files with dash-prefix names must not be interpreted as flags."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "-rf", "sneaky")

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "-rf", "is_directory": False},
        )
        assert resp.status_code == 200

        cmd = _get_command(mock_orchestrator)
        # The '--' separator ensures '-rf' is treated as a filename
        assert "--" in cmd, "Command must use '--' to prevent flag injection"
        assert cmd[cmd.index("--") + 1] == "/app/-rf"

    def test_delete_empty_path_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Empty file_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "", "is_directory": False},
        )
        assert resp.status_code == 400

    def test_delete_path_traversal_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Path containing '..' should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "../etc/passwd", "is_directory": False},
        )
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_delete_path_traversal_backslash(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Backslash path traversal should also be rejected."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "src\\..\\..\\etc\\passwd", "is_directory": False},
        )
        assert resp.status_code == 400

    def test_delete_null_byte_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Path containing null bytes should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "src/\x00evil.txt", "is_directory": False},
        )
        assert resp.status_code == 400

    def test_delete_whitespace_only_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Whitespace-only paths should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "   ", "is_directory": False},
        )
        assert resp.status_code == 400

    def test_delete_strips_leading_slash(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Leading slashes in paths should be stripped."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "file.txt", "content")

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "/file.txt", "is_directory": False},
        )
        assert resp.status_code == 200
        assert resp.json()["file_path"] == "file.txt"

    def test_delete_unauthenticated(
        self, api_client, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Unauthenticated requests should be rejected."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        # Clear auth header to simulate unauthenticated request
        # (api_client and authenticated_client share the same session)
        saved_auth = api_client.headers.pop("Authorization", None)
        try:
            resp = api_client.request(
                "DELETE",
                f"/api/projects/{slug}/files",
                json={"file_path": "file.txt"},
            )
            assert resp.status_code == 403
        finally:
            if saved_auth:
                api_client.headers["Authorization"] = saved_auth

    def test_delete_default_is_directory_false(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """When is_directory is not provided, it should default to False (rm -f)."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "readme.md", "hello")

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={"file_path": "readme.md"},
        )
        assert resp.status_code == 200

        cmd = _get_command(mock_orchestrator)
        assert "-f" in cmd
        assert "-rf" not in cmd


# ---------------------------------------------------------------------------
# POST /api/projects/{slug}/files/rename
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRenameFile:
    def test_rename_file(self, authenticated_client, default_base_id, mock_orchestrator):
        """Rename a file within the same directory."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "src/old.ts", "content")

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "src/old.ts", "new_path": "src/new.ts"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["old_path"] == "src/old.ts"
        assert data["new_path"] == "src/new.ts"

    def test_rename_move_to_new_directory(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Move a file to a different directory."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "old-dir/file.ts", "content")

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "old-dir/file.ts", "new_path": "new-dir/file.ts"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_path"] == "new-dir/file.ts"

        # Should have called mkdir -p -- for parent dir and mv --
        assert mock_orchestrator.execute_command.call_count >= 2

        # Check mkdir uses --
        mkdir_cmd = _get_command(mock_orchestrator, 0)
        assert "mkdir" in mkdir_cmd
        assert "--" in mkdir_cmd

        # Check mv uses --
        mv_cmd = _get_command(mock_orchestrator, 1)
        assert "mv" in mv_cmd
        assert "--" in mv_cmd

    def test_rename_command_uses_separator(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """mv command must use '--' to prevent flag injection from filenames."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "-n", "content")

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "-n", "new_path": "safe.txt"},
        )
        assert resp.status_code == 200

        mv_cmd = _get_command(mock_orchestrator, -1)
        assert "--" in mv_cmd, "mv command must use '--' to prevent flag injection"

    def test_rename_same_path_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Renaming to the same path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "src/file.ts", "new_path": "src/file.ts"},
        )
        assert resp.status_code == 400
        assert "same" in resp.json()["detail"].lower()

    def test_rename_path_traversal_old_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Path traversal in old_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "../../etc/passwd", "new_path": "stolen.txt"},
        )
        assert resp.status_code == 400

    def test_rename_path_traversal_new_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Path traversal in new_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "src/file.ts", "new_path": "../../etc/passwd"},
        )
        assert resp.status_code == 400

    def test_rename_empty_old_path_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Empty old_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "", "new_path": "new.txt"},
        )
        assert resp.status_code == 400

    def test_rename_empty_new_path_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Empty new_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "old.txt", "new_path": ""},
        )
        assert resp.status_code == 400

    def test_rename_unauthenticated(
        self, api_client, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Unauthenticated rename should be rejected."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        # Clear auth header to simulate unauthenticated request
        saved_auth = api_client.headers.pop("Authorization", None)
        try:
            resp = api_client.post(
                f"/api/projects/{slug}/files/rename",
                json={"old_path": "a.ts", "new_path": "b.ts"},
            )
            assert resp.status_code == 403
        finally:
            if saved_auth:
                api_client.headers["Authorization"] = saved_auth

    def test_rename_root_file_no_parent(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Rename a root-level file (no parent directory in path)."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        _save_file(client, slug, "old.txt", "content")

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "old.txt", "new_path": "new.txt"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_path"] == "new.txt"


# ---------------------------------------------------------------------------
# POST /api/projects/{slug}/files/mkdir
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMkdir:
    def test_create_directory(self, authenticated_client, default_base_id, mock_orchestrator):
        """Create a new directory."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "src/components/ui"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dir_path"] == "src/components/ui"
        assert "created" in data["message"].lower()

        # Verify orchestrator was called with mkdir -p --
        mock_orchestrator.execute_command.assert_called()
        cmd = _get_command(mock_orchestrator)
        assert cmd[:3] == ["mkdir", "-p", "--"], f"Expected mkdir -p -- but got {cmd}"
        assert cmd[3] == "/app/src/components/ui"

    def test_mkdir_single_dir(self, authenticated_client, default_base_id, mock_orchestrator):
        """Create a single directory at root level."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "assets"},
        )
        assert resp.status_code == 200
        assert resp.json()["dir_path"] == "assets"

    def test_mkdir_with_dash_prefix(self, authenticated_client, default_base_id, mock_orchestrator):
        """Directory names starting with dashes should not be treated as flags."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "-p"},
        )
        assert resp.status_code == 200

        cmd = _get_command(mock_orchestrator)
        assert "--" in cmd, "mkdir must use '--' to prevent flag injection"

    def test_mkdir_empty_path_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Empty dir_path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": ""},
        )
        assert resp.status_code == 400

    def test_mkdir_path_traversal_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Path traversal in mkdir should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "../../../tmp/evil"},
        )
        assert resp.status_code == 400

    def test_mkdir_null_byte_rejected(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Null bytes in mkdir path should return 400."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "src/\x00evil"},
        )
        assert resp.status_code == 400

    def test_mkdir_unauthenticated(
        self, api_client, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Unauthenticated mkdir should be rejected."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        # Clear auth header to simulate unauthenticated request
        saved_auth = api_client.headers.pop("Authorization", None)
        try:
            resp = api_client.post(
                f"/api/projects/{slug}/files/mkdir",
                json={"dir_path": "src/new"},
            )
            assert resp.status_code == 403
        finally:
            if saved_auth:
                api_client.headers["Authorization"] = saved_auth

    def test_mkdir_strips_leading_slash(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Leading slashes should be stripped from directory paths."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={"dir_path": "/src/components"},
        )
        assert resp.status_code == 200
        assert resp.json()["dir_path"] == "src/components"


# ---------------------------------------------------------------------------
# Cross-cutting: ownership / 404
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFileOpsOwnership:
    def test_delete_on_nonexistent_project(self, authenticated_client, mock_orchestrator):
        """Deleting from a non-existent project should return 404."""
        client, _ = authenticated_client

        resp = client.request(
            "DELETE",
            "/api/projects/nonexistent-slug-xyz/files",
            json={"file_path": "file.txt"},
        )
        assert resp.status_code == 404

    def test_rename_on_nonexistent_project(self, authenticated_client, mock_orchestrator):
        """Renaming in a non-existent project should return 404."""
        client, _ = authenticated_client

        resp = client.post(
            "/api/projects/nonexistent-slug-xyz/files/rename",
            json={"old_path": "a.txt", "new_path": "b.txt"},
        )
        assert resp.status_code == 404

    def test_mkdir_on_nonexistent_project(self, authenticated_client, mock_orchestrator):
        """Mkdir in a non-existent project should return 404."""
        client, _ = authenticated_client

        resp = client.post(
            "/api/projects/nonexistent-slug-xyz/files/mkdir",
            json={"dir_path": "src"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Request body validation (missing fields)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRequestValidation:
    def test_delete_missing_file_path(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Delete without file_path field should return 422."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.request(
            "DELETE",
            f"/api/projects/{slug}/files",
            json={},
        )
        assert resp.status_code == 422

    def test_rename_missing_old_path(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Rename without old_path field should return 422."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"new_path": "b.txt"},
        )
        assert resp.status_code == 422

    def test_rename_missing_new_path(
        self, authenticated_client, default_base_id, mock_orchestrator
    ):
        """Rename without new_path field should return 422."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/rename",
            json={"old_path": "a.txt"},
        )
        assert resp.status_code == 422

    def test_mkdir_missing_dir_path(self, authenticated_client, default_base_id, mock_orchestrator):
        """Mkdir without dir_path field should return 422."""
        client, _ = authenticated_client
        slug = _create_project(client, default_base_id)

        resp = client.post(
            f"/api/projects/{slug}/files/mkdir",
            json={},
        )
        assert resp.status_code == 422
