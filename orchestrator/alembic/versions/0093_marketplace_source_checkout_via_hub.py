"""marketplace sources: per-source hub-checkout opt-in column (Wave 9).

Revision ID: 0093_msrc_checkout_hub
Revises: 0092_appver_source_id
Create Date: 2026-04-29

Wave 9 of the federated-marketplace decoupling. Adds a single nullable-
defaulted column to ``marketplace_sources``:

    checkout_via_hub_enabled BOOLEAN NOT NULL DEFAULT false

Per the Wave-9 ``dispatch_purchase`` rules, hub-owned checkout
(``pricing.checkout`` capability) only fires when:

  1. The hub advertises the ``pricing.checkout`` capability,
  2. The source's ``trust_level`` is ``official`` or ``admin_trusted``,
  3. ``MARKETPLACE_HUB_CHECKOUT_GLOBAL_ENABLED=true`` (env / settings),
  4. AND the source row's ``checkout_via_hub_enabled`` is ``true``,
  5. AND the runtime feature flag
     ``marketplace_federation_checkout_use_hub_checkout`` is ``true``.

(4) is the per-source rollout dial — operators flip it on once parity
tests pass for that source. (5) is the global kill-switch. Both default
off so Wave 9 ships a complete code path that is dormant until it's
explicitly enabled per-source.

Purely additive — no backfill needed and no constraints touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0093_msrc_checkout_hub"
down_revision: str | Sequence[str] | None = "0092_appver_source_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("marketplace_sources") as batch:
        batch.add_column(
            sa.Column(
                "checkout_via_hub_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("marketplace_sources") as batch:
        batch.drop_column("checkout_via_hub_enabled")
