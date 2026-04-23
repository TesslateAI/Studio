# Marketplace Models

This document covers the models that power OpenSail's marketplace, where users can discover, purchase, and use AI agents, project templates, and workflow templates.

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

## MarketplaceAgent Model

The MarketplaceAgent model represents AI agents available in the marketplace. Agents can be free or paid, open-source or closed, and can be forked by users to create custom versions.

### Schema

```python
class MarketplaceAgent(Base):
    __tablename__ = "marketplace_agents"

    # Identity
    id: UUID                    # Primary key
    name: str                   # Display name: "Full-Stack Builder"
    slug: str                   # URL-safe identifier (unique)
    description: str            # Short description
    long_description: str       # Detailed description (Markdown)
    category: str               # builder, frontend, fullstack, data, etc.

    # Item type
    item_type: str              # agent, base, tool, integration (default: "agent")

    # Agent configuration
    system_prompt: str          # System prompt defining agent behavior
    mode: str                   # Deprecated: use agent_type instead
    agent_type: str             # StreamAgent, IterativeAgent, etc.
    tools: JSON                 # List of tool names: ["read_file", "write_file", ...]
    tool_configs: JSON          # Custom tool descriptions/prompts
    model: str                  # Specific model: "cerebras/llama3.1-8b"

    # Forking (open source agents)
    is_forkable: bool           # Can users fork this agent?
    parent_agent_id: UUID       # Parent agent (if forked)
    forked_by_user_id: UUID     # User who forked this agent
    created_by_user_id: UUID    # Agent creator (NULL = Tesslate-created)
    config: JSON                # Editable configuration for forked agents

    # Visual
    icon: str                   # Emoji or phosphor icon name
    avatar_url: str             # URL to logo/profile picture
    preview_image: str          # Screenshot/preview image

    # Pricing
    pricing_type: str           # free, monthly, api, one_time
    price: int                  # In cents (for monthly or one_time)
    api_pricing_input: float    # $ per million input tokens
    api_pricing_output: float   # $ per million output tokens
    stripe_price_id: str        # Stripe Price ID
    stripe_product_id: str      # Stripe Product ID

    # Source type
    source_type: str            # open, closed
    git_repo_url: str           # GitHub repo URL for open-source items (nullable, max 500 chars)
    requires_user_keys: bool    # For passthrough pricing (user brings API keys)

    # Stats
    downloads: int              # Number of installs
    rating: float               # Average rating (1-5)
    reviews_count: int          # Number of reviews
    usage_count: int            # Number of messages sent to this agent

    # Features & requirements
    features: JSON              # ["Code generation", "File editing", ...]
    required_models: JSON       # Models this agent needs access to
    tags: JSON                  # ["react", "typescript", "ai", ...]

    # Skill-specific field (item_type='skill')
    skill_body: str             # Full SKILL.md body after frontmatter (nullable, Text)

    # Status
    is_featured: bool           # Show on homepage
    is_active: bool             # Available for purchase
    is_published: bool          # For user-created forked agents

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Pricing Types

**free**: No charge to use
```python
pricing_type = "free"
price = 0
```

**monthly**: Monthly subscription
```python
pricing_type = "monthly"
price = 2000  # $20.00/month
stripe_subscription_id = "sub_xxx"
```

**api**: Pay-per-token usage (LiteLLM tracking)
```python
pricing_type = "api"
api_pricing_input = 0.50  # $0.50 per million input tokens
api_pricing_output = 1.50  # $1.50 per million output tokens
```

**one_time**: One-time purchase
```python
pricing_type = "one_time"
price = 4999  # $49.99
```

### Agent Types

- **StreamAgent**: Streaming responses with tool calls (default)
- **IterativeAgent**: Multi-iteration planning and execution
- **CodeAgent**: Specialized for code generation
- **DataAgent**: Specialized for data analysis

### Key Relationships

```python
# Forking hierarchy
parent_agent = relationship("MarketplaceAgent", remote_side=[id], foreign_keys=[parent_agent_id])
forked_by_user = relationship("User", foreign_keys=[forked_by_user_id])
created_by_user = relationship("User", foreign_keys=[created_by_user_id])

# Purchases and usage
purchased_by = relationship("UserPurchasedAgent", back_populates="agent")
project_assignments = relationship("ProjectAgent", back_populates="agent")
reviews = relationship("AgentReview", back_populates="agent")

# Skills attached to this agent (per user)
skill_assignments = relationship("AgentSkillAssignment", back_populates="agent")
```

### Common Queries

**Get all active agents**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .where(MarketplaceAgent.is_active == True)
    .where(MarketplaceAgent.is_published == True)
    .order_by(MarketplaceAgent.downloads.desc())
)
agents = result.scalars().all()
```

