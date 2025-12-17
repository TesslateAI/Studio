# Marketplace Recommendations System

This document describes the co-installation based recommendation system used for the "People also like" feature in the marketplace.

## Overview

The recommendations system tracks which agents are frequently installed together by users, enabling intelligent "People also like" suggestions on agent detail pages. It uses a pre-computed co-installation count approach that ensures:

- **O(n) update time**: Where n = number of agents user has installed
- **O(1) query time**: Constant-time lookup for recommendations
- **Non-blocking**: Updates run as background tasks
- **Zero extra resource usage**: No ML models, no external services

## Architecture

### Database Model

```python
# orchestrator/app/models.py
class AgentCoInstall(Base):
    """Tracks co-installation patterns between agents."""
    __tablename__ = "agent_co_installs"

    id = Column(UUID, primary_key=True, default=uuid4)
    agent_id = Column(UUID, ForeignKey("marketplace_agents.id"), nullable=False)
    related_agent_id = Column(UUID, ForeignKey("marketplace_agents.id"), nullable=False)
    co_install_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Unique constraint ensures one record per pair
    __table_args__ = (
        UniqueConstraint('agent_id', 'related_agent_id', name='uq_agent_co_install_pair'),
    )
```

### Service Layer

Located at `orchestrator/app/services/recommendations.py`:

```python
# Update co-install counts when user installs an agent
async def update_co_install_counts(db, user_id, new_agent_id) -> None

# Get related agents for recommendations
async def get_related_agents(db, agent_slug, limit=6, exclude_agent_ids=None) -> List[dict]
```

## Algorithm

### On Agent Installation

When a user installs agent X:

1. Look up user's existing installed agents: [A, B, C]
2. For each existing agent, create/update co-install pairs:
   - (A, X) +1 count
   - (X, A) +1 count
   - (B, X) +1 count
   - (X, B) +1 count
   - (C, X) +1 count
   - (X, C) +1 count
3. Uses PostgreSQL upsert (INSERT ON CONFLICT) for atomic updates

**Time Complexity**: O(n) where n = number of user's installed agents

### On Recommendation Query

When viewing agent X's detail page:

1. Query `AgentCoInstall` for rows where `agent_id = X`
2. Order by `co_install_count DESC`
3. Filter out already-installed agents
4. Return top N related agents

**Time Complexity**: O(1) - simple indexed query

### Fallback Strategy

If co-install data is sparse (new agent, cold start):
- Fall back to same-category agents
- Ordered by download count

## API Endpoints

### GET `/api/marketplace/agents/{slug}/related`

Returns related agents based on co-installation patterns.

**Parameters:**
- `slug` (path): Agent slug to get recommendations for
- `limit` (query, optional): Max agents to return (1-12, default 6)

**Response:**
```json
{
  "related_agents": [
    {
      "id": "uuid",
      "name": "Agent Name",
      "slug": "agent-slug",
      "description": "...",
      "category": "productivity",
      "icon": "emoji",
      "avatar_url": "...",
      "downloads": 1234,
      "rating": 4.8,
      "pricing_type": "free"
    }
  ]
}
```

### Background Task Integration

Co-install updates are triggered automatically on:
- Free agent purchases (POST `/api/marketplace/agents/{id}/purchase`)
- Paid agent verification (POST `/api/marketplace/verify-purchase`)

Both use FastAPI's `BackgroundTasks` to ensure non-blocking behavior:

```python
background_tasks.add_task(update_recommendations)
```

## Frontend Integration

The MarketplaceDetail page (`app/src/pages/MarketplaceDetail.tsx`) uses the recommendations API:

```typescript
// Load related items using recommendations API
const related = await marketplaceApi.getRelatedAgents(slug, 4);
setRelatedItems(related);
```

Falls back to category-based suggestions if the API call fails.

## Database Migration

When deploying, ensure the `agent_co_installs` table is created:

```sql
CREATE TABLE agent_co_installs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES marketplace_agents(id),
    related_agent_id UUID NOT NULL REFERENCES marketplace_agents(id),
    co_install_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_agent_co_install_pair UNIQUE (agent_id, related_agent_id)
);

CREATE INDEX idx_co_install_agent_id ON agent_co_installs(agent_id);
CREATE INDEX idx_co_install_count ON agent_co_installs(agent_id, co_install_count DESC);
```

## Performance Considerations

1. **Indexed Queries**: Primary query uses `agent_id` index + `co_install_count` ordering
2. **Background Processing**: Updates don't block the purchase response
3. **Separate Session**: Background tasks use independent DB sessions
4. **Upsert Pattern**: Single SQL statement for insert-or-update

## Future Improvements

Potential enhancements (not currently implemented):

1. **Decay factor**: Weight recent co-installs higher
2. **Category weighting**: Boost same-category recommendations
3. **User similarity**: "Users like you also installed..."
4. **Negative signals**: Track uninstalls to reduce counts
5. **A/B testing**: Compare recommendation strategies
