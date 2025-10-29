"""
Code patching utilities for AI-driven file editing.

Implements modern diff-based editing approaches:
- Search/replace blocks (Aider-style)
- Unified diff format
- Fuzzy matching with progressive fallback strategies

This allows AI agents to make surgical edits without rewriting entire files.
"""

import re
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


@dataclass
class SearchReplaceEdit:
    """Represents a single search/replace edit operation."""
    file_path: str
    search_content: str
    replace_content: str
    line_number: Optional[int] = None  # For error reporting


@dataclass
class EditResult:
    """Result of applying an edit operation."""
    success: bool
    content: Optional[str] = None  # The edited content if successful
    error: Optional[str] = None
    match_method: Optional[str] = None  # How the match was found (exact, trimmed, fuzzy, etc.)


def extract_search_replace_blocks(content: str) -> List[SearchReplaceEdit]:
    """
    Extract search/replace edit blocks from AI response.

    Expected format:
    ```
    path/to/file.js
    <<<<<<< SEARCH
    old code to find
    =======
    new code to replace with
    >>>>>>> REPLACE
    ```

    Returns:
        List of SearchReplaceEdit objects
    """
    edits = []

    # Pattern to match file path followed by search/replace blocks
    # Supports multiple formats:
    # 1. File path on its own line before the block
    # 2. File path in a comment inside code fence
    pattern = r'(?:```[^\n]*\n)?(?://|#)?\s*(?:File:\s*)?([^\n]+\.[\w]+)\s*\n?(```[^\n]*\n)?<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE(?:\n```)?'

    matches = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)

    for match in matches:
        file_path = match.group(1).strip()
        search_content = match.group(3).strip()
        replace_content = match.group(4).strip()

        # Clean up file path
        file_path = re.sub(r'^(?://|#|<!--)\s*(?:File:\s*)?', '', file_path)
        file_path = re.sub(r'\s*(?:-->)?\s*$', '', file_path).strip()

        if file_path and search_content is not None:  # replace_content can be empty (deletion)
            edits.append(SearchReplaceEdit(
                file_path=file_path,
                search_content=search_content,
                replace_content=replace_content
            ))
            logger.info(f"Extracted search/replace edit for {file_path}")

    return edits


def apply_search_replace(
    original_content: str,
    search: str,
    replace: str,
    fuzzy: bool = True
) -> EditResult:
    """
    Apply a search/replace edit to content with progressive fuzzy matching.

    Matching strategies (in order):
    1. Exact match
    2. Trimmed line endings
    3. All whitespace normalized
    4. Fuzzy matching (if enabled)

    Args:
        original_content: The original file content
        search: The text to search for
        replace: The text to replace it with
        fuzzy: Enable fuzzy matching fallback

    Returns:
        EditResult with success status and modified content or error
    """

    # Strategy 1: Exact match
    if search in original_content:
        new_content = original_content.replace(search, replace, 1)
        return EditResult(
            success=True,
            content=new_content,
            match_method="exact"
        )

    # Strategy 2: Trimmed line endings
    search_lines = search.split('\n')
    original_lines = original_content.split('\n')

    # Try matching with trimmed line endings
    trimmed_search = '\n'.join(line.rstrip() for line in search_lines)
    trimmed_original = '\n'.join(line.rstrip() for line in original_lines)

    if trimmed_search in trimmed_original:
        # Find the match position in trimmed version
        start_idx = trimmed_original.index(trimmed_search)

        # Reconstruct with original line endings preserved
        # Count lines before match
        lines_before = trimmed_original[:start_idx].count('\n')

        # Apply replacement preserving structure
        result_lines = original_lines[:lines_before]
        replace_lines = replace.split('\n')
        result_lines.extend(replace_lines)

        # Add lines after the match
        search_line_count = len(search_lines)
        result_lines.extend(original_lines[lines_before + search_line_count:])

        new_content = '\n'.join(result_lines)
        return EditResult(
            success=True,
            content=new_content,
            match_method="trimmed"
        )

    # Strategy 3: Whitespace-normalized matching
    def normalize_whitespace(text: str) -> str:
        """Normalize all whitespace for comparison."""
        return re.sub(r'\s+', ' ', text.strip())

    normalized_search = normalize_whitespace(search)

    # Find best match using normalized whitespace
    best_match_idx = -1
    best_match_len = 0

    for i in range(len(original_lines)):
        for j in range(i + 1, min(i + len(search_lines) + 10, len(original_lines) + 1)):
            candidate = '\n'.join(original_lines[i:j])
            normalized_candidate = normalize_whitespace(candidate)

            if normalized_candidate == normalized_search:
                # Found a match
                result_lines = original_lines[:i]
                result_lines.extend(replace.split('\n'))
                result_lines.extend(original_lines[j:])

                new_content = '\n'.join(result_lines)
                return EditResult(
                    success=True,
                    content=new_content,
                    match_method="whitespace_normalized"
                )

    # Strategy 4: Fuzzy matching (if enabled)
    if fuzzy:
        fuzzy_result = _fuzzy_search_replace(original_content, search, replace)
        if fuzzy_result.success:
            return fuzzy_result

    # All strategies failed
    return EditResult(
        success=False,
        error=f"Could not find search block in file. Tried exact, trimmed, normalized, and fuzzy matching.\n\nSearched for:\n{search[:200]}..."
    )