**Get featured agents**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .where(MarketplaceAgent.is_featured == True)
    .where(MarketplaceAgent.is_active == True)
)
featured = result.scalars().all()
```

**Get agents by category**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .where(MarketplaceAgent.category == "frontend")
    .where(MarketplaceAgent.is_active == True)
    .order_by(MarketplaceAgent.rating.desc())
)
frontend_agents = result.scalars().all()
```

**Get agent with reviews**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .options(selectinload(MarketplaceAgent.reviews))
    .where(MarketplaceAgent.slug == slug)
)
agent = result.scalar_one_or_none()
```

**Fork an agent**:
```python
# Create a fork
forked_agent = MarketplaceAgent(
    name=f"{original_agent.name} (Custom)",
    slug=f"{original_agent.slug}-fork-{user.slug}",
    description=original_agent.description,
    system_prompt=original_agent.system_prompt,
    agent_type=original_agent.agent_type,
    tools=original_agent.tools,
    is_forkable=False,  # Forks cannot be forked again
    parent_agent_id=original_agent.id,
    forked_by_user_id=user.id,
    pricing_type="free",  # User's own fork
    is_published=False,  # Private by default
    source_type="open"
)
db.add(forked_agent)
await db.commit()
```

**Track agent usage**:
```python
agent.usage_count += 1
await db.commit()
```

### Notes

- Agents can be forked if `is_forkable=True` and `source_type="open"`
- API pricing agents require LiteLLM integration for token tracking
- The `config` field allows forked agents to have user-customizable settings
- Agent creators receive 90% of revenue (10% platform fee)

---

## UserPurchasedAgent Model

Tracks which agents users have purchased or added to their library.

### Schema

```python
class UserPurchasedAgent(Base):
    __tablename__ = "user_purchased_agents"

    # Identity
    id: UUID
    user_id: UUID               # Foreign key to User
    agent_id: UUID              # Foreign key to MarketplaceAgent

    # Purchase details
    purchase_date: datetime     # When agent was acquired
    purchase_type: str          # free, purchased, subscription
    stripe_payment_intent: str  # For one-time purchases
    stripe_subscription_id: str # For subscriptions
    expires_at: datetime        # For subscriptions (renewal date)
    is_active: bool             # Is subscription active?

    # User preferences
    selected_model: str         # User's model override for open source agents
```

### Key Relationships

```python
user = relationship("User", back_populates="purchased_agents")
agent = relationship("MarketplaceAgent", back_populates="purchased_by")
```

### Common Queries

**Get user's agent library**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .join(UserPurchasedAgent)
    .where(UserPurchasedAgent.user_id == user.id)
    .where(UserPurchasedAgent.is_active == True)
)
agents = result.scalars().all()
```

**Check if user owns an agent**:
```python
result = await db.execute(
    select(UserPurchasedAgent)
    .where(UserPurchasedAgent.user_id == user.id)
    .where(UserPurchasedAgent.agent_id == agent.id)
    .where(UserPurchasedAgent.is_active == True)
)
purchase = result.scalar_one_or_none()

if purchase:
    # User owns this agent
    pass
```

**Add free agent to library**:
```python
purchase = UserPurchasedAgent(
    user_id=user.id,
    agent_id=agent.id,
    purchase_type="free",
    is_active=True
)
db.add(purchase)
await db.commit()
```

**Add paid agent (one-time)**:
```python
purchase = UserPurchasedAgent(
    user_id=user.id,
    agent_id=agent.id,
    purchase_type="purchased",
    stripe_payment_intent=payment_intent.id,
    is_active=True
)
db.add(purchase)
await db.commit()
```

**Add subscription agent**:
```python
purchase = UserPurchasedAgent(
    user_id=user.id,
    agent_id=agent.id,
    purchase_type="subscription",
    stripe_subscription_id=subscription.id,
    expires_at=subscription.current_period_end,
    is_active=True
)
db.add(purchase)
await db.commit()
```

**Cancel subscription**:
```python
purchase.is_active = False
await db.commit()
```

---

## ProjectAgent Model

Assigns agents to specific projects, enabling project-scoped agent usage.

### Schema

```python
class ProjectAgent(Base):
    __tablename__ = "project_agents"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project
    agent_id: UUID              # Foreign key to MarketplaceAgent
    user_id: UUID               # Foreign key to User (for validation)

    # Status
    enabled: bool               # Is agent active on this project?
    added_at: datetime          # When agent was added
```

### Key Relationships

```python
project = relationship("Project", back_populates="project_agents")
agent = relationship("MarketplaceAgent", back_populates="project_assignments")
```

