# Adding API Routers

This guide covers how to add new API endpoints to Tesslate Studio's FastAPI backend.

## Overview

Tesslate Studio uses FastAPI routers to organize API endpoints. Each router handles a specific domain of functionality (projects, chat, billing, etc.).

### Router Location

All routers are located in:
```
orchestrator/app/routers/
```

### Existing Routers

| Router | Prefix | Purpose |
|--------|--------|---------|
| `projects.py` | `/api/projects` | Project CRUD, container management |
| `chat.py` | `/api/chat` | Agent chat, streaming responses |
| `billing.py` | `/api` | Stripe subscriptions |
| `auth.py` | `/api/auth` | Authentication |
| `git.py` | `/api` | Git operations |
| `deployments.py` | `/api/deployments` | External deployments |
| `feedback.py` | `/api/feedback` | Bug reports and suggestions |

## Step 1: Create the Router File

Create a new file in `orchestrator/app/routers/`. Example: `notifications.py`

```python
"""
Notifications API endpoints.

Provides endpoints for:
- Listing user notifications
- Marking notifications as read
- Managing notification preferences
"""
import uuid
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Notification  # You'll need to create this model
from ..models_auth import User
from ..schemas_notifications import (  # You'll need to create these schemas
    NotificationCreate,
    NotificationRead,
    NotificationList,
)
from ..users import current_active_user


# Create the router with prefix and tags
router = APIRouter(prefix="/api/notifications", tags=["notifications"])
```

## Step 2: Define Endpoints

### GET Endpoint (List)

```python
@router.get("", response_model=NotificationList)
async def list_notifications(
    unread_only: bool = Query(False, description="Filter to unread only"),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    List all notifications for the current user.
    """
    # Build query
    query = select(Notification).where(Notification.user_id == current_user.id)

    # Apply filters
    if unread_only:
        query = query.where(Notification.read_at.is_(None))

    # Order by newest first
    query = query.order_by(desc(Notification.created_at))

    # Get total count
    count_query = select(func.count()).select_from(Notification).where(
        Notification.user_id == current_user.id
    )
    if unread_only:
        count_query = count_query.where(Notification.read_at.is_(None))
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Execute
    result = await db.execute(query)
    notifications = result.scalars().all()

    return NotificationList(
        notifications=[NotificationRead.model_validate(n) for n in notifications],
        total=total
    )
```

### GET Endpoint (Single Item)

```python
@router.get("/{notification_id}", response_model=NotificationRead)
async def get_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Get a single notification by ID.
    """
    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    )

    result = await db.execute(query)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return NotificationRead.model_validate(notification)
```

### POST Endpoint (Create)

```python
@router.post("", response_model=NotificationRead, status_code=201)
async def create_notification(
    notification: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create a new notification.
    """
    new_notification = Notification(
        user_id=current_user.id,
        title=notification.title,
        message=notification.message,
        type=notification.type,
    )

    db.add(new_notification)
    await db.commit()
    await db.refresh(new_notification)

    return NotificationRead.model_validate(new_notification)
```

### PATCH Endpoint (Update)

```python
@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_as_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Mark a notification as read.
    """
    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    )

    result = await db.execute(query)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.read_at = datetime.utcnow()
    await db.commit()
    await db.refresh(notification)

    return NotificationRead.model_validate(notification)
```

### DELETE Endpoint

```python
@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Delete a notification.
    """
    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    )

    result = await db.execute(query)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    await db.delete(notification)
    await db.commit()

    return None
```

## Step 3: Add Dependencies

### Common Dependencies

```python
from ..database import get_db
from ..models_auth import User
from ..users import current_active_user, current_superuser

# For authenticated endpoints
current_user: User = Depends(current_active_user)

# For admin-only endpoints
admin_user: User = Depends(current_superuser)

# For database access
db: AsyncSession = Depends(get_db)
```

### Custom Dependencies

Create custom dependencies for specific validation:

```python
from fastapi import Depends, HTTPException

async def get_notification_or_404(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
) -> Notification:
    """Dependency to get a notification or raise 404."""
    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    )
    result = await db.execute(query)
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    return notification


# Use in endpoint
@router.get("/{notification_id}")
async def get_notification(
    notification: Notification = Depends(get_notification_or_404),
):
    return notification
```

