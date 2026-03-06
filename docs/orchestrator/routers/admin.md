# Admin Router

**File**: `orchestrator/app/routers/admin.py` (~3500+ lines)

The admin router provides comprehensive platform administration capabilities for superusers.

## Overview

Admin endpoints are restricted to superusers only (checked via `current_superuser` dependency). They provide:

### Core Features
- **User Management**: Search, suspend, unsuspend, delete users, adjust credits
- **System Health**: Database, Kubernetes, LiteLLM, S3 monitoring
- **Token Analytics**: Usage by model, user, tier with anomaly detection
- **Audit Logs**: View, filter, export admin action logs
- **Project Administration**: List, hibernate, transfer, delete projects
- **Billing Administration**: Revenue overview, credit purchases, creator payouts
- **Deployment Monitoring**: Stats by provider, deployment list with filters

## Base Path

All endpoints are mounted at `/api/admin`

## Authentication

All endpoints require superuser role:

```python
@router.get("/metrics/users")
async def get_user_metrics(
    admin: User = Depends(current_superuser),  # Superuser required
    db: AsyncSession = Depends(get_db)
):
    ...
```

Non-superusers receive `403 Forbidden`.

## User Metrics

### Get User Metrics

```
GET /api/admin/metrics/users
```

Returns comprehensive user statistics.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_users": 1542,
  "new_users": 87,
  "dau": 234,
  "mau": 892,
  "growth_rate": 12.5,
  "retention_rate": 68.3,
  "daily_new_users": [
    {"date": "2025-01-01T00:00:00Z", "count": 3},
    {"date": "2025-01-02T00:00:00Z", "count": 5},
    ...
  ],
  "period_days": 30
}
```

**Metrics Explained**:

- **total_users**: All registered users
- **new_users**: Users registered in period
- **DAU** (Daily Active Users): Users active in last 24 hours (created projects or sent messages)
- **MAU** (Monthly Active Users): Users active in last 30 days
- **growth_rate**: (new_users - previous_period_users) / previous_period_users * 100
- **retention_rate**: % of users active in both current and previous week

### Get User List

```
GET /api/admin/users
```

Returns paginated list of all users with details.

**Query Parameters**:
- `skip`: Pagination offset (default: 0)
- `limit`: Results per page (default: 50)
- `search`: Search in username/email
- `tier`: Filter by subscription tier (free/pro)
- `sort`: Sort by (created_at, username, projects_count)

**Response**:
```json
{
  "users": [
    {
      "id": "uuid",
      "username": "johndoe",
      "email": "john@example.com",
      "subscription_tier": "pro",
      "created_at": "2024-12-01T10:00:00Z",
      "projects_count": 5,
      "messages_count": 234,
      "credit_balance_cents": 10000,
      "last_active": "2025-01-09T09:30:00Z"
    }
  ],
  "total": 1542,
  "skip": 0,
  "limit": 50
}
```

### Get User Details

```
GET /api/admin/users/{user_id}
```

Returns detailed information about a specific user.

**Response**:
```json
{
  "id": "uuid",
  "username": "johndoe",
  "email": "john@example.com",
  "subscription_tier": "pro",
  "stripe_customer_id": "cus_xxx",
  "stripe_subscription_id": "sub_xxx",
  "credit_balance_cents": 10000,
  "created_at": "2024-12-01T10:00:00Z",
  "projects": [
    {
      "id": "uuid",
      "name": "My App",
      "created_at": "2025-01-05T10:00:00Z"
    }
  ],
  "purchases": [
    {
      "agent_id": "uuid",
      "agent_name": "React Specialist",
      "purchased_at": "2025-01-08T10:00:00Z"
    }
  ],
  "usage_stats": {
    "total_requests": 542,
    "total_cost_cents": 2500,
    "total_tokens": 200000
  }
}
```

### Update User

```
PATCH /api/admin/users/{user_id}
```

Updates user account settings.

**Request Body**:
```json
{
  "subscription_tier": "pro|free",
  "credit_balance_cents": 5000,
  "is_active": true,
  "is_superuser": false
}
```

**Use Cases**:
- Grant complimentary Pro subscription
- Add credits for support issues
- Deactivate abusive accounts
- Promote user to admin

### Delete User

```
DELETE /api/admin/users/{user_id}
```

Permanently deletes a user and all associated data (projects, messages, purchases).

**Warning**: This is irreversible!

## Project Metrics

### Get Project Metrics

```
GET /api/admin/metrics/projects
```

Returns project creation and usage statistics.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_projects": 3842,
  "new_projects": 187,
  "active_projects": 542,
  "deployed_projects": 234,
  "projects_per_user_avg": 2.49,
  "daily_new_projects": [
    {"date": "2025-01-01T00:00:00Z", "count": 8},
    {"date": "2025-01-02T00:00:00Z", "count": 12},
    ...
  ],
  "by_source_type": {
    "template": 2100,
    "github": 980,
    "gitlab": 420,
    "base": 342
  },
  "period_days": 30
}
```

