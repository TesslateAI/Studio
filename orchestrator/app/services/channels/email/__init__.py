"""Email-channel helpers (Phase 4).

Today only the approval-card builder lives here; future helpers (digest
emails, run-history exports) can join without further restructuring.
"""

from .approval_email import (
    ApprovalEmailContent,
    build_approval_email,
    send_approval_email,
)

__all__ = [
    "ApprovalEmailContent",
    "build_approval_email",
    "send_approval_email",
]
