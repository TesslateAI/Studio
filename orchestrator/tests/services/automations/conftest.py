"""Per-package conftest for automation service tests.

Forces ``app.models`` (legacy/canonical ORM) to import BEFORE any test
imports ``app.models_automations``. Without this, tests that only import
``ControllerIntent``/``AppInstance``/etc. trigger SQLAlchemy mapper
configuration which then can't resolve string references like
``"MarketplaceApp"`` (defined in ``app.models``).

Symptom that motivated this file:

    sqlalchemy.exc.InvalidRequestError: When initializing mapper
    Mapper[AppInstance(app_instances)], expression 'MarketplaceApp'
    failed to locate a name ('MarketplaceApp').

Importing ``app.models`` here is a side-effect-only registration; we
don't bind the symbols. The order is the only thing that matters.
"""

from __future__ import annotations

import app.models  # noqa: F401  # registers MarketplaceApp + friends
import app.models_automations  # noqa: F401  # registers automation tables
