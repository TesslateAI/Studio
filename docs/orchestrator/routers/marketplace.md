# Marketplace Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/marketplace.py` (~2600 lines)

The marketplace router manages the agent and base template marketplace where users can browse, purchase, and publish AI agents and project templates.

## Overview

The marketplace has two main sections:
1. **Agents**: Pre-configured AI agents with custom prompts and tool sets
2. **Bases**: Starter project templates (Next.js, React, Vue, etc.)

Both support:
- Free and paid listings
- User reviews and ratings
- Purchase tracking
- Creator royalties
- Publishing workflow

## Base Path

All endpoints are mounted at `/api/marketplace`

## Model Configuration

### Get Available Models

```
GET /api/marketplace/models
```

Returns list of AI models available for agent creation, including system models and user's custom models.

**Response**:
```json
{
  "models": [
    {
      "id": "claude-sonnet-4-5-20250929",
      "name": "Claude Sonnet 4.5",
      "source": "system",
      "provider": "internal",
      "pricing": {"input": 3.0, "output": 15.0},
      "available": true
    }
  ],
  "default": "claude-sonnet-4-5-20250929",
  "count": 15,
  "external_providers": [
    {
      "provider": "openrouter",
      "name": "OpenRouter",
      "has_key": false,
      "setup_required": true,
      "models_count": "200+"
    }
  ],
  "custom_models": []
}
```

### Add Custom Model

```
POST /api/marketplace/models/custom
```

Adds a custom model from OpenRouter to the user's account.

**Request Body**:
```json
{
  "model_id": "anthropic/claude-3-opus",
  "model_name": "Claude 3 Opus",
  "pricing_input": 15.0,
  "pricing_output": 75.0
}
```

## Agent Marketplace

### Browse Agents

```
GET /api/marketplace/agents
```

Browse published agents with filtering and pagination.

**Query Parameters**:
- `category`: Filter by category (web-development, data-analysis, devops, etc.)
- `pricing_type`: Filter by pricing (free, credits, subscription)
- `search`: Search in name, description, and tags
- `sort`: Sort by (featured, popular, newest, price_asc, price_desc)
- `page`: Page number (1-indexed, default: 1)
- `limit`: Results per page (default: 12, max: 50)

**Response**:
```json
{
  "agents": [
    {
      "id": "uuid",
      "name": "React Specialist",
      "slug": "react-specialist",
      "description": "Expert in React development",
      "category": "web-development",
      "pricing_type": "free",
      "price_credits": 0,
      "downloads": 1542,
      "rating": 4.7,
      "review_count": 89,
      "creator": {
        "id": "uuid",
        "username": "techcreator"
      }
    }
  ],
  "total": 45,
  "skip": 0,
  "limit": 20
}
```

### Get Agent Details

```
GET /api/marketplace/agents/{agent_id}
```

Returns full details for a specific agent including system prompt (if user purchased or creator).

**Response**:
```json
{
  "id": "uuid",
  "name": "React Specialist",
  "description": "Expert in React development...",
  "system_prompt": "You are an expert React developer...",  // Only if purchased
  "category": "web-development",
  "pricing_type": "free",
  "model": "claude-sonnet-4-5-20250929",
  "is_purchased": true,
  "creator": {...},
  "reviews": [...]
}
```

### Purchase Agent

```
POST /api/marketplace/agents/{agent_id}/purchase
```

Purchases an agent (free or paid).

**Request Body**:
```json
{
  "payment_method": "credits|subscription"  // For paid agents
}
```

**Response**:
```json
{
  "message": "Agent purchased successfully",
  "purchase": {
    "id": "uuid",
    "agent_id": "uuid",
    "purchased_at": "2025-01-09T10:00:00Z"
  }
}
```

**Credit Deduction**:
For paid agents, credits are deducted from user's balance. Transaction recorded in `MarketplaceTransaction`.

### Review Agent (Create or Update)

```
POST /api/marketplace/agents/{agent_id}/review?rating=5&comment=Great+agent
```

Create or update (upsert) a review for a purchased agent. If the user already has a review, it overwrites rating/comment/timestamp.

**Query Parameters**:
- `rating` (required, 1-5): Star rating
- `comment` (optional): Review text

**Response**:
```json
{
  "message": "Review submitted successfully",
  "rating": 5
}
```

**Restrictions**:
- Must have purchased agent (`UserPurchasedAgent` with `is_active=True`)
- One review per user per agent (upsert pattern)
- Rating must be 1-5

**Side effect**: Recalculates `MarketplaceAgent.rating` (avg) and `.reviews_count` via SQL aggregate.

### Get Agent Reviews

```
GET /api/marketplace/agents/{agent_id}/reviews?page=1&limit=10
```

**(Public, optional auth)** Paginated reviews with user info.

