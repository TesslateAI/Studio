"""
Unit tests for output_formatter.

Tests success/error output formatting and utility functions.
"""

import pytest
from app.agent.tools.output_formatter import (
    success_output,
    error_output,
    format_file_size,
    pluralize
)


@pytest.mark.unit
class TestOutputFormatter:
    """Test suite for output formatting utilities."""

    def test_success_output_basic(self):
        """Test creating a basic success output."""
        result = success_output(
            message="Operation succeeded",
            key1="value1",
            key2="value2"
        )

        assert result["message"] == "Operation succeeded"
        assert result["key1"] == "value1"
        assert result["key2"] == "value2"

    def test_success_output_with_details(self):
        """Test success output with details dict."""
        result = success_output(
            message="File written",
            file_path="src/App.jsx",
            details={"size": 1024, "lines": 50}
        )

        assert result["message"] == "File written"
        assert result["file_path"] == "src/App.jsx"
        assert result["details"]["size"] == 1024
        assert result["details"]["lines"] == 50

    def test_error_output_basic(self):
        """Test creating a basic error output."""
        result = error_output(
            message="Operation failed",
            suggestion="Try again with correct parameters"
        )

        assert result["message"] == "Operation failed"
        assert result["suggestion"] == "Try again with correct parameters"

    def test_error_output_with_details(self):
        """Test error output with additional details."""
        result = error_output(
            message="File not found",
            suggestion="Check the file path",
            file_path="missing.txt",
            details={"error": "ENOENT"}
        )

        assert result["message"] == "File not found"
        assert result["suggestion"] == "Check the file path"
        assert result["file_path"] == "missing.txt"
        assert result["details"]["error"] == "ENOENT"

    def test_format_file_size_bytes(self):
        """Test formatting file size in bytes."""
        assert format_file_size(100) == "100 bytes"
        assert format_file_size(1) == "1 byte"
        assert format_file_size(0) == "0 bytes"

    def test_format_file_size_kb(self):
        """Test formatting file size in KB."""
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(2048) == "2.0 KB"
        assert format_file_size(1536) == "1.5 KB"

    def test_format_file_size_mb(self):
        """Test formatting file size in MB."""
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(1024 * 1024 * 2.5) == "2.5 MB"

    def test_format_file_size_gb(self):
        """Test formatting file size in GB."""
        assert format_file_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_file_size(1024 * 1024 * 1024 * 1.5) == "1.5 GB"

    def test_pluralize_singular(self):
        """Test pluralize with singular count."""
        assert pluralize(1, "file") == "1 file"
        assert pluralize(1, "line") == "1 line"

    def test_pluralize_plural(self):
        """Test pluralize with plural count."""
        assert pluralize(0, "file") == "0 files"
        assert pluralize(2, "file") == "2 files"
        assert pluralize(100, "line") == "100 lines"

    def test_pluralize_custom_plural_form(self):
        """Test pluralize with custom plural form."""
        assert pluralize(2, "child", "children") == "2 children"
        assert pluralize(1, "child", "children") == "1 child"

    @pytest.mark.parametrize("count,word,expected", [
        (0, "item", "0 items"),
        (1, "item", "1 item"),
        (5, "item", "5 items"),
        (100, "item", "100 items"),
    ])
    def test_pluralize_parametrized(self, count, word, expected):
        """Test pluralize with various counts."""
        assert pluralize(count, word) == expected
