"""
Async file I/O utilities
Wraps blocking file operations to prevent blocking the event loop.
"""
import asyncio
import os
import shutil
from typing import Optional, List, Callable, Tuple
from pathlib import Path


async def rmtree_async(path: str, progress_callback: Optional[Callable] = None) -> None:
    """
    Async version of shutil.rmtree with progress tracking

    Args:
        path: Directory path to remove
        progress_callback: Optional callback(current, total, path) for progress updates
    """
    def _count_items(directory: str) -> int:
        """Count total files and directories"""
        count = 0
        try:
            for root, dirs, files in os.walk(directory):
                count += len(files) + len(dirs)
        except Exception:
            pass
        return count

    def _rmtree_with_progress(directory: str, callback: Optional[Callable] = None):
        """Remove directory tree with progress tracking"""
        if not os.path.exists(directory):
            return

        total_items = _count_items(directory) if callback else 0
        current_item = 0

        def on_error(func, path, exc_info):
            """Error handler for rmtree"""
            # Try to change permissions and retry
            try:
                os.chmod(path, 0o777)
                func(path)
            except Exception:
                pass

        # Walk through directory in reverse to delete files first
        for root, dirs, files in os.walk(directory, topdown=False):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    os.chmod(file_path, 0o777)
                    os.remove(file_path)
                    current_item += 1
                    if callback:
                        callback(current_item, total_items, file_path)
                except Exception:
                    pass

            for name in dirs:
                dir_path = os.path.join(root, name)
                try:
                    os.chmod(dir_path, 0o777)
                    os.rmdir(dir_path)
                    current_item += 1
                    if callback:
                        callback(current_item, total_items, dir_path)
                except Exception:
                    pass

        # Finally remove the root directory
        try:
            os.rmdir(directory)
        except Exception:
            # Fallback to shutil.rmtree if manual removal failed
            shutil.rmtree(directory, onerror=on_error)

    # Run in thread pool to avoid blocking event loop
    await asyncio.to_thread(_rmtree_with_progress, path, progress_callback)


async def walk_directory_async(
    directory: str,
    exclude_dirs: Optional[List[str]] = None,
    max_depth: Optional[int] = None
) -> List[Tuple[str, List[str], List[str]]]:
    """
    Async version of os.walk

    Args:
        directory: Directory to walk
        exclude_dirs: Directory names to exclude (e.g., ['node_modules', '.git'])
        max_depth: Maximum depth to traverse

    Returns:
        List of (root, dirs, files) tuples
    """
    def _walk():
        exclude = exclude_dirs or []
        results = []

        for root, dirs, files in os.walk(directory):
            # Calculate depth
            if max_depth is not None:
                depth = root[len(directory):].count(os.sep)
                if depth >= max_depth:
                    dirs.clear()
                    continue

            # Filter excluded directories
            dirs[:] = [d for d in dirs if d not in exclude]

            results.append((root, dirs, files))

        return results

    return await asyncio.to_thread(_walk)


async def read_file_async(file_path: str, encoding: str = 'utf-8', errors: str = 'replace') -> str:
    """
    Async file read

    Args:
        file_path: Path to file
        encoding: Character encoding
        errors: Error handling strategy

    Returns:
        File contents as string
    """
    def _read():
        with open(file_path, 'r', encoding=encoding, errors=errors) as f:
            return f.read()

    return await asyncio.to_thread(_read)


async def write_file_async(
    file_path: str,
    content: str,
    encoding: str = 'utf-8',
    mode: str = 'w'
) -> None:
    """
    Async file write

    Args:
        file_path: Path to file
        content: Content to write
        encoding: Character encoding
        mode: Write mode ('w' or 'a')
    """
    def _write():
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, mode, encoding=encoding) as f:
            f.write(content)

    await asyncio.to_thread(_write)


async def copy_file_async(src: str, dst: str) -> None:
    """
    Async file copy

    Args:
        src: Source file path
        dst: Destination file path
    """
    await asyncio.to_thread(shutil.copy2, src, dst)


async def copy_tree_async(
    src: str,
    dst: str,
    progress_callback: Optional[Callable] = None
) -> None:
    """
    Async directory tree copy with progress

    Args:
        src: Source directory
        dst: Destination directory
        progress_callback: Optional callback(current, total, path)
    """
    def _count_files(directory: str) -> int:
        count = 0
        for _, _, files in os.walk(directory):
            count += len(files)
        return count

    def _copy_tree_with_progress(source: str, destination: str, callback: Optional[Callable] = None):
        total_files = _count_files(source) if callback else 0
        current_file = 0

        def copy_function(src, dst):
            nonlocal current_file
            shutil.copy2(src, dst)
            current_file += 1
            if callback:
                callback(current_file, total_files, src)

        shutil.copytree(source, destination, copy_function=copy_function)

    await asyncio.to_thread(_copy_tree_with_progress, src, dst, progress_callback)


async def makedirs_async(path: str, exist_ok: bool = True) -> None:
    """
    Async directory creation

    Args:
        path: Directory path
        exist_ok: Don't raise error if directory exists
    """
    await asyncio.to_thread(os.makedirs, path, exist_ok=exist_ok)


async def path_exists_async(path: str) -> bool:
    """
    Async path existence check

    Args:
        path: Path to check

    Returns:
        True if path exists
    """
    return await asyncio.to_thread(os.path.exists, path)


async def get_directory_size_async(directory: str) -> int:
    """
    Get total size of directory in bytes

    Args:
        directory: Directory path

    Returns:
        Size in bytes
    """
    def _get_size():
        total_size = 0
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    total_size += os.path.getsize(file_path)
                except Exception:
                    pass
        return total_size

    return await asyncio.to_thread(_get_size)


async def count_files_async(directory: str, exclude_dirs: Optional[List[str]] = None) -> int:
    """
    Count total files in directory

    Args:
        directory: Directory path
        exclude_dirs: Directories to exclude

    Returns:
        File count
    """
    def _count():
        exclude = exclude_dirs or []
        count = 0
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in exclude]
            count += len(files)
        return count

    return await asyncio.to_thread(_count)