**Response**:
```json
{
  "reviews": [
    {
      "id": "uuid",
      "rating": 5,
      "comment": "Great agent!",
      "created_at": "2025-01-01T00:00:00",
      "user_id": "uuid",
      "user_name": "John",
      "user_avatar_url": "https://...",
      "is_own_review": false
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 10,
  "has_more": true
}
```

### Delete Agent Review

```
DELETE /api/marketplace/agents/{agent_id}/review
```

**(Authenticated)** Delete current user's own review. Recalculates agent rating after deletion.

**Permission model**: Only your own review (filtered by `current_user.id`). No admin override.

### Get My Agents

```
GET /api/marketplace/agents/my-agents
```

Returns all agents purchased by the current user.

**Response**:
```json
{
  "agents": [...],
  "total": 12
}
```

## Base Marketplace

Bases are starter project templates (full codebases with frameworks, dependencies, configuration).

### Browse Bases

```
GET /api/marketplace/bases
```

Browse published project bases. Returns only active bases that are either seeded (no creator) or have `visibility=public`. Private user-submitted bases are excluded.

**Query Parameters**: Same as agents (category, pricing_type, search, sort, skip, limit)

**Visibility Filtering**:
```python
query = select(MarketplaceBase).where(
    MarketplaceBase.is_active == True,
    or_(
        MarketplaceBase.created_by_user_id.is_(None),  # seeded bases always visible
        MarketplaceBase.visibility == "public"           # user bases only when public
    )
)
```

**Response**: Similar to agents response but for bases, now includes `created_by_user_id`, `visibility`, and `creator_name` fields

### Get Base Details

```
GET /api/marketplace/bases/{base_id}
```

Returns full details for a project base.

**Response**:
```json
{
  "id": "uuid",
  "name": "E-commerce Starter",
  "slug": "ecommerce-starter",
  "description": "Full e-commerce platform with cart, checkout, admin",
  "category": "web-development",
  "pricing_type": "credits",
  "price_credits": 500,
  "git_repo_url": "https://github.com/creator/ecommerce-starter",
  "default_branch": "main",
  "is_purchased": false,
  "creator": {...},
  "screenshots": [...]
}
```

### Purchase Base

```
POST /api/marketplace/bases/{base_id}/purchase
```

Purchases a project base.

**Response**: Purchase object

After purchasing, users can create projects using this base:
```json
{
  "source_type": "base",
  "base_id": "uuid"
}
```

### Review Base (Create or Update)

```
POST /api/marketplace/bases/{base_id}/review?rating=5&comment=Great+template
```

Create or update (upsert) a review for a purchased base. Mirrors the agent review endpoint exactly.

**Query Parameters**:
- `rating` (required, 1-5): Star rating
- `comment` (optional): Review text

**Restrictions**:
- Must have purchased base (`UserPurchasedBase` with `is_active=True`)
- One review per user per base (upsert pattern)
- Rating must be 1-5

**Side effect**: Recalculates `MarketplaceBase.rating` (avg) and `.reviews_count` via SQL aggregate.

### Get Base Reviews

```
GET /api/marketplace/bases/{base_id}/reviews?page=1&limit=10
```

**(Public, optional auth)** Paginated reviews with user info. Same response shape as agent reviews.

### Delete Base Review

```
DELETE /api/marketplace/bases/{base_id}/review
```

**(Authenticated)** Delete current user's own review. Recalculates base rating after deletion.

## User-Submitted Bases

Users can submit their own project templates by providing a git repository URL. No admin approval is needed -- users control visibility (private/public) directly.

### Submit Base

```
POST /api/marketplace/bases/submit
```

**(Authenticated)** Create a new base from a git repository URL.

**Request Body**:
```json
{
  "name": "My SaaS Template",
  "description": "Full-stack SaaS with auth, billing, admin",
  "git_repo_url": "https://github.com/user/saas-template",
  "category": "fullstack",
  "default_branch": "main",
  "visibility": "public",
  "icon": "📦",
  "tags": ["nextjs", "stripe", "auth"],
  "tech_stack": ["Next.js", "PostgreSQL", "Stripe"],
  "features": ["Authentication", "Billing", "Admin Dashboard"],
  "long_description": "Detailed markdown description..."
}
```

**Validation**:
- `git_repo_url` must start with `https://`
- `visibility` must be `"private"` or `"public"`
- `category` must be one of: `fullstack`, `frontend`, `backend`, `mobile`, `data`, `devops`

**Behavior**:
- Generates slug from name + user_id + timestamp
- Sets `created_by_user_id` to current user
- Sets `pricing_type` to `"free"`
- Auto-creates `UserPurchasedBase` so creator has it in their library immediately
- No git clone at submit time -- clone happens only when a project is created from the base

**Response**: Created base object with `id`

### Update Base

```
PATCH /api/marketplace/bases/{base_id}
```

