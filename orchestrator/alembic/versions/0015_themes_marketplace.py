"""Add marketplace fields to themes + user_library_themes table

Revision ID: 0015_themes_marketplace
Revises: 0014_pricing_overhaul
Create Date: 2026-02-22

"""

import sqlalchemy as sa
from alembic import op
from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0015_themes_marketplace"
down_revision = "0014_pricing_overhaul"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add marketplace columns to themes table ---
    op.add_column("themes", sa.Column("slug", sa.String(200), nullable=True))
    op.add_column("themes", sa.Column("long_description", sa.Text(), nullable=True))
    op.add_column(
        "themes", sa.Column("icon", sa.String(50), server_default="palette", nullable=True)
    )
    op.add_column("themes", sa.Column("preview_image", sa.String(), nullable=True))
    op.add_column(
        "themes", sa.Column("pricing_type", sa.String(20), server_default="free", nullable=True)
    )
    op.add_column("themes", sa.Column("price", sa.Integer(), server_default="0", nullable=True))
    op.add_column("themes", sa.Column("stripe_price_id", sa.String(), nullable=True))
    op.add_column("themes", sa.Column("stripe_product_id", sa.String(), nullable=True))
    op.add_column("themes", sa.Column("downloads", sa.Integer(), server_default="0", nullable=True))
    op.add_column("themes", sa.Column("rating", sa.Float(), server_default="5.0", nullable=True))
    op.add_column(
        "themes", sa.Column("reviews_count", sa.Integer(), server_default="0", nullable=True)
    )
    op.add_column(
        "themes", sa.Column("is_featured", sa.Boolean(), server_default="false", nullable=True)
    )
    op.add_column(
        "themes", sa.Column("is_published", sa.Boolean(), server_default="true", nullable=True)
    )
    op.add_column("themes", sa.Column("created_by_user_id", GUID(), nullable=True))
    op.add_column("themes", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column(
        "themes", sa.Column("category", sa.String(50), server_default="general", nullable=True)
    )
    op.add_column(
        "themes", sa.Column("source_type", sa.String(20), server_default="open", nullable=True)
    )
    op.add_column("themes", sa.Column("parent_theme_id", sa.String(100), nullable=True))
    with op.batch_alter_table("themes") as batch_op:
        batch_op.create_foreign_key(
            "fk_themes_created_by_user_id", "users", ["created_by_user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_themes_parent_theme_id", "themes", ["parent_theme_id"], ["id"], ondelete="SET NULL"
        )

    # Data migration: set slug = id for existing themes
    op.execute("UPDATE themes SET slug = id WHERE slug IS NULL")

    # Create unique index on slug
    op.create_index("ix_themes_slug", "themes", ["slug"], unique=True)

    # --- Create user_library_themes table ---
    op.create_table(
        "user_library_themes",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "theme_id",
            sa.String(100),
            sa.ForeignKey("themes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("purchase_type", sa.String(20), nullable=False, server_default="free"),
        sa.Column("stripe_payment_intent", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.UniqueConstraint("user_id", "theme_id", name="uq_user_library_theme"),
    )
    op.create_index("ix_user_library_themes_id", "user_library_themes", ["id"])
    op.create_index("ix_user_library_themes_user_id", "user_library_themes", ["user_id"])

    if op.get_bind().dialect.name != "postgresql":
        return

    # Data migration: auto-add default-dark and default-light to all existing users
    op.execute("""
        INSERT INTO user_library_themes (id, user_id, theme_id, purchase_type, is_active)
        SELECT gen_random_uuid(), u.id, t.id, 'free', true
        FROM users u
        CROSS JOIN themes t
        WHERE t.id IN ('default-dark', 'default-light')
        ON CONFLICT ON CONSTRAINT uq_user_library_theme DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("user_library_themes")

    op.drop_index("ix_themes_slug", table_name="themes")
    op.drop_column("themes", "parent_theme_id")
    op.drop_column("themes", "source_type")
    op.drop_column("themes", "category")
    op.drop_column("themes", "tags")
    op.drop_column("themes", "created_by_user_id")
    op.drop_column("themes", "is_published")
    op.drop_column("themes", "is_featured")
    op.drop_column("themes", "reviews_count")
    op.drop_column("themes", "rating")
    op.drop_column("themes", "downloads")
    op.drop_column("themes", "stripe_product_id")
    op.drop_column("themes", "stripe_price_id")
    op.drop_column("themes", "price")
    op.drop_column("themes", "pricing_type")
    op.drop_column("themes", "preview_image")
    op.drop_column("themes", "icon")
    op.drop_column("themes", "long_description")
    op.drop_column("themes", "slug")