### Get Project Details

```
GET /api/admin/projects/{project_id}
```

Returns detailed information about a specific project.

**Response**:
```json
{
  "id": "uuid",
  "name": "My App",
  "slug": "my-app-k3x8n2",
  "owner": {
    "id": "uuid",
    "username": "johndoe"
  },
  "source_type": "github",
  "created_at": "2025-01-05T10:00:00Z",
  "containers": [...],
  "files_count": 87,
  "messages_count": 45,
  "deployments": [...],
  "environment_status": "ready"
}
```

## Agent Metrics

### Get Agent Metrics

```
GET /api/admin/metrics/agents
```

Returns AI agent usage statistics.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_requests": 15420,
  "total_cost_cents": 125000,
  "total_tokens_input": 5000000,
  "total_tokens_output": 2000000,
  "avg_cost_per_request": 8.11,
  "by_model": {
    "claude-sonnet-4-5-20250929": {
      "requests": 12000,
      "cost_cents": 100000,
      "percentage": 77.8
    },
    "gpt-4-turbo": {
      "requests": 3420,
      "cost_cents": 25000,
      "percentage": 22.2
    }
  },
  "by_agent": {
    "default-agent": {
      "requests": 10000,
      "cost_cents": 80000
    },
    "react-specialist": {
      "requests": 5420,
      "cost_cents": 45000
    }
  },
  "daily_requests": [
    {"date": "2025-01-01T00:00:00Z", "count": 420},
    {"date": "2025-01-02T00:00:00Z", "count": 538},
    ...
  ]
}
```

## Marketplace Moderation

### Get Pending Items

```
GET /api/admin/marketplace/pending
```

Returns agents and bases awaiting moderation.

**Response**:
```json
{
  "agents": [
    {
      "id": "uuid",
      "name": "Vue Expert",
      "creator": {
        "id": "uuid",
        "username": "creator123"
      },
      "status": "pending_review",
      "submitted_at": "2025-01-09T10:00:00Z",
      "category": "web-development",
      "pricing_type": "credits",
      "price_credits": 200
    }
  ],
  "bases": [
    {
      "id": "uuid",
      "name": "E-commerce Starter",
      "creator": {...},
      "status": "pending_review",
      "submitted_at": "2025-01-09T09:00:00Z"
    }
  ],
  "total_pending": 8
}
```

### Approve Agent

```
POST /api/admin/marketplace/agents/{agent_id}/approve
```

Approves a pending agent for publication.

**Request Body**:
```json
{
  "notes": "Approved - high quality"  // Optional
}
```

**Response**:
```json
{
  "message": "Agent approved and published",
  "agent": {
    "id": "uuid",
    "status": "published"
  }
}
```

Agent immediately appears in marketplace.

### Reject Agent

```
POST /api/admin/marketplace/agents/{agent_id}/reject
```

Rejects a pending agent.

**Request Body**:
```json
{
  "reason": "System prompt contains inappropriate content"
}
```

**Response**:
```json
{
  "message": "Agent rejected",
  "agent": {
    "id": "uuid",
    "status": "rejected"
  }
}
```

Creator receives notification with rejection reason.

### Approve Base

```
POST /api/admin/marketplace/bases/{base_id}/approve
```

Approves a pending project base.

### Reject Base

```
POST /api/admin/marketplace/bases/{base_id}/reject
```

Rejects a pending project base.

### Moderate Published Item

```
POST /api/admin/marketplace/agents/{agent_id}/moderate
```

Moderates a published agent (unpublish, flag, etc.).

**Request Body**:
```json
{
  "action": "unpublish|flag|ban",
  "reason": "Violation of terms of service"
}
```

**Actions**:
- **unpublish**: Removes from marketplace but keeps record
- **flag**: Marks for review without removing
- **ban**: Permanent ban, prevents republication

## System Health

### Get System Status

```
GET /api/admin/system/status
```

Returns platform health metrics.

**Response**:
```json
{
  "status": "healthy|degraded|down",
  "uptime_seconds": 2592000,
  "database": {
    "status": "connected",
    "pool_size": 10,
    "active_connections": 5
  },
  "orchestrator": {
    "mode": "kubernetes",
    "namespaces_count": 542,
    "active_pods": 847
  },
  "storage": {
    "type": "s3",
    "used_gb": 1250.5,
    "available_gb": 8749.5
  },
  "timestamp": "2025-01-09T10:00:00Z"
}
```

### Get Error Logs

```
GET /api/admin/system/logs
```

Returns recent error logs.

**Query Parameters**:
- `level`: Filter by level (error/warning/info)
- `limit`: Max logs (default: 100)

**Response**:
```json
{
  "logs": [
    {
      "timestamp": "2025-01-09T09:55:00Z",
      "level": "error",
      "message": "Failed to start container frontend-abc",
      "context": {
        "project_id": "uuid",
        "user_id": "uuid",
        "error": "ImagePullBackOff"
      }
    }
  ]
}
```

## Financial Metrics

### Get Revenue Metrics

```
GET /api/admin/metrics/revenue
```

Returns revenue and transaction statistics.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_revenue_cents": 125000,
  "total_revenue_usd": 1250.00,
  "subscription_revenue_cents": 80000,
  "credit_revenue_cents": 45000,
  "marketplace_revenue_cents": 15000,
  "transactions_count": 542,
  "by_type": {
    "subscription": {
      "count": 80,
      "revenue_cents": 80000
    },
    "credits": {
      "count": 420,
      "revenue_cents": 45000
    },
    "marketplace": {
      "count": 42,
      "revenue_cents": 15000
    }
  },
  "daily_revenue": [
    {"date": "2025-01-01T00:00:00Z", "revenue_cents": 4200},
    {"date": "2025-01-02T00:00:00Z", "revenue_cents": 3800},
    ...
  ]
}
```