**(Authenticated, Owner only)** Update a user-submitted base.

**Request Body**: Partial update of any `BaseSubmitRequest` fields.

**Restrictions**: Must be base creator (`created_by_user_id == current_user.id`). Slug is regenerated if name changes.

### Toggle Base Visibility

```
PATCH /api/marketplace/bases/{base_id}/visibility
```

**(Authenticated, Owner only)** Switch a base between private and public.

**Request Body**:
```json
{
  "visibility": "private"
}
```

**Behavior**:
- Private: Only the creator can see and use the base
- Public: Visible on the marketplace browse page for all users

### Delete Base

```
DELETE /api/marketplace/bases/{base_id}
```

**(Authenticated, Owner only)** Soft-delete a user-submitted base (sets `is_active=False`).

### Get My Created Bases

```
GET /api/marketplace/my-created-bases
```

**(Authenticated)** Returns all bases created by the current user (both active and inactive are included for management).

**Response**:
```json
{
  "bases": [
    {
      "id": "uuid",
      "name": "My Template",
      "slug": "my-template-abc123",
      "description": "...",
      "git_repo_url": "https://github.com/...",
      "visibility": "public",
      "category": "fullstack",
      "downloads": 42,
      "rating": 4.5,
      "created_at": "2025-01-15T10:30:00Z",
      "is_active": true
    }
  ]
}
```

## Subagent Endpoints

Subagents are specialized child agents that the main agent can spawn for focused tasks. Each marketplace agent can have its own set of configured subagents.

### List Subagents

```
GET /api/marketplace/agents/{agent_id}/subagents
```

Returns all subagents configured for a specific agent.

**Response**:
```json
{
  "subagents": [
    {
      "id": "uuid",
      "name": "Code Reviewer",
      "system_prompt": "You review code for...",
      "tools": ["read_file", "bash_exec"]
    }
  ]
}
```

### Create Subagent

```
POST /api/marketplace/agents/{agent_id}/subagents
```

Add a new subagent to an agent (creator only).

**Request Body**:
```json
{
  "name": "Test Writer",
  "system_prompt": "You write tests for...",
  "tools": ["read_file", "write_file", "bash_exec"]
}
```

### Update Subagent

```
PATCH /api/marketplace/agents/{agent_id}/subagents/{subagent_id}
```

Update an existing subagent configuration (creator only).

### Delete Subagent

```
DELETE /api/marketplace/agents/{agent_id}/subagents/{subagent_id}
```

Remove a subagent from an agent (creator only).

## Creator Endpoints

Creators can publish their own agents and bases to the marketplace. The creator profile (`/api/creators/{user_id}/profile`) aggregates both published agents and public user-submitted bases, including combined download and review statistics.

### Publish Agent

```
POST /api/marketplace/agents/publish
```

Publish a new agent to the marketplace.

**Request Body**:
```json
{
  "name": "Vue.js Expert",
  "description": "Specialized in Vue 3 and Composition API",
  "system_prompt": "You are an expert Vue.js developer...",
  "category": "web-development",
  "pricing_type": "free|credits|subscription",
  "price_credits": 100,
  "model": "claude-sonnet-4-5-20250929",
  "tools": ["read_file", "write_file", "shell_execute"],
  "tags": ["vue", "javascript", "frontend"]
}
```

**Response**: Created agent object with status "pending_review"

**Publishing Workflow**:
1. Creator submits agent
2. Status: "pending_review"
3. Admin reviews in admin panel
4. Admin approves → Status: "published"
5. Agent appears in marketplace

### Update Agent

```
PATCH /api/marketplace/agents/{agent_id}/update
```

Update an existing agent (creator only).

**Request Body**: Same fields as publish (partial update)

**Restrictions**:
- Must be agent creator
- Cannot change pricing_type after purchases
- Major changes require re-approval

### Publish Base

```
POST /api/marketplace/bases/publish
```

Publish a project base to the marketplace.

**Request Body**:
```json
{
  "name": "SaaS Boilerplate",
  "description": "Full SaaS template with auth, billing, admin",
  "git_repo_url": "https://github.com/user/saas-boilerplate",
  "default_branch": "main",
  "category": "web-development",
  "pricing_type": "credits",
  "price_credits": 1000,
  "frameworks": ["Next.js", "PostgreSQL", "Stripe"],
  "screenshots": ["url1", "url2"]
}
```

**Response**: Created base object with status "pending_review"

### Get My Published Items

```
GET /api/marketplace/creators/my-items
```

Returns all agents and bases published by the creator.

**Response**:
```json
{
  "agents": [...],
  "bases": [...],
  "total_downloads": 542,
  "total_revenue": 15420  // In credits
}
```

## Admin Endpoints

### Moderate Agent

```
PATCH /api/marketplace/agents/{agent_id}/moderate
```

