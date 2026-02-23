"""
Pydantic schemas for feedback system.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ============================================================================
# Feedback Post Schemas
# ============================================================================


class FeedbackPostCreate(BaseModel):
    """Schema for creating a new feedback post."""

    type: str = Field(..., description="Type of feedback: 'bug' or 'suggestion'")
    title: str = Field(..., min_length=1, max_length=500, description="Feedback title")
    description: str = Field(..., min_length=1, description="Detailed description")


class FeedbackPostUpdate(BaseModel):
    """Schema for updating a feedback post (admin only)."""

    status: str | None = Field(
        None, description="Status: 'open', 'in_progress', 'resolved', 'closed'"
    )


class FeedbackPostRead(BaseModel):
    """Schema for reading feedback post data."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str  # From relationship
    username: str | None = None  # @username handle
    avatar_url: str | None = None  # Profile picture URL
    type: str
    title: str
    description: str
    status: str
    upvote_count: int
    has_upvoted: bool = False  # Whether current user has upvoted
    comment_count: int = 0  # Number of comments
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeedbackPostList(BaseModel):
    """Schema for listing feedback posts."""

    posts: list[FeedbackPostRead]
    total: int


# ============================================================================
# Feedback Comment Schemas
# ============================================================================


class FeedbackCommentCreate(BaseModel):
    """Schema for creating a new comment."""

    content: str = Field(..., min_length=1, description="Comment content")


class FeedbackCommentRead(BaseModel):
    """Schema for reading comment data."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str  # From relationship
    username: str | None = None  # @username handle
    avatar_url: str | None = None  # Profile picture URL
    feedback_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Feedback Detail Schema (with comments)
# ============================================================================


class FeedbackPostDetail(BaseModel):
    """Schema for reading feedback post with comments."""

    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    username: str | None = None
    avatar_url: str | None = None
    type: str
    title: str
    description: str
    status: str
    upvote_count: int
    has_upvoted: bool = False
    is_owner: bool = False  # Whether current user owns this feedback
    created_at: datetime
    updated_at: datetime
    comments: list[FeedbackCommentRead] = []

    class Config:
        from_attributes = True


# ============================================================================
# Response Schemas
# ============================================================================


class UpvoteResponse(BaseModel):
    """Response after toggling upvote."""

    upvoted: bool  # True if upvoted, False if removed
    upvote_count: int  # New upvote count