### Common Queries

**Get agents assigned to a project**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .join(ProjectAgent)
    .where(ProjectAgent.project_id == project.id)
    .where(ProjectAgent.enabled == True)
)
agents = result.scalars().all()
```

**Assign agent to project**:
```python
# First, verify user owns the agent
purchase = await db.execute(
    select(UserPurchasedAgent)
    .where(UserPurchasedAgent.user_id == user.id)
    .where(UserPurchasedAgent.agent_id == agent.id)
    .where(UserPurchasedAgent.is_active == True)
)
if not purchase.scalar_one_or_none():
    raise ValueError("User does not own this agent")

# Assign to project
assignment = ProjectAgent(
    project_id=project.id,
    agent_id=agent.id,
    user_id=user.id,
    enabled=True
)
db.add(assignment)
await db.commit()
```

**Disable agent on project**:
```python
assignment.enabled = False
await db.commit()
```

---

## AgentReview Model

User reviews and ratings for marketplace agents.

### Schema

```python
class AgentReview(Base):
    __tablename__ = "agent_reviews"

    # Identity
    id: UUID
    agent_id: UUID              # Foreign key to MarketplaceAgent
    user_id: UUID               # Foreign key to User

    # Review content
    rating: int                 # 1-5 stars
    comment: str                # Optional text review

    # Timestamp
    created_at: datetime
```

### Key Relationships

```python
agent = relationship("MarketplaceAgent", back_populates="reviews")
user = relationship("User", back_populates="agent_reviews")
```

### Common Queries

**Get reviews for an agent**:
```python
result = await db.execute(
    select(AgentReview)
    .options(selectinload(AgentReview.user))
    .where(AgentReview.agent_id == agent.id)
    .order_by(AgentReview.created_at.desc())
)
reviews = result.scalars().all()
```

**Add a review**:
```python
review = AgentReview(
    agent_id=agent.id,
    user_id=user.id,
    rating=5,
    comment="This agent is amazing! Saved me hours of work."
)
db.add(review)
await db.commit()

# Update agent rating and review count
agent.reviews_count += 1
agent.rating = await calculate_average_rating(agent.id)
await db.commit()
```

**Calculate average rating**:
```python
from sqlalchemy import func

result = await db.execute(
    select(func.avg(AgentReview.rating))
    .where(AgentReview.agent_id == agent.id)
)
average_rating = result.scalar() or 5.0
```

---

## MarketplaceBase Model

Project templates (React, FastAPI, Next.js, etc.) available in the marketplace.

### Schema

```python
class MarketplaceBase(Base):
    __tablename__ = "marketplace_bases"

    # Identity
    id: UUID
    name: str                   # "Next.js Starter"
    slug: str                   # "nextjs-starter" (unique)
    description: str            # Short description
    long_description: str       # Detailed description (Markdown)

    # Git repository for template
    git_repo_url: str           # GitHub repo URL
    default_branch: str         # "main"

    # Metadata
    category: str               # fullstack, frontend, backend, mobile
    icon: str                   # Emoji
    preview_image: str          # Screenshot
    tags: JSON                  # ["vite", "react", "fastapi", "python"]

    # Pricing
    pricing_type: str           # free, one_time, monthly
    price: int                  # In cents
    stripe_price_id: str
    stripe_product_id: str

    # Stats
    downloads: int
    rating: float
    reviews_count: int

    # Features
    features: JSON              # ["Hot reload", "API ready", "Database setup"]
    tech_stack: JSON            # ["React", "FastAPI", "PostgreSQL"]

    # User-submitted bases
    created_by_user_id: UUID    # FK → users.id, nullable (NULL = Tesslate-seeded base)
    visibility: str             # "private" or "public" (default "public")

    # Status
    is_featured: bool
    is_active: bool

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
purchased_by = relationship("UserPurchasedBase", back_populates="base")
reviews = relationship("BaseReview", back_populates="base")
created_by_user = relationship("User", foreign_keys=[created_by_user_id])
```

### Common Queries

**Get all public bases** (marketplace browse):
```python
from sqlalchemy import or_

