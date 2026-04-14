"""
File Operations Module

Essential file operation tools for AI agents.

The tools registered here:
    * ``read_file`` / ``write_file``        (read_write.py)
    * ``patch_file`` / ``multi_edit``       (edit.py — multi-strategy matcher)
    * ``apply_patch``                       (apply_patch_tool.py — structured batch)
    * ``file_undo``                         (undo_tool.py)
    * ``view_image``                        (view_image.py)

``EDIT_HISTORY`` from :mod:`edit_history` is the shared ring buffer
every mutating tool records into so ``file_undo`` can walk it back.
"""

from .apply_patch_tool import register_apply_patch_tool
from .edit import register_edit_tools
from .edit_history import EDIT_HISTORY, EditHistory, EditHistoryEntry
from .read_many import register_read_many_files_tool
from .read_write import register_read_write_tools
from .undo_tool import register_undo_tool
from .view_image import register_view_image_tool


def register_all_file_tools(registry):
    """Register essential file operation tools."""
    register_read_write_tools(registry)  # read_file, write_file
    register_read_many_files_tool(registry)  # read_many_files
    register_edit_tools(registry)  # patch_file, multi_edit
    register_apply_patch_tool(registry)  # apply_patch (structured)
    register_file_ops_upgrades(registry)  # file_undo, view_image


def register_file_ops_upgrades(registry):
    """
    Register the ``file_undo`` and ``view_image`` tools.

    Exposed as a standalone entry point so a central registrar can wire
    these in without going through ``register_all_file_tools``.
    """
    register_undo_tool(registry)
    register_view_image_tool(registry)


__all__ = [
    "register_all_file_tools",
    "register_read_write_tools",
    "register_read_many_files_tool",
    "register_edit_tools",
    "register_apply_patch_tool",
    "register_file_ops_upgrades",
    "register_undo_tool",
    "register_view_image_tool",
    "EDIT_HISTORY",
    "EditHistory",
    "EditHistoryEntry",
]
