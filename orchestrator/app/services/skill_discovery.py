"""
Skill Discovery Service

Discovers available skills from three sources:
1. Built-in skills — seeded with ``is_builtin=True`` and auto-available to every
   agent regardless of AgentSkillAssignment state (e.g. the project-architecture
   reference skill). Body contains live markers resolved by skill_markers.
2. Database (MarketplaceAgent with item_type='skill', attached via AgentSkillAssignment)
3. Project files (.agents/skills/SKILL.md in the user's container)

Only loads name + description for progressive disclosure.
Full skill body is loaded on-demand by the load_skill tool.
"""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class SkillCatalogEntry:
    """Lightweight skill entry for progressive disclosure catalog."""
    name: str
    description: str
    source: str  # "builtin" | "db" | "file"
    skill_id: UUID | None = None
    file_path: str | None = None
    is_builtin: bool = False


async def discover_skills(
    agent_id: UUID | None,
    user_id: UUID,
    project_id: str | None,
    container_name: str | None,
    db: AsyncSession,
) -> list[SkillCatalogEntry]:
    """
    Discover available skills from all sources.

    Args:
        agent_id: ID of the active marketplace agent
        user_id: Current user ID
        project_id: Current project ID
        container_name: Container name for file-based skill discovery
        db: Database session

    Returns:
        List of SkillCatalogEntry (name + description only, no body)
    """
    skills: list[SkillCatalogEntry] = []
    seen_ids: set[UUID] = set()

    # Source A (priority): built-in skills — always available to every agent.
    builtin_skills = await _discover_builtin_skills(db)
    for s in builtin_skills:
        skills.append(s)
        if s.skill_id is not None:
            seen_ids.add(s.skill_id)

    # Source B: DB skills attached to this agent via AgentSkillAssignment.
    # De-dupe against built-ins — a user who explicitly installed a built-in
    # appears in both sources; show it once (with the built-in marker).
    if agent_id:
        db_skills = await _discover_db_skills(agent_id, user_id, db)
        for s in db_skills:
            if s.skill_id is not None and s.skill_id in seen_ids:
                continue
            skills.append(s)

    # Source C: Project file-based skills from container
    if container_name and project_id:
        file_skills = await _discover_file_skills(user_id, project_id, container_name)
        skills.extend(file_skills)

    if skills:
        logger.info(
            f"Discovered {len(skills)} skills "
            f"({sum(1 for s in skills if s.source == 'builtin')} built-in, "
            f"{sum(1 for s in skills if s.source == 'db')} DB, "
            f"{sum(1 for s in skills if s.source == 'file')} file)"
        )

    return skills


async def _discover_builtin_skills(db: AsyncSession) -> list[SkillCatalogEntry]:
    """Discover every skill seeded with ``is_builtin=True``.

    Safe by construction: the column is only written by ``seeds/skills.py``.
    No user-facing Pydantic request schema exposes the field, so user payloads
    can't flip it, and mutation endpoints reject attempts to edit built-in
    rows via ``_reject_if_builtin``.
    """
    try:
        from ..models import MarketplaceAgent

        result = await db.execute(
            select(
                MarketplaceAgent.id,
                MarketplaceAgent.name,
                MarketplaceAgent.description,
            ).where(
                MarketplaceAgent.is_builtin.is_(True),
                MarketplaceAgent.is_active.is_(True),
                MarketplaceAgent.item_type == "skill",
            )
        )
        rows = result.all()
        return [
            SkillCatalogEntry(
                name=row.name,
                description=row.description,
                source="builtin",
                skill_id=row.id,
                is_builtin=True,
            )
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Failed to discover built-in skills: {e}")
        return []


async def _discover_db_skills(
    agent_id: UUID, user_id: UUID, db: AsyncSession
) -> list[SkillCatalogEntry]:
    """Discover skills attached to this agent via AgentSkillAssignment."""
    try:
        from ..models import AgentSkillAssignment, MarketplaceAgent

        result = await db.execute(
            select(MarketplaceAgent.id, MarketplaceAgent.name, MarketplaceAgent.description)
            .join(
                AgentSkillAssignment,
                AgentSkillAssignment.skill_id == MarketplaceAgent.id,
            )
            .where(
                AgentSkillAssignment.agent_id == agent_id,
                AgentSkillAssignment.user_id == user_id,
                AgentSkillAssignment.enabled.is_(True),
                MarketplaceAgent.is_active.is_(True),
                MarketplaceAgent.item_type == "skill",
            )
        )
        rows = result.all()

        return [
            SkillCatalogEntry(
                name=row.name,
                description=row.description,
                source="db",
                skill_id=row.id,
            )
            for row in rows
        ]

    except Exception as e:
        logger.warning(f"Failed to discover DB skills: {e}")
        return []


async def _discover_file_skills(
    user_id: UUID, project_id: str, container_name: str
) -> list[SkillCatalogEntry]:
    """Discover SKILL.md files in the project's .agents/skills/ directory."""
    from ..utils.resource_naming import get_container_name
    from .orchestration import is_kubernetes_mode

    try:
        # Find SKILL.md files in the container
        if is_kubernetes_mode():
            pod_name = get_container_name(user_id, project_id, mode="kubernetes")
            namespace = "tesslate-user-environments"
            cmd = f"kubectl exec -n {namespace} {pod_name} -- find /app/.agents/skills -name SKILL.md -maxdepth 4 2>/dev/null"
        else:
            docker_container = get_container_name(user_id, project_id, mode="docker")
            cmd = f"docker exec {docker_container} find /app/.agents/skills -name SKILL.md -maxdepth 4 2>/dev/null"

        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0 or not stdout.strip():
            return []

        skill_paths = stdout.decode("utf-8").strip().split("\n")
        skills = []

        for path in skill_paths:
            path = path.strip()
            if not path:
                continue

            entry = await _parse_skill_frontmatter(user_id, project_id, path)
            if entry:
                skills.append(entry)

        return skills

    except Exception as e:
        logger.debug(f"Failed to discover file-based skills: {e}")
        return []


async def _parse_skill_frontmatter(
    user_id: UUID, project_id: str, file_path: str
) -> SkillCatalogEntry | None:
    """Parse only the YAML frontmatter from a SKILL.md file (name + description)."""
    import shlex

    from ..utils.resource_naming import get_container_name
    from .orchestration import is_kubernetes_mode

    try:
        safe_path = shlex.quote(file_path)

        # Read just the frontmatter (first --- to second ---)
        if is_kubernetes_mode():
            pod_name = get_container_name(user_id, project_id, mode="kubernetes")
            namespace = "tesslate-user-environments"
            cmd = f"kubectl exec -n {namespace} {pod_name} -- head -20 {safe_path}"
        else:
            docker_container = get_container_name(user_id, project_id, mode="docker")
            cmd = f"docker exec {docker_container} head -20 {safe_path}"

        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return None

        content = stdout.decode("utf-8")

        # Parse YAML frontmatter
        if not content.startswith("---"):
            return None

        end_marker = content.find("---", 3)
        if end_marker == -1:
            return None

        frontmatter_str = content[3:end_marker].strip()
        frontmatter = yaml.safe_load(frontmatter_str)

        if not frontmatter or not isinstance(frontmatter, dict):
            return None

        name = frontmatter.get("name")
        description = frontmatter.get("description", "")

        if not name:
            return None

        return SkillCatalogEntry(
            name=name,
            description=description,
            source="file",
            file_path=file_path,
        )

    except Exception as e:
        logger.debug(f"Failed to parse skill frontmatter from {file_path}: {e}")
        return None