result = await db.execute(
    select(MarketplaceBase)
    .where(
        MarketplaceBase.is_active == True,
        or_(
            MarketplaceBase.created_by_user_id.is_(None),  # seeded bases
            MarketplaceBase.visibility == "public"           # public user bases
        )
    )
    .order_by(MarketplaceBase.downloads.desc())
)
bases = result.scalars().all()
```

**Get bases by category**:
```python
result = await db.execute(
    select(MarketplaceBase)
    .where(MarketplaceBase.category == "fullstack")
    .where(MarketplaceBase.is_active == True)
)
fullstack_bases = result.scalars().all()
```

**Get user's created bases**:
```python
result = await db.execute(
    select(MarketplaceBase)
    .where(MarketplaceBase.created_by_user_id == user.id)
    .order_by(MarketplaceBase.created_at.desc())
)
my_bases = result.scalars().all()
```

---

## UserPurchasedBase Model

Tracks which project templates users have acquired.

### Schema

```python
class UserPurchasedBase(Base):
    __tablename__ = "user_purchased_bases"

    # Identity
    id: UUID
    user_id: UUID
    base_id: UUID

    # Purchase details
    purchase_date: datetime
    purchase_type: str          # free, purchased, subscription
    stripe_payment_intent: str
    is_active: bool
```

### Key Relationships

```python
user = relationship("User", back_populates="purchased_bases")
base = relationship("MarketplaceBase", back_populates="purchased_by")
```

---

## BaseReview Model

User reviews for marketplace bases (same structure as AgentReview).

### Schema

```python
class BaseReview(Base):
    __tablename__ = "base_reviews"

    id: UUID
    base_id: UUID
    user_id: UUID
    rating: int                 # 1-5
    comment: str
    created_at: datetime
```

---

## WorkflowTemplate Model

Pre-configured multi-container workflows that users can drag onto their canvas.

### Schema

```python
class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    # Identity
    id: UUID
    name: str                   # "Next.js + Supabase Starter"
    slug: str                   # "nextjs-supabase" (unique)
    description: str
    long_description: str

    # Visual
    icon: str
    preview_image: str

    # Categorization
    category: str               # fullstack, backend, frontend, data-pipeline, ai-app
    tags: JSON                  # ["nextjs", "supabase", "auth"]

    # Template definition (JSON)
    template_definition: JSON   # Defines nodes and connections
    required_credentials: JSON  # ["supabase"]

    # Pricing
    pricing_type: str           # free, one_time, monthly
    price: int
    stripe_price_id: str
    stripe_product_id: str

    # Stats
    downloads: int
    rating: float
    reviews_count: int

    # Status
    is_featured: bool
    is_active: bool

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Template Definition Structure

```json
{
  "nodes": [
    {
      "template_id": "frontend",
      "type": "base",
      "base_slug": "nextjs",
      "name": "Frontend",
      "position": {"x": 0, "y": 100}
    },
    {
      "template_id": "database",
      "type": "service",
      "service_slug": "supabase",
      "name": "Database",
      "position": {"x": 300, "y": 100},
      "deployment_mode": "external"
    }
  ],
  "edges": [
    {
      "source": "frontend",
      "target": "database",
      "connector_type": "env_injection",
      "config": {
        "env_mapping": {
          "NEXT_PUBLIC_SUPABASE_URL": "SUPABASE_URL",
          "NEXT_PUBLIC_SUPABASE_ANON_KEY": "SUPABASE_ANON_KEY"
        }
      }
    }
  ],
  "required_credentials": ["supabase"]
}
```

### Common Queries

**Get all workflow templates**:
```python
result = await db.execute(
    select(WorkflowTemplate)
    .where(WorkflowTemplate.is_active == True)
    .order_by(WorkflowTemplate.downloads.desc())
)
templates = result.scalars().all()
```

**Apply workflow to project**:
```python
workflow = await get_workflow_by_slug(slug)
template_def = workflow.template_definition

# Create containers from template nodes
for node in template_def["nodes"]:
    container = Container(
        project_id=project.id,
        name=node["name"],
        position_x=node["position"]["x"],
        position_y=node["position"]["y"],
        # ... other fields from node
    )
    db.add(container)

# Create connections from template edges
for edge in template_def["edges"]:
    source = await get_container_by_template_id(edge["source"])
    target = await get_container_by_template_id(edge["target"])

    connection = ContainerConnection(
        project_id=project.id,
        source_container_id=source.id,
        target_container_id=target.id,
        connector_type=edge["connector_type"],
        config=edge["config"]
    )
    db.add(connection)

await db.commit()
```

---

## AgentCoInstall Model

Tracks co-installation patterns for smart recommendations ("People also installed").

### Schema

```python
class AgentCoInstall(Base):
    __tablename__ = "agent_co_installs"

    # Identity
    id: UUID
    agent_id: UUID              # Primary agent
    related_agent_id: UUID      # Related agent

    # Statistics
    co_install_count: int       # Number of users who have both

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Unique constraint
    __table_args__ = (
        UniqueConstraint('agent_id', 'related_agent_id', name='uq_agent_co_install_pair'),
    )
```