## Step 4: Register in main.py

Open `orchestrator/app/main.py` and add your router:

```python
# At the top, import your router
from .routers import projects, chat, agent, ..., notifications  # Add your import

# ...

# In the router registration section, add:
app.include_router(notifications.router)  # If prefix is already in router

# Or with custom prefix:
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
```

## Step 5: Add Schemas

Create schemas in `orchestrator/app/schemas_notifications.py`:

```python
"""Pydantic schemas for notifications."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    """Base notification fields."""
    title: str
    message: str
    type: str = "info"  # info, warning, error, success


class NotificationCreate(NotificationBase):
    """Schema for creating a notification."""
    pass


class NotificationRead(NotificationBase):
    """Schema for reading a notification."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationList(BaseModel):
    """Schema for notification list response."""
    notifications: List[NotificationRead]
    total: int
```

## Step 6: Add Database Model (if needed)

Add the model to `orchestrator/app/models.py`:

```python
class Notification(Base):
    """User notifications."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), default="info")
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="notifications")
```

## Step 7: Create Migration

```bash
cd orchestrator

# Generate migration
alembic revision --autogenerate -m "add_notifications_table"

# Review the generated migration file
# Edit if needed

# Run migration
alembic upgrade head
```

See [Database Migrations](database-migrations.md) for more details.

## Testing the Endpoint

### Manual Testing

```bash
# Using curl
curl -X GET "http://localhost:8000/api/notifications" \
  -H "Authorization: Bearer <token>"

# Using httpie
http GET http://localhost:8000/api/notifications Authorization:"Bearer <token>"
```

### Swagger UI

Visit http://localhost:8000/docs to test endpoints interactively.

### Automated Tests

Create tests in `orchestrator/tests/routers/test_notifications.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_notifications(
    client: AsyncClient,
    auth_headers: dict,
):
    """Test listing notifications."""
    response = await client.get(
        "/api/notifications",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "notifications" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_create_notification(
    client: AsyncClient,
    auth_headers: dict,
):
    """Test creating a notification."""
    response = await client.post(
        "/api/notifications",
        headers=auth_headers,
        json={
            "title": "Test Notification",
            "message": "This is a test",
            "type": "info",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Notification"
```

## Best Practices

### 1. Use Proper HTTP Status Codes

| Code | Use Case |
|------|----------|
| 200 | Successful GET, PUT, PATCH |
| 201 | Successful POST (created) |
| 204 | Successful DELETE (no content) |
| 400 | Bad request (validation error) |
| 401 | Not authenticated |
| 403 | Not authorized |
| 404 | Resource not found |
| 422 | Validation error (Pydantic) |

### 2. Document Endpoints

```python
@router.get("/{notification_id}", response_model=NotificationRead)
async def get_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Get a single notification by ID.

    Args:
        notification_id: UUID of the notification

    Returns:
        NotificationRead: The notification details

    Raises:
        HTTPException 404: Notification not found
    """
    ...
```

### 3. Use Query Parameters for Filtering

```python
@router.get("")
async def list_items(
    status: Optional[str] = Query(None, description="Filter by status"),
    created_after: Optional[datetime] = Query(None, description="Filter by creation date"),
    limit: int = Query(50, le=100, description="Maximum items to return"),
    offset: int = Query(0, description="Number of items to skip"),
):
    ...
```

### 4. Handle Errors Gracefully

```python
from fastapi import HTTPException

# Specific error
raise HTTPException(status_code=404, detail="Notification not found")

# With additional context
raise HTTPException(
    status_code=400,
    detail={
        "message": "Invalid notification type",
        "allowed_types": ["info", "warning", "error", "success"],
    },
)
```

## Complete Example

See `orchestrator/app/routers/feedback.py` for a complete, production-ready router implementation with:
- Full CRUD operations
- Proper authentication
- Pagination
- Filtering and sorting
- Related resources (comments, upvotes)

## Next Steps

- [Adding Agent Tools](adding-agent-tools.md) - Extend agent capabilities
- [Database Migrations](database-migrations.md) - Manage schema changes
- [Local Development](local-development.md) - Test your changes
