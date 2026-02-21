"""
Plan Manager for Tesslate Agent.

1:1 port of minimal-codex/plan_manager.py, adapted from filesystem to
in-memory storage (same pattern as todos.py). Plans are keyed by
"user_{id}_project_{id}" so they persist across agent iterations within
a single session but don't leak across projects.

All mutations are guarded by an asyncio.Lock to prevent concurrent
requests from corrupting shared state.
"""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Word list for generating plan names (1:1 from codex)
WORDS = [
    "swift",
    "brave",
    "calm",
    "dark",
    "eager",
    "fair",
    "gold",
    "happy",
    "iron",
    "jade",
    "keen",
    "lush",
    "mist",
    "noble",
    "oak",
    "pale",
    "quick",
    "rust",
    "sage",
    "true",
    "vast",
    "warm",
    "xenon",
    "young",
    "zeal",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
]


def _generate_plan_name() -> str:
    """Generate a plan name like swift_brave_calm (1:1 codex naming)."""
    words = random.sample(WORDS, 3)
    return "_".join(words)


@dataclass
class PlanStep:
    """A single step in a plan."""

    title: str
    status: str = "pending"  # pending | in_progress | completed


@dataclass
class Plan:
    """An implementation plan."""

    name: str
    task: str
    steps: list[PlanStep] = field(default_factory=list)
    critical_files: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_markdown(self) -> str:
        """Format plan as markdown with status symbols (1:1 codex: □ ▶ ✓)."""
        lines = [f"# Plan: {self.name.replace('_', ' ').title()}", ""]
        lines.append(f"## Task\n{self.task}")
        lines.append(f"\n## Created\n{self.created_at}")
        lines.append("\n## Steps\n")
        for i, step in enumerate(self.steps, 1):
            symbol = {"completed": "✓", "in_progress": "▶"}.get(step.status, "□")
            lines.append(f"{i}. [{symbol}] {step.title}")
        lines.append("\n## Critical Files\n")
        for f in self.critical_files:
            lines.append(f"- `{f}`")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize to dict for API responses."""
        return {
            "name": self.name,
            "task": self.task,
            "steps": [{"step": s.title, "status": s.status} for s in self.steps],
            "critical_files": self.critical_files,
            "created_at": self.created_at,
        }


# In-memory storage keyed by "user_{id}_project_{id}"
_plan_storage: dict[str, Plan] = {}
_plan_lock = asyncio.Lock()


def _storage_key(context: dict) -> str:
    """Build storage key from execution context."""
    user_id = context.get("user_id", "unknown")
    project_id = context.get("project_id", "unknown")
    return f"user_{user_id}_project_{project_id}"


class PlanManager:
    """Manages plans for autonomous planning mode.

    Plans are stored in-memory keyed by user+project. This matches the
    same pattern as todos.py — plans persist within an agent session
    but are scoped to a specific project.

    All mutations are async and guarded by _plan_lock.
    Read-only methods have sync variants for use in non-async contexts
    (e.g. building system prompts).
    """

    @staticmethod
    async def create_plan(
        context: dict,
        task: str,
        steps: list[dict],
        critical_files: list[str],
    ) -> Plan:
        """Create and store a new plan.

        Args:
            context: Execution context with user_id and project_id
            task: Original task description
            steps: List of {"step": str, "status": str}
            critical_files: File paths critical for implementation

        Returns:
            The created Plan
        """
        name = _generate_plan_name()
        plan = Plan(
            name=name,
            task=task,
            steps=[
                PlanStep(title=s.get("step", ""), status=s.get("status", "pending")) for s in steps
            ],
            critical_files=critical_files,
            created_at=datetime.now(UTC).isoformat(),
        )
        key = _storage_key(context)
        async with _plan_lock:
            _plan_storage[key] = plan
        return plan

    @staticmethod
    async def get_plan(context: dict) -> Plan | None:
        """Get the active plan for this context."""
        async with _plan_lock:
            return _plan_storage.get(_storage_key(context))

    @staticmethod
    def get_plan_sync(context: dict) -> Plan | None:
        """Get the active plan (non-async, for system prompt building).

        This is a snapshot read — acceptable without the lock because
        dict.get() is atomic in CPython and we only need a consistent
        reference, not a transaction.
        """
        return _plan_storage.get(_storage_key(context))

    @staticmethod
    async def update_step(
        context: dict,
        step_index: int,
        new_status: str,
    ) -> Plan | None:
        """Update a step's status in the active plan.

        Args:
            context: Execution context
            step_index: 0-indexed step number
            new_status: "pending", "in_progress", or "completed"

        Returns:
            Updated Plan, or None if no plan exists
        """
        async with _plan_lock:
            plan = _plan_storage.get(_storage_key(context))
            if plan and 0 <= step_index < len(plan.steps):
                plan.steps[step_index].status = new_status
            return plan

    @staticmethod
    async def update_plan(
        context: dict,
        steps: list[dict],
        explanation: str | None = None,
    ) -> Plan | None:
        """Replace the entire step list of the active plan.

        Args:
            context: Execution context
            steps: New list of {"step": str, "status": str}
            explanation: Optional reason for the update

        Returns:
            Updated Plan, or None if no plan exists
        """
        async with _plan_lock:
            plan = _plan_storage.get(_storage_key(context))
            if plan:
                plan.steps = [
                    PlanStep(title=s.get("step", ""), status=s.get("status", "pending"))
                    for s in steps
                ]
            return plan

    @staticmethod
    async def get_plan_context(context: dict) -> str | None:
        """Get plan content formatted for injection into system prompt.

        Returns the exact format codex uses:
        === ACTIVE PLAN ===
        ...
        === END PLAN ===
        """
        async with _plan_lock:
            plan = _plan_storage.get(_storage_key(context))
        if not plan:
            return None

        steps_text = []
        for i, step in enumerate(plan.steps, 1):
            symbol = {"completed": "✓", "in_progress": "▶"}.get(step.status, "□")
            steps_text.append(f"{i}. [{symbol}] {step.title}")

        files_text = "\n".join(f"- `{f}`" for f in plan.critical_files)

        return (
            f"=== ACTIVE PLAN ===\n"
            f"Task: {plan.task}\n\n"
            f"Steps:\n" + "\n".join(steps_text) + "\n\n"
            f"Critical Files:\n{files_text}\n"
            f"=== END PLAN ===\n\n"
            f"Continue executing from the current in_progress step. "
            f"Mark steps completed as you finish them using update_plan."
        )

    @staticmethod
    async def clear_plan(context: dict) -> None:
        """Remove the active plan for this context."""
        key = _storage_key(context)
        async with _plan_lock:
            _plan_storage.pop(key, None)
