"""
Unit tests for _validate_file_path helper in projects router.

These tests don't need a database or HTTP client — they test pure validation logic.
"""

import pytest
from fastapi import HTTPException

from app.routers.projects import _validate_file_path


@pytest.mark.unit
class TestValidateFilePath:
    def test_normal_path(self):
        assert _validate_file_path("src/index.ts") == "src/index.ts"

    def test_strips_leading_slash(self):
        assert _validate_file_path("/src/index.ts") == "src/index.ts"

    def test_strips_whitespace(self):
        assert _validate_file_path("  src/index.ts  ") == "src/index.ts"

    def test_nested_path(self):
        assert _validate_file_path("src/components/ui/Button.tsx") == "src/components/ui/Button.tsx"

    def test_single_file(self):
        assert _validate_file_path("README.md") == "README.md"

    def test_dotfile(self):
        assert _validate_file_path(".gitignore") == ".gitignore"

    def test_single_dot_allowed(self):
        assert _validate_file_path("./src/index.ts") == "./src/index.ts"

    def test_empty_string_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("")
        assert exc.value.status_code == 400

    def test_whitespace_only_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("   ")
        assert exc.value.status_code == 400

    def test_null_byte_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("src/\x00evil.ts")
        assert exc.value.status_code == 400

    def test_path_traversal_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("../etc/passwd")
        assert exc.value.status_code == 400
        assert "traversal" in exc.value.detail.lower()

    def test_path_traversal_mid_path_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("src/../../etc/passwd")
        assert exc.value.status_code == 400

    def test_path_traversal_backslash_rejected(self):
        with pytest.raises(HTTPException) as exc:
            _validate_file_path("src\\..\\..\\etc\\passwd")
        assert exc.value.status_code == 400

    def test_double_dot_in_filename_allowed(self):
        """A file named '..foo' or 'foo..bar' is not path traversal."""
        assert _validate_file_path("src/foo..bar.ts") == "src/foo..bar.ts"

    def test_path_with_sql_wildcard_percent(self):
        """Percent signs in paths are valid filenames and should pass validation."""
        assert _validate_file_path("src/100%done.txt") == "src/100%done.txt"

    def test_path_with_sql_wildcard_underscore(self):
        """Underscores in paths are valid filenames and should pass validation."""
        assert _validate_file_path("src/my_file.ts") == "src/my_file.ts"

    def test_path_with_dash_prefix(self):
        """Filenames starting with dashes are valid and should pass validation."""
        assert _validate_file_path("-rf") == "-rf"

    def test_multiple_leading_slashes_stripped(self):
        assert _validate_file_path("///src/file.ts") == "src/file.ts"