**(Superuser only)**

Approve or reject a pending agent.

**Request Body**:
```json
{
  "action": "approve|reject",
  "reason": "Optional rejection reason"
}
```

### Moderate Base

```
PATCH /api/marketplace/bases/{base_id}/moderate
```

**(Superuser only)**

Approve or reject a pending base.

### Get Pending Items

```
GET /api/marketplace/admin/pending
```

**(Superuser only)**

Returns all items pending moderation.

**Response**:
```json
{
  "agents": [
    {
      "id": "uuid",
      "name": "Pending Agent",
      "status": "pending_review",
      "submitted_at": "2025-01-09T10:00:00Z",
      "creator": {...}
    }
  ],
  "bases": [...]
}
```

## Recommendations

### Get Related Agents

```
GET /api/marketplace/agents/{agent_id}/related
```

Returns agents frequently purchased together (collaborative filtering).

**Response**:
```json
{
  "agents": [...],
  "algorithm": "co_install"
}
```

**Implementation**:

Uses `co_install_counts` field on MarketplaceAgent to track purchase correlations:
```json
{
  "agent_uuid_1": 42,  // Purchased together 42 times
  "agent_uuid_2": 28
}
```

## Categories

Standard categories for agents and bases:
- `web-development`: Frontend, backend, full-stack
- `data-analysis`: Data science, analytics, ML
- `devops`: Infrastructure, CI/CD, monitoring
- `mobile`: iOS, Android, React Native
- `game-development`: Unity, Unreal, Godot
- `design`: UI/UX, graphics, prototyping
- `writing`: Content creation, documentation
- `testing`: QA, automated testing, debugging
- `security`: Security audits, penetration testing
- `other`: Miscellaneous

## Pricing Types

1. **Free**: No cost, anyone can use
2. **Credits**: One-time credit purchase
3. **Subscription**: Requires Pro subscription

## Example Workflows

### Publishing an Agent

1. **Creator creates agent**:
   ```
   POST /api/marketplace/agents/publish
   {
     "name": "Django Expert",
     "system_prompt": "You are an expert Django developer...",
     "pricing_type": "credits",
     "price_credits": 200
   }
   ```

2. **Agent created with status "pending_review"**

3. **Admin reviews**:
   ```
   GET /api/marketplace/admin/pending
   ```

4. **Admin approves**:
   ```
   PATCH /api/marketplace/agents/{id}/moderate
   {"action": "approve"}
   ```

5. **Agent published**, status becomes "published"

6. **Agent appears in marketplace**

### Purchasing and Using an Agent

1. **User browses marketplace**:
   ```
   GET /api/marketplace/agents?category=web-development
   ```

2. **User purchases agent**:
   ```
   POST /api/marketplace/agents/{id}/purchase
   ```

3. **Credits deducted**, purchase recorded

4. **User selects agent in chat**:
   ```
   POST /api/chat/agent
   {
     "project_id": "uuid",
     "message": "Create a blog",
     "agent_id": "purchased-agent-uuid"
   }
   ```

5. **Agent runs with custom system prompt**

6. **User leaves review**:
   ```
   POST /api/marketplace/agents/{id}/review?rating=5&comment=Excellent!
   ```

## Revenue Sharing

When users purchase paid agents/bases, credits are distributed:
- **80%** to creator
- **20%** to platform

Tracked in `MarketplaceTransaction` with fields:
- `buyer_id`: User who purchased
- `seller_id`: Creator who published
- `amount_credits`: Total cost
- `platform_fee_credits`: Platform's 20%
- `creator_payout_credits`: Creator's 80%

Creators can withdraw earnings via Stripe Connect (future feature).

## Security

1. **System Prompt Protection**: Only buyers and creators see full system prompts
2. **Review Verification**: Must purchase before reviewing
3. **Moderation**: All items reviewed before publishing
4. **Content Filtering**: Descriptions and prompts scanned for inappropriate content
5. **Rate Limiting**: Publish and purchase endpoints rate-limited

## Implementation Notes

### Agent Search Casts JSON to Text

The `search` parameter on `GET /api/marketplace/agents` searches across `name`, `description`, and `tags`. Since `tags` is a JSON column in PostgreSQL, it must be cast to `String` before applying `func.lower()`. Without this cast, PostgreSQL throws an error because `lower()` does not accept JSON input.

```python
# Correct — cast JSON to text before lower()
func.lower(cast(MarketplaceAgent.tags, String)).like(func.lower(search_filter))

# Wrong — causes 500 error
func.lower(MarketplaceAgent.tags).like(func.lower(search_filter))
```

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - MarketplaceAgent, MarketplaceBase models
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/recommendations.py` - Recommendation engine
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/litellm_service.py` - Model management
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/factory.py` - Agent instantiation from marketplace models