def _fuzzy_search_replace(
    original_content: str,
    search: str,
    replace: str,
    threshold: float = 0.8
) -> EditResult:
    """
    Fuzzy matching using SequenceMatcher.

    Finds the best matching block in the original content and replaces it.
    """
    search_lines = search.split('\n')
    original_lines = original_content.split('\n')

    best_ratio = 0.0
    best_start = -1
    best_end = -1

    # Try different window sizes around the search length
    for window_size in [len(search_lines), len(search_lines) + 2, len(search_lines) - 1]:
        if window_size <= 0:
            continue

        for i in range(len(original_lines) - window_size + 1):
            candidate_lines = original_lines[i:i + window_size]
            candidate = '\n'.join(candidate_lines)

            # Calculate similarity
            ratio = SequenceMatcher(None, search, candidate).ratio()

            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i
                best_end = i + window_size

    if best_ratio >= threshold:
        # Apply the replacement
        result_lines = original_lines[:best_start]
        result_lines.extend(replace.split('\n'))
        result_lines.extend(original_lines[best_end:])

        new_content = '\n'.join(result_lines)

        logger.info(f"Fuzzy match found with {best_ratio:.2%} similarity")

        return EditResult(
            success=True,
            content=new_content,
            match_method=f"fuzzy ({best_ratio:.2%})"
        )

    return EditResult(
        success=False,
        error=f"Fuzzy matching failed. Best similarity was {best_ratio:.2%} (threshold: {threshold:.0%})"
    )


def apply_multiple_edits(
    original_content: str,
    edits: List[Tuple[str, str]],  # List of (search, replace) tuples
    fuzzy: bool = True
) -> EditResult:
    """
    Apply multiple search/replace edits sequentially.

    Each edit is applied to the result of the previous edit.
    If any edit fails, returns error with the edit that failed.

    Args:
        original_content: The original file content
        edits: List of (search, replace) tuples
        fuzzy: Enable fuzzy matching

    Returns:
        EditResult with final content or error from first failed edit
    """
    current_content = original_content

    for i, (search, replace) in enumerate(edits):
        result = apply_search_replace(current_content, search, replace, fuzzy)

        if not result.success:
            return EditResult(
                success=False,
                error=f"Edit {i+1}/{len(edits)} failed: {result.error}"
            )

        current_content = result.content
        logger.info(f"Applied edit {i+1}/{len(edits)} using {result.match_method} matching")

    return EditResult(
        success=True,
        content=current_content,
        match_method=f"multiple ({len(edits)} edits)"
    )


def is_search_replace_format(content: str) -> bool:
    """
    Check if content contains search/replace blocks.

    Returns True if the content appears to use search/replace format.
    """
    pattern = r'<<<<<<< SEARCH.*?=======.*?>>>>>>> REPLACE'
    return bool(re.search(pattern, content, re.DOTALL))


def is_full_file_format(content: str) -> bool:
    """
    Check if content contains full file code blocks.

    Returns True if the content appears to be full file(s).
    """
    # Check for typical full file markers
    patterns = [
        r'```(?:\w+)?\s*\n(?://|#)\s*File:\s*[^\n]+\n',  # File: comment
        r'```(?:\w+)?\s*\n[a-zA-Z0-9_/-]+\.[a-zA-Z0-9]+\n',  # Direct path
    ]

    for pattern in patterns:
        if re.search(pattern, content):
            return True

    return False


def extract_edits_by_file(content: str) -> Dict[str, List[SearchReplaceEdit]]:
    """
    Group search/replace edits by file path.

    Returns:
        Dict mapping file paths to lists of edits for that file
    """
    edits = extract_search_replace_blocks(content)

    by_file: Dict[str, List[SearchReplaceEdit]] = {}
    for edit in edits:
        if edit.file_path not in by_file:
            by_file[edit.file_path] = []
        by_file[edit.file_path].append(edit)

    return by_file
