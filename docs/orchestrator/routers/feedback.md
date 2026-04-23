# Feedback Router

**File**: `orchestrator/app/routers/feedback.py`

**Base path**: `/api/feedback`

## Purpose

In-product feedback board: users file posts, vote, and comment. Consumed by the Feedback page in settings.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `` | user | List feedback posts (paginated/filterable). |
| GET | `/{feedback_id}` | user | Post detail including comments. |
| POST | `` | user | Create a feedback post (201). |
| PATCH | `/{feedback_id}` | user | Edit post (author or admin). |
| DELETE | `/{feedback_id}` | user | Delete post (author or admin, 204). |
| POST | `/{feedback_id}/upvote` | user | Toggle upvote. |
| POST | `/{feedback_id}/comments` | user | Add a comment (201). |

## Auth

All endpoints require `current_active_user`. Admin privileges allow moderating others' posts.

## Related

- Models: `FeedbackPost`, `FeedbackComment`, `FeedbackUpvote` in [models.py](../../../orchestrator/app/models.py).
- Schemas: `FeedbackPostRead`, `FeedbackCommentRead`, `UpvoteResponse` in [schemas.py](../../../orchestrator/app/schemas.py).
