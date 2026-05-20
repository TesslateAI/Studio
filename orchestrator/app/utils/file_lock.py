"""Cross-platform advisory file locking.

POSIX provides ``fcntl.flock``; Windows has no ``fcntl`` module at all, so
the desktop sidecar (which runs on Windows) routes through ``msvcrt.locking``.
``msvcrt`` has no shared-lock mode, so shared locks degrade to exclusive on
Windows — correct, just stricter, and fine for the single-process desktop
sidecar.

All functions take an integer file descriptor (pass ``file_obj.fileno()``).
On Windows the descriptor must be opened with write access for the lock to
be placed.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    import msvcrt

    def lock_exclusive(fd: int, *, blocking: bool = True) -> bool:
        """Take an exclusive lock. Returns False if non-blocking and held."""
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, mode, 1)
            return True
        except OSError:
            if blocking:
                raise
            return False

    def lock_shared(fd: int, *, blocking: bool = True) -> bool:
        """msvcrt has no shared mode; an exclusive lock is a correct substitute."""
        return lock_exclusive(fd, blocking=blocking)

    def unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def lock_exclusive(fd: int, *, blocking: bool = True) -> bool:
        """Take an exclusive lock. Returns False if non-blocking and held."""
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
            return True
        except BlockingIOError:
            return False

    def lock_shared(fd: int, *, blocking: bool = True) -> bool:
        """Take a shared (reader) lock. Returns False if non-blocking and held."""
        flags = fcntl.LOCK_SH | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
            return True
        except BlockingIOError:
            return False

    def unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
