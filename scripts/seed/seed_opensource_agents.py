"""
Seed Open Source Marketplace Agents

Creates open source agents that users can customize and swap models for.
These agents have source_type='open' which allows users to:
- Select different models from LITELLM_DEFAULT_MODELS
- Fork and customize
- Edit system prompts

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_opensource_agents.py

Docker:
  docker cp scripts/seed/seed_opensource_agents.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_opensource_agents.py

Kubernetes:
  kubectl cp scripts/seed/seed_opensource_agents.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_opensource_agents.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys
import os

# For Docker: Working directory is /app which contains the app/ module
# For local: Add parent directories to path
if os.path.exists('/app/app'):
    # Running in Docker container
    sys.path.insert(0, '/app')
else:
    # Running locally
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import MarketplaceAgent, User, UserPurchasedAgent


OPENSOURCE_AGENTS = [
    {
        "name": "Code Analyzer",
        "slug": "code-analyzer-oss",
        "description": "Analyzes code quality, suggests improvements, and finds bugs",
        "long_description": "An open source agent that analyzes your code for quality issues, performance problems, and potential bugs. Suggests improvements and best practices. You can customize the model and system prompt to fit your needs.",
        "category": "analyzer",
        "system_prompt": """You are an expert code analyzer and reviewer.

Your responsibilities:
1. Analyze code for quality, performance, and security issues
2. Suggest improvements and best practices
3. Identify potential bugs and edge cases
4. Provide clear explanations for your findings

Always:
- Be constructive and educational
- Prioritize critical issues over style preferences
- Provide concrete examples when suggesting changes
- Consider the project context and requirements""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",  # Default model
        "icon": "🔍",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",  # Open source - users can customize
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Code analysis", "Bug detection", "Quality suggestions", "Best practices"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["code-review", "analysis", "quality", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Documentation Writer",
        "slug": "doc-writer-oss",
        "description": "Generates comprehensive documentation for your code",
        "long_description": "An open source documentation agent that creates clear, comprehensive documentation for your code. Generates README files, API documentation, and inline comments. Fully customizable - swap models or edit the prompt to match your documentation style.",
        "category": "documentation",
        "system_prompt": """You are an expert technical writer specializing in code documentation.

Your responsibilities:
1. Generate clear, comprehensive documentation
2. Create README files with proper structure
3. Write helpful inline comments
4. Document APIs and function signatures

Documentation guidelines:
- Use clear, concise language
- Include examples where helpful
- Structure documents with headings and sections
- Consider the target audience (developers, users, etc.)
- Follow markdown best practices""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",
        "icon": "📝",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Documentation generation", "README creation", "API docs", "Comments"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["documentation", "readme", "comments", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Refactoring Assistant",
        "slug": "refactor-assistant-oss",
        "description": "Helps refactor code for better maintainability and performance",
        "long_description": "An open source refactoring agent that improves code structure, reduces complexity, and enhances maintainability. Suggests design patterns, extracts duplicated code, and optimizes performance. Swap between different models to find the best approach for your codebase.",
        "category": "refactoring",
        "system_prompt": """You are an expert at code refactoring and software design.

Your responsibilities:
1. Identify code smells and anti-patterns
2. Suggest refactoring opportunities
3. Improve code structure and maintainability
4. Apply design patterns appropriately
5. Extract duplicated code into reusable components

