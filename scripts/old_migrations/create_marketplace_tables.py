"""
Create marketplace tables migration script.

Run this script to add the new marketplace tables to your database.
"""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine, Base, AsyncSessionLocal
from app.models import (
    MarketplaceAgent, UserPurchasedAgent, ProjectAgent, AgentReview
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_marketplace_tables():
    """Create the new marketplace-related tables."""
    try:
        logger.info("Creating marketplace tables...")

        # Create all tables (will only create new ones, existing tables are not affected)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Marketplace tables created successfully!")
        return True
    except Exception as e:
        logger.error(f"Error creating marketplace tables: {e}")
        return False


async def seed_default_agents():
    """Seed the database with 6 default marketplace agents."""

    default_agents = [
        # Builder-style agents (stream mode)
        {
            "name": "Builder AI Pro",
            "slug": "builder-ai-pro",
            "description": "Advanced full-stack development with modern frameworks",
            "long_description": """Builder AI Pro is an advanced coding assistant that excels at full-stack web development.
            It can create complete applications using React, Vue, or Angular for the frontend, paired with Node.js, Python,
            or other backend technologies. This agent understands modern development patterns, can implement authentication,
            database design, API development, and follows best practices for scalable applications.""",
            "category": "builder",
            "mode": "stream",
            "icon": "🚀",
            "pricing_type": "passthrough",
            "price": 0,
            "source_type": "open",
            "requires_user_keys": True,
            "system_prompt": """You are an expert full-stack developer with deep knowledge of modern web technologies.
            You excel at building complete applications from scratch and can work with React, Vue, Angular, Node.js,
            Python, databases, and various APIs. Always follow best practices, write clean code, and consider scalability.""",
            "features": ["React/Vue/Angular", "Node.js/Python", "Database design", "API development", "Authentication", "Best practices"],
            "required_models": ["WEBGEN-SMALL", "cerebras/qwen-3-coder-480b"],
            "tags": ["fullstack", "web", "api", "react", "node", "python"],
            "is_featured": True
        },
        {
            "name": "Rapid Prototyper",
            "slug": "rapid-prototyper",
            "description": "Quick MVP and prototype builder for startups",
            "long_description": """The Rapid Prototyper specializes in building Minimum Viable Products (MVPs) and prototypes
            quickly and efficiently. Perfect for startups and entrepreneurs who need to validate ideas fast. This agent focuses
            on speed without sacrificing code quality, using modern tools and frameworks to deliver working prototypes in record time.""",
            "category": "builder",
            "mode": "stream",
            "icon": "⚡",
            "pricing_type": "monthly",
            "price": 1999,  # $19.99 in cents
            "source_type": "closed",
            "requires_user_keys": False,
            "system_prompt": """You specialize in rapid prototyping and MVP development. Focus on speed and functionality
            while maintaining clean, maintainable code. Use modern frameworks and tools that allow for quick iteration.
            Prioritize core features and suggest simple but effective solutions.""",
            "features": ["Fast iteration", "MVP focus", "Clean code", "Modern frameworks", "Startup-friendly", "Quick deployment"],
            "required_models": ["WEBGEN-SMALL", "UIGEN-FX-SMALL"],
            "tags": ["mvp", "startup", "rapid", "prototype", "agile"]
        },
        {
            "name": "Code Architect",
            "slug": "code-architect",
            "description": "Enterprise-grade application architecture and design",
            "long_description": """Code Architect is designed for building enterprise-level applications with robust architecture.
            This agent specializes in microservices, design patterns, scalability, and security. It can design complex systems,
            implement proper separation of concerns, and ensure your application can handle enterprise-scale demands.""",
            "category": "builder",
            "mode": "stream",
            "icon": "🏗️",
            "pricing_type": "monthly",
            "price": 4999,  # $49.99 in cents
            "system_prompt": """You are an enterprise software architect with expertise in designing large-scale applications.
            Focus on scalability, security, maintainability, and proper design patterns. Implement microservices architecture
            when appropriate, ensure proper separation of concerns, and follow SOLID principles.""",
            "features": ["Microservices", "Design patterns", "Scalability", "Security", "SOLID principles", "Enterprise patterns"],
            "required_models": ["cerebras/qwen-3-coder-480b"],
            "tags": ["enterprise", "architecture", "scalable", "microservices", "patterns"]
        },

        # Frontend/Fullstack agents (agent mode)
        {
            "name": "Frontend Master",
            "slug": "frontend-master",
            "description": "React, Vue, and modern UI development specialist",
            "long_description": """Frontend Master is your expert for all things frontend. Specializing in React, Vue, and
            modern JavaScript frameworks, this agent creates beautiful, responsive, and performant user interfaces. It understands
            component architecture, state management, and can implement complex UI interactions with smooth animations.""",
            "category": "frontend",
            "mode": "agent",
            "icon": "🎨",
            "pricing_type": "free",
            "price": 0,
            "system_prompt": """You are a frontend development specialist with expertise in React, Vue, and modern UI frameworks.
            Create beautiful, responsive, and accessible user interfaces. Focus on component architecture, state management,
            and performance optimization. Implement smooth animations and interactions.""",
            "features": ["React/Vue", "Tailwind CSS", "Animations", "Responsive design", "Component architecture", "State management"],
            "required_models": ["UIGEN-FX-SMALL", "WEBGEN-SMALL"],
            "tags": ["frontend", "ui", "react", "vue", "tailwind", "responsive"]
        },
        {
            "name": "Full Stack Developer",
            "slug": "fullstack-developer",
            "description": "Complete web application development from frontend to backend",
            "long_description": """The Full Stack Developer agent is a versatile coding assistant that can handle every aspect
            of web development. From creating stunning frontends to building robust backends, managing databases, and setting up
            DevOps pipelines. This agent ensures all parts of your application work seamlessly together.""",
            "category": "fullstack",
            "mode": "agent",
            "icon": "💻",
            "pricing_type": "monthly",
            "price": 2999,  # $29.99 in cents
            "system_prompt": """You are a full-stack developer capable of building complete web applications. Handle frontend
            development with modern frameworks, backend API development, database design and optimization, and basic DevOps tasks.
            Ensure proper integration between all layers of the application.""",
            "features": ["Frontend & Backend", "Database management", "API integration", "DevOps basics", "Testing", "Deployment"],
            "required_models": ["WEBGEN-SMALL", "cerebras/qwen-3-coder-480b"],
            "tags": ["fullstack", "complete", "endtoend", "web", "api", "database"]
        },
        {
            "name": "UI/UX Designer",
            "slug": "ui-ux-designer",
            "description": "Beautiful, functional interface design with user experience focus",
            "long_description": """The UI/UX Designer agent combines design thinking with development skills to create interfaces
            that are not just beautiful, but also highly functional and user-friendly. It understands design systems, accessibility
            standards, and can implement modern UI patterns that delight users while maintaining excellent usability.""",
            "category": "frontend",
            "mode": "agent",
            "icon": "✨",
            "pricing_type": "monthly",
            "price": 2499,  # $24.99 in cents
            "system_prompt": """You are a UI/UX designer and developer who creates beautiful, functional, and accessible interfaces.
            Focus on user experience, implement design systems, follow accessibility standards, and create intuitive interactions.
            Use modern CSS and animation techniques to enhance the user experience.""",
            "features": ["Design systems", "User experience", "Accessibility", "Modern UI", "Animations", "Responsive layouts"],
            "required_models": ["UIGEN-FX-SMALL"],
            "tags": ["design", "ux", "ui", "accessibility", "animations", "css"]
        }
    ]

    async with AsyncSessionLocal() as db:
        try:
            # Check if agents already exist
            from sqlalchemy import select
            result = await db.execute(select(MarketplaceAgent))
            existing_agents = result.scalars().all()

            if existing_agents:
                logger.info(f"Agents already seeded ({len(existing_agents)} agents found)")
                return True

            # Create agents
            for agent_data in default_agents:
                agent = MarketplaceAgent(**agent_data)
                db.add(agent)
                logger.info(f"  Created agent: {agent_data['name']} ({agent_data['slug']})")

            await db.commit()
            logger.info(f"Successfully seeded {len(default_agents)} marketplace agents!")
            return True

        except Exception as e:
            logger.error(f"Error seeding agents: {e}")
            await db.rollback()
            return False


async def main():
    """Main function to run the migration."""
    logger.info("Starting marketplace migration...")

    # Create tables
    success = await create_marketplace_tables()
    if not success:
        logger.error("Failed to create tables. Exiting.")
        return

    # Seed default agents
    success = await seed_default_agents()
    if not success:
        logger.error("Failed to seed agents, but tables were created successfully.")
        return

    logger.info("Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())