### How It Works

When a user installs an agent:
1. Query all other agents the user has installed
2. For each other agent, increment `co_install_count` for the pair
3. Background task (non-blocking)

```python
async def update_co_install_stats(user_id: UUID, new_agent_id: UUID):
    # Get all other agents user has
    result = await db.execute(
        select(UserPurchasedAgent.agent_id)
        .where(UserPurchasedAgent.user_id == user_id)
        .where(UserPurchasedAgent.agent_id != new_agent_id)
    )
    other_agent_ids = result.scalars().all()

    # Update co-install counts
    for other_agent_id in other_agent_ids:
        # Find or create co-install record
        result = await db.execute(
            select(AgentCoInstall)
            .where(AgentCoInstall.agent_id == new_agent_id)
            .where(AgentCoInstall.related_agent_id == other_agent_id)
        )
        record = result.scalar_one_or_none()

        if record:
            record.co_install_count += 1
        else:
            record = AgentCoInstall(
                agent_id=new_agent_id,
                related_agent_id=other_agent_id,
                co_install_count=1
            )
            db.add(record)

    await db.commit()
```

### Common Queries

**Get recommended agents**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .join(
        AgentCoInstall,
        AgentCoInstall.related_agent_id == MarketplaceAgent.id
    )
    .where(AgentCoInstall.agent_id == current_agent_id)
    .order_by(AgentCoInstall.co_install_count.desc())
    .limit(5)
)
recommendations = result.scalars().all()
```

---

## AgentSkillAssignment Model

Tracks which skills (marketplace agents with `item_type='skill'`) are attached to which agents, per user. This is a three-way junction table enabling users to customize their agents with reusable skill modules.

### Schema

```python
class AgentSkillAssignment(Base):
    __tablename__ = "agent_skill_assignments"

    # Identity
    id: UUID
    agent_id: UUID              # Foreign key to MarketplaceAgent (the agent)
    skill_id: UUID              # Foreign key to MarketplaceAgent (the skill, item_type='skill')
    user_id: UUID               # Foreign key to User

    # Status
    enabled: bool               # Is this skill active on the agent?
    added_at: datetime          # When the skill was attached

    # Unique constraint: (agent_id, skill_id, user_id)
```

### Key Relationships

```python
agent = relationship("MarketplaceAgent", back_populates="skill_assignments", foreign_keys=[agent_id])
skill = relationship("MarketplaceAgent", foreign_keys=[skill_id])
user = relationship("User")
```

### Common Queries

**Get skills attached to an agent for a user**:
```python
result = await db.execute(
    select(MarketplaceAgent)
    .join(AgentSkillAssignment, AgentSkillAssignment.skill_id == MarketplaceAgent.id)
    .where(AgentSkillAssignment.agent_id == agent_id)
    .where(AgentSkillAssignment.user_id == user.id)
    .where(AgentSkillAssignment.enabled == True)
)
skills = result.scalars().all()
```

**Attach a skill to an agent**:
```python
assignment = AgentSkillAssignment(
    agent_id=agent.id,
    skill_id=skill.id,
    user_id=user.id,
    enabled=True
)
db.add(assignment)
await db.commit()
```

**Detach a skill from an agent**:
```python
await db.execute(
    delete(AgentSkillAssignment)
    .where(AgentSkillAssignment.agent_id == agent_id)
    .where(AgentSkillAssignment.skill_id == skill_id)
    .where(AgentSkillAssignment.user_id == user_id)
)
await db.commit()
```

### Notes

- Both `agent_id` and `skill_id` reference `marketplace_agents.id` — skills are stored as MarketplaceAgent rows with `item_type='skill'`
- The `skill_body` field on MarketplaceAgent holds the full SKILL.md content for skill-type items
- The unique constraint on `(agent_id, skill_id, user_id)` prevents duplicate attachments
- CASCADE deletes: removing the agent, skill, or user automatically cleans up assignments

---

## Summary

The marketplace models enable a rich ecosystem where users can:

- **Discover** agents and templates through categories, tags, and search
- **Purchase** agents with various pricing models (free, monthly, API, one-time)
- **Fork** open-source agents to create custom versions
- **Attach skills** to agents for per-user customization
- **Review** agents and templates to help others
- **Assign** agents to specific projects
- **Install** workflow templates for rapid project setup
- **Get recommendations** based on co-installation patterns

Key revenue flows:
- One-time agent purchases → 90% to creator, 10% to platform
- Monthly subscriptions → 90% to creator, 10% to platform
- API usage pricing → 90% to creator, 10% to platform

The marketplace is fully integrated with Stripe for payments and LiteLLM for usage tracking.