## Bulk Operations

### Bulk Update Users

```
POST /api/admin/users/bulk-update
```

Updates multiple users at once.

**Request Body**:
```json
{
  "user_ids": ["uuid1", "uuid2", "uuid3"],
  "updates": {
    "subscription_tier": "pro",
    "credit_balance_cents": 5000
  }
}
```

**Use Cases**:
- Grant complimentary upgrades to beta testers
- Compensate affected users after incident
- Batch admin promotions

### Bulk Delete Projects

```
POST /api/admin/projects/bulk-delete
```

Deletes multiple projects at once.

**Request Body**:
```json
{
  "project_ids": ["uuid1", "uuid2", "uuid3"],
  "reason": "DMCA takedown request"
}
```

**Warning**: Irreversible!

## Analytics Export

### Export User Data

```
GET /api/admin/export/users
```

Exports user data to CSV.

**Query Parameters**:
- `start_date`: Period start
- `end_date`: Period end
- `tier`: Filter by tier

**Response**: CSV file download

```csv
id,username,email,subscription_tier,created_at,projects_count
uuid,johndoe,john@example.com,pro,2024-12-01T10:00:00Z,5
...
```

### Export Metrics

```
GET /api/admin/export/metrics
```

Exports metrics to JSON.

**Response**: JSON file with all metrics

