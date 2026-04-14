"""Update user_library_themes unique constraint to include team_id

The old constraint (user_id, theme_id) prevents the same theme from
being installed under different teams for the same user. The new
constraint (user_id, theme_id, team_id) allows per-team theme installs.

Revision ID: 0040_theme_team_constraint
Revises: 0039_kanban_task_ref
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040_theme_team_constraint"
down_revision: str | Sequence[str] | None = "0039_kanban_task_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_library_themes") as batch_op:
        batch_op.drop_constraint("uq_user_library_theme", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_library_theme_team",
            ["user_id", "theme_id", "team_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("user_library_themes") as batch_op:
        batch_op.drop_constraint("uq_user_library_theme_team", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_library_theme",
            ["user_id", "theme_id"],
        )