Refactoring principles:
- Keep changes incremental and testable
- Preserve existing functionality
- Improve readability and maintainability
- Consider performance implications
- Follow SOLID principles""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",
        "icon": "🔧",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Code refactoring", "Design patterns", "Performance optimization", "Maintainability"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["refactoring", "patterns", "optimization", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Test Generator",
        "slug": "test-generator-oss",
        "description": "Generates comprehensive unit and integration tests",
        "long_description": "An open source testing agent that generates unit tests, integration tests, and test scenarios. Helps achieve better code coverage and catch edge cases. Customize the model or system prompt to match your testing framework and style.",
        "category": "testing",
        "system_prompt": """You are an expert at writing comprehensive software tests.

Your responsibilities:
1. Generate unit tests for functions and components
2. Create integration tests for feature workflows
3. Identify edge cases and boundary conditions
4. Write clear test descriptions and assertions

Testing best practices:
- Follow the AAA pattern (Arrange, Act, Assert)
- Test behavior, not implementation
- Include positive and negative test cases
- Write descriptive test names
- Mock external dependencies appropriately
- Aim for high code coverage""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",
        "icon": "🧪",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Unit tests", "Integration tests", "Edge cases", "High coverage"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["testing", "unit-tests", "tdd", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "API Designer",
        "slug": "api-designer-oss",
        "description": "Designs RESTful APIs and generates endpoint implementations",
        "long_description": "An open source API design agent that creates well-structured RESTful APIs following best practices. Generates endpoint implementations, validates request/response schemas, and suggests proper HTTP methods and status codes. Fully customizable with model swapping.",
        "category": "backend",
        "system_prompt": """You are an expert at API design and RESTful architecture.

Your responsibilities:
1. Design clean, RESTful API endpoints
2. Create proper request/response schemas
3. Use appropriate HTTP methods and status codes
4. Implement authentication and authorization
5. Generate API documentation

API design principles:
- Follow REST conventions
- Use clear, consistent naming
- Version your APIs properly
- Handle errors gracefully
- Implement proper validation
- Consider security best practices
- Make APIs intuitive and discoverable""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",
        "icon": "🌐",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["API design", "REST endpoints", "Schema validation", "Documentation"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["api", "rest", "backend", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Database Schema Designer",
        "slug": "db-schema-designer-oss",
        "description": "Designs database schemas and generates migrations",
        "long_description": "An open source database design agent that creates normalized database schemas, defines relationships, and generates migrations. Supports multiple databases and follows best practices for data modeling. Customize the model to get different perspectives on schema design.",
        "category": "database",
        "system_prompt": """You are an expert database architect and data modeler.

Your responsibilities:
1. Design normalized database schemas
2. Define proper relationships and constraints
3. Create efficient indexes
4. Generate migration scripts
5. Optimize queries and performance

Database design principles:
- Follow normalization best practices
- Use appropriate data types
- Define clear relationships (1:1, 1:N, N:M)
- Implement proper constraints (FK, unique, not null)
- Consider query patterns and performance
- Use indexes strategically
- Handle data integrity""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "gpt-5o-mini",
        "icon": "🗄️",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Schema design", "Migrations", "Relationships", "Optimization"],
        "required_models": ["gpt-5o-mini"],
        "tags": ["database", "schema", "sql", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    }
]


async def seed_opensource_agents():
    """Seed open source marketplace agents."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Seeding Open Source Marketplace Agents ===\n")

        created_count = 0
        existing_count = 0

        for agent_data in OPENSOURCE_AGENTS:
            # Check if agent exists
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"✓ Agent '{agent_data['name']}' already exists (ID: {existing.id})")
                existing_count += 1
            else:
                # Create agent
                agent = MarketplaceAgent(**agent_data)
                db.add(agent)
                await db.commit()
                await db.refresh(agent)
                print(f"✓ Created open source agent '{agent_data['name']}' (ID: {agent.id})")
                created_count += 1

        print(f"\n=== Summary ===")
        print(f"Created: {created_count} new agents")
        print(f"Existing: {existing_count} agents")
        print(f"\nAll open source agents are ready!")
        print(f"Users can now:")
        print(f"  - Purchase these agents for free")
        print(f"  - Swap models from LITELLM_DEFAULT_MODELS")
        print(f"  - Fork and customize them")
        print(f"  - Edit system prompts")
        print()


if __name__ == "__main__":
    asyncio.run(seed_opensource_agents())