## Audit Logs

### Get Audit Logs

```
GET /api/admin/audit-logs
```

Returns paginated list of admin action logs.

**Query Parameters**:
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 50)
- `action_type`: Filter by action type (e.g., "user_suspend", "project_delete")
- `target_type`: Filter by target type (user/project/agent/base)
- `start_date`: Filter from date (ISO format)
- `end_date`: Filter to date (ISO format)
- `search`: Search in details

**Response**:
```json
{
  "logs": [
    {
      "id": "uuid",
      "admin_id": "uuid",
      "admin_username": "admin@example.com",
      "action_type": "user_suspend",
      "target_type": "user",
      "target_id": "uuid",
      "details": {"reason": "Violation of TOS"},
      "ip_address": "192.168.1.1",
      "created_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 542,
  "page": 1,
  "page_size": 50,
  "total_pages": 11
}
```

### Export Audit Logs

```
GET /api/admin/audit-logs/export
```

Exports audit logs to CSV file.

**Query Parameters**: Same as Get Audit Logs

**Response**: CSV file download

## Project Administration

### Get Admin Projects

```
GET /api/admin/projects
```

Returns paginated list of all projects with admin details.

**Query Parameters**:
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 50)
- `search`: Search in project name/slug
- `status`: Filter by status (active/hibernated/deleted)
- `deployment_status`: Filter by deployment status

**Response**:
```json
{
  "projects": [
    {
      "id": "uuid",
      "name": "My App",
      "slug": "my-app-k3x8n2",
      "owner_id": "uuid",
      "owner_username": "johndoe",
      "status": "active",
      "created_at": "2025-01-05T10:00:00Z",
      "containers_count": 3,
      "deployment_status": "deployed"
    }
  ],
  "total": 3842,
  "page": 1,
  "page_size": 50,
  "total_pages": 77
}
```

### Hibernate Project

```
POST /api/admin/projects/{project_id}/hibernate
```

Hibernates a project (stops containers, preserves data).

**Request Body**:
```json
{
  "reason": "Resource optimization"
}
```

### Transfer Project

```
POST /api/admin/projects/{project_id}/transfer
```

Transfers project ownership to another user.

**Request Body**:
```json
{
  "new_owner_id": "uuid",
  "reason": "Account migration"
}
```

### Delete Project (Admin)

```
DELETE /api/admin/projects/{project_id}
```

Permanently deletes a project.

**Request Body**:
```json
{
  "reason": "DMCA takedown request"
}
```

## Billing Administration

### Get Billing Overview

```
GET /api/admin/billing/overview
```

