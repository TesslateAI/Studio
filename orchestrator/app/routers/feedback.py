"""
Feedback system API endpoints.

Provides endpoints for:
- Creating and listing feedback posts (bugs/suggestions)
- Upvoting feedback posts
- Adding comments to feedback posts
- Updating feedback status (admin only)
"""
import uuid
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, asc, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import FeedbackPost, FeedbackUpvote, FeedbackComment
from ..models_auth import User
from ..schemas_feedback import (
    FeedbackPostCreate,
    FeedbackPostRead,
    FeedbackPostList,
    FeedbackPostDetail,
    FeedbackPostUpdate,
    FeedbackCommentCreate,
    FeedbackCommentRead,
    UpvoteResponse,
)
from ..users import current_active_user, current_superuser


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


# ============================================================================
# Feedback Post Endpoints
# ============================================================================

@router.get("", response_model=FeedbackPostList)
async def list_feedback(
    type: Optional[str] = Query(None, description="Filter by type: 'bug' or 'suggestion'"),
    status: Optional[str] = Query(None, description="Filter by status"),
    sort: str = Query("upvotes", description="Sort by: 'upvotes', 'date', or 'comments'"),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    List all feedback posts with filters and sorting.

    Returns posts with upvote status for the current user.
    """
    # Build query
    query = select(FeedbackPost).options(
        selectinload(FeedbackPost.user),
        selectinload(FeedbackPost.upvotes),
        selectinload(FeedbackPost.comments),
    )

    # Apply filters
    if type:
        query = query.where(FeedbackPost.type == type)
    if status:
        query = query.where(FeedbackPost.status == status)

    # Apply sorting
    if sort == "upvotes":
        query = query.order_by(desc(FeedbackPost.upvote_count), desc(FeedbackPost.created_at))
    elif sort == "date":
        query = query.order_by(desc(FeedbackPost.created_at))
    elif sort == "comments":
        # Count comments via relationship
        query = query.order_by(desc(FeedbackPost.created_at))  # We'll sort by comment count in Python

    # Get total count
    count_query = select(func.count()).select_from(FeedbackPost)
    if type:
        count_query = count_query.where(FeedbackPost.type == type)
    if status:
        count_query = count_query.where(FeedbackPost.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Execute query
    result = await db.execute(query)
    posts = result.scalars().all()

    # Convert to response format with user-specific data
    posts_data = []
    for post in posts:
        # Check if current user has upvoted
        has_upvoted = any(upvote.user_id == current_user.id for upvote in post.upvotes)

        posts_data.append(FeedbackPostRead(
            id=post.id,
            user_id=post.user_id,
            user_name=post.user.name if post.user else "Unknown",
            type=post.type,
            title=post.title,
            description=post.description,
            status=post.status,
            upvote_count=post.upvote_count,
            has_upvoted=has_upvoted,
            comment_count=len(post.comments),
            created_at=post.created_at,
            updated_at=post.updated_at,
        ))

    # Sort by comments if requested (after loading)
    if sort == "comments":
        posts_data.sort(key=lambda p: p.comment_count, reverse=True)

    return FeedbackPostList(posts=posts_data, total=total)


@router.get("/{feedback_id}", response_model=FeedbackPostDetail)
async def get_feedback(
    feedback_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Get a single feedback post with all comments.
    """
    query = select(FeedbackPost).where(FeedbackPost.id == feedback_id).options(
        selectinload(FeedbackPost.user),
        selectinload(FeedbackPost.upvotes),
        selectinload(FeedbackPost.comments).selectinload(FeedbackComment.user),
    )

    result = await db.execute(query)
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Feedback post not found")

    # Check if current user has upvoted
    has_upvoted = any(upvote.user_id == current_user.id for upvote in post.upvotes)

    # Convert comments
    comments_data = [
        FeedbackCommentRead(
            id=comment.id,
            user_id=comment.user_id,
            user_name=comment.user.name if comment.user else "Unknown",
            feedback_id=comment.feedback_id,
            content=comment.content,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        )
        for comment in sorted(post.comments, key=lambda c: c.created_at)
    ]

    return FeedbackPostDetail(
        id=post.id,
        user_id=post.user_id,
        user_name=post.user.name if post.user else "Unknown",
        type=post.type,
        title=post.title,
        description=post.description,
        status=post.status,
        upvote_count=post.upvote_count,
        has_upvoted=has_upvoted,
        created_at=post.created_at,
        updated_at=post.updated_at,
        comments=comments_data,
    )


@router.post("", response_model=FeedbackPostRead, status_code=201)
async def create_feedback(
    feedback: FeedbackPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create a new feedback post (bug or suggestion).
    """
    # Validate type
    if feedback.type not in ["bug", "suggestion"]:
        raise HTTPException(status_code=400, detail="Type must be 'bug' or 'suggestion'")

    # Create post
    new_post = FeedbackPost(
        user_id=current_user.id,
        type=feedback.type,
        title=feedback.title,
        description=feedback.description,
        status="open",
        upvote_count=0,
    )

    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)

    # Load user relationship
    await db.refresh(new_post, ["user"])

    return FeedbackPostRead(
        id=new_post.id,
        user_id=new_post.user_id,
        user_name=current_user.name,
        type=new_post.type,
        title=new_post.title,
        description=new_post.description,
        status=new_post.status,
        upvote_count=0,
        has_upvoted=False,
        comment_count=0,
        created_at=new_post.created_at,
        updated_at=new_post.updated_at,
    )


@router.patch("/{feedback_id}", response_model=FeedbackPostRead)
async def update_feedback(
    feedback_id: uuid.UUID,
    update: FeedbackPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_superuser),  # Admin only
):
    """
    Update feedback post status (admin only).
    """
    query = select(FeedbackPost).where(FeedbackPost.id == feedback_id).options(
        selectinload(FeedbackPost.user),
        selectinload(FeedbackPost.upvotes),
        selectinload(FeedbackPost.comments),
    )

    result = await db.execute(query)
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Feedback post not found")

    # Validate status
    valid_statuses = ["open", "in_progress", "resolved", "closed"]
    if update.status and update.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(valid_statuses)}")

    # Update fields
    if update.status:
        post.status = update.status
        post.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(post)

    # Check if current user has upvoted
    has_upvoted = any(upvote.user_id == current_user.id for upvote in post.upvotes)

    return FeedbackPostRead(
        id=post.id,
        user_id=post.user_id,
        user_name=post.user.name if post.user else "Unknown",
        type=post.type,
        title=post.title,
        description=post.description,
        status=post.status,
        upvote_count=post.upvote_count,
        has_upvoted=has_upvoted,
        comment_count=len(post.comments),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Delete a feedback post (owner or admin only).
    """
    query = select(FeedbackPost).where(FeedbackPost.id == feedback_id)
    result = await db.execute(query)
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Feedback post not found")

    # Check permissions (owner or admin)
    if post.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized to delete this feedback")

    await db.delete(post)
    await db.commit()

    return None


# ============================================================================
# Upvote Endpoints
# ============================================================================

@router.post("/{feedback_id}/upvote", response_model=UpvoteResponse)
async def toggle_upvote(
    feedback_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Toggle upvote on a feedback post.

    If user has already upvoted, remove the upvote.
    If user hasn't upvoted, add an upvote.
    """
    # Check if post exists
    post_query = select(FeedbackPost).where(FeedbackPost.id == feedback_id)
    post_result = await db.execute(post_query)
    post = post_result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Feedback post not found")

    # Check if user has already upvoted
    upvote_query = select(FeedbackUpvote).where(
        FeedbackUpvote.user_id == current_user.id,
        FeedbackUpvote.feedback_id == feedback_id,
    )
    upvote_result = await db.execute(upvote_query)
    existing_upvote = upvote_result.scalar_one_or_none()

    if existing_upvote:
        # Remove upvote
        await db.delete(existing_upvote)
        post.upvote_count = max(0, post.upvote_count - 1)
        upvoted = False
    else:
        # Add upvote
        new_upvote = FeedbackUpvote(
            user_id=current_user.id,
            feedback_id=feedback_id,
        )
        db.add(new_upvote)
        post.upvote_count += 1
        upvoted = True

    await db.commit()
    await db.refresh(post)

    return UpvoteResponse(
        upvoted=upvoted,
        upvote_count=post.upvote_count,
    )


# ============================================================================
# Comment Endpoints
# ============================================================================

@router.post("/{feedback_id}/comments", response_model=FeedbackCommentRead, status_code=201)
async def create_comment(
    feedback_id: uuid.UUID,
    comment: FeedbackCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Add a comment to a feedback post.
    """
    # Check if post exists
    post_query = select(FeedbackPost).where(FeedbackPost.id == feedback_id)
    post_result = await db.execute(post_query)
    post = post_result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail="Feedback post not found")

    # Create comment
    new_comment = FeedbackComment(
        user_id=current_user.id,
        feedback_id=feedback_id,
        content=comment.content,
    )

    db.add(new_comment)
    await db.commit()
    await db.refresh(new_comment)

    return FeedbackCommentRead(
        id=new_comment.id,
        user_id=new_comment.user_id,
        user_name=current_user.name,
        feedback_id=new_comment.feedback_id,
        content=new_comment.content,
        created_at=new_comment.created_at,
        updated_at=new_comment.updated_at,
    )
