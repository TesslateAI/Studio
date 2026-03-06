"""
Test fixtures module.

This module provides golden test data for oracle tests and reusable mock objects.

Files:
- golden_parser_inputs.json: Parser oracle test cases
- golden_patches.json: Code patching oracle test cases
- golden_tool_outputs.json: Tool execution oracle test cases
"""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def load_golden_data(filename: str) -> dict:
    """Load golden test data from JSON file."""
    filepath = FIXTURES_DIR / filename
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def get_parser_test_cases():
    """Get parser oracle test cases."""
    return load_golden_data("golden_parser_inputs.json")


def get_patch_test_cases():
    """Get code patching oracle test cases."""
    return load_golden_data("golden_patches.json")


def get_tool_output_test_cases():
    """Get tool execution oracle test cases."""
    return load_golden_data("golden_tool_outputs.json")
