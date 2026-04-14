"""Change default visibility for marketplace_bases to private

Revision ID: 0010
Revises: 0009
Create Date: 2026-02-10

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_default_visibility_private"
down_revision = "0009_add_template_archive_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.alter_column("visibility", server_default="private")


def downgrade() -> None:
    with op.batch_alter_table("marketplace_bases") as batch_op:
        batch_op.alter_column("visibility", server_default="public")
