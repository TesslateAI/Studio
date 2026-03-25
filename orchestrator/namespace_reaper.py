#!/usr/bin/env python3
"""Entry point for the namespace-reaper CronJob."""

import logging
import sys

from app.services.namespace_reaper import NamespaceReaper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

try:
    result = NamespaceReaper().reap()
    if result.errors:
        sys.exit(1)
except Exception as e:
    logging.getLogger("namespace-reaper").error("Reaper failed: %s", e, exc_info=True)
    sys.exit(1)