Returns comprehensive billing statistics.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_revenue_cents": 125000,
  "subscription_revenue_cents": 80000,
  "credit_revenue_cents": 45000,
  "subscriptions_by_tier": {
    "free": 1200,
    "pro": 342
  },
  "daily_revenue": [
    {"date": "2025-01-01T00:00:00Z", "revenue_cents": 4200},
    {"date": "2025-01-02T00:00:00Z", "revenue_cents": 3800}
  ],
  "period_days": 30
}
```

### Get Credit Purchases

```
GET /api/admin/billing/purchases
```

Returns paginated list of credit purchases.

**Query Parameters**:
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 50)
- `start_date`: Filter from date
- `end_date`: Filter to date

**Response**:
```json
{
  "purchases": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "username": "johndoe",
      "amount_cents": 1000,
      "credits_purchased": 500,
      "created_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 420,
  "page": 1,
  "page_size": 50
}
```

### Get Creator Earnings

```
GET /api/admin/billing/creators
```

Returns paginated list of creator earnings.

**Query Parameters**:
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 50)

**Response**:
```json
{
  "creators": [
    {
      "user_id": "uuid",
      "username": "creator123",
      "total_earnings_cents": 5000,
      "pending_payout_cents": 2500,
      "agents_count": 3,
      "total_sales": 42
    }
  ],
  "total": 87,
  "page": 1,
  "page_size": 50
}
```

## Deployment Monitoring

### Get Deployment Stats

```
GET /api/admin/deployments/stats
```

Returns deployment statistics by provider.

**Query Parameters**:
- `days`: Period to analyze (default: 30)

**Response**:
```json
{
  "total_deployments": 234,
  "successful_deployments": 210,
  "failed_deployments": 24,
  "by_provider": {
    "vercel": {
      "total": 120,
      "successful": 115,
      "failed": 5,
      "success_rate": 95.8
    },
    "netlify": {
      "total": 80,
      "successful": 72,
      "failed": 8,
      "success_rate": 90.0
    },
    "cloudflare": {
      "total": 34,
      "successful": 23,
      "failed": 11,
      "success_rate": 67.6
    }
  },
  "daily_deployments": [
    {"date": "2025-01-01T00:00:00Z", "count": 12},
    {"date": "2025-01-02T00:00:00Z", "count": 15}
  ],
  "period_days": 30
}
```

### Get Deployments List

```
GET /api/admin/deployments
```

Returns paginated list of all deployments.

**Query Parameters**:
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 50)
- `provider`: Filter by provider (vercel/netlify/cloudflare)
- `status`: Filter by status (success/failed/pending)

**Response**:
```json
{
  "deployments": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "project_name": "My App",
      "owner_username": "johndoe",
      "provider": "vercel",
      "status": "success",
      "deployment_url": "https://my-app.vercel.app",
      "created_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 234,
  "page": 1,
  "page_size": 50
}
```

## Security

1. **Superuser Only**: All endpoints check `is_superuser = true`
2. **Audit Logging**: All admin actions logged with admin user ID
3. **Rate Limiting**: Admin endpoints rate-limited to prevent abuse
4. **Two-Factor Auth**: Recommended for admin accounts (future)
5. **IP Whitelisting**: Admin access restricted to specific IPs (optional)

## Example Workflows

### Moderating Marketplace Submission

1. **Creator submits agent**

2. **Admin views pending items**:
   ```
   GET /api/admin/marketplace/pending
   ```

3. **Admin reviews agent details**:
   - System prompt (check for inappropriate content)
   - Category (correct categorization)
   - Pricing (reasonable price)
   - Description (accurate and clear)

4. **Admin approves**:
   ```
   POST /api/admin/marketplace/agents/{id}/approve
   ```

5. **Agent published**, creator notified

### Handling User Support Issue

1. **User reports issue**: "My Pro subscription didn't activate after payment"

2. **Admin looks up user**:
   ```
   GET /api/admin/users?search=john@example.com
   ```

3. **Admin checks details**:
   ```
   GET /api/admin/users/{user_id}
   ```

4. **Admin sees**: Stripe payment succeeded but webhook failed

5. **Admin manually activates Pro**:
   ```
   PATCH /api/admin/users/{user_id}
   {"subscription_tier": "pro"}
   ```

6. **User's account updated**, issue resolved

### Monitoring Platform Health

1. **Admin checks system status**:
   ```
   GET /api/admin/system/status
   ```

2. **Sees**: High error rate in logs

3. **Admin checks error logs**:
   ```
   GET /api/admin/system/logs?level=error
   ```

4. **Identifies issue**: ImagePullBackOff errors for devserver image

5. **Admin investigates** and fixes K8s image pull secret

6. **Platform health restored**

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/users.py` - User authentication, superuser check
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - Database models
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/usage_service.py` - Usage tracking
