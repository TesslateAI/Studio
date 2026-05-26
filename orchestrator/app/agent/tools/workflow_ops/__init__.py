"""Agent tools for self-modifying workflows (G2+, issue #469).

Two tools today:

* ``manage_workflow_proposal`` (G2) — agent drafts changes to an
  automation it owns. Routes through the existing approval pipeline.
* ``read_workflow_history`` (G2) — agent reads recent runs + step
  outputs + events so it can diagnose before proposing changes.

G3 adds ``test_run_workflow``. G6 adds ``lookup_learning`` /
``record_learning``. G5's doctor pulls in all of these.
"""

from .manage_workflow_proposal import register_manage_workflow_proposal_tool
from .read_workflow_history import register_read_workflow_history_tool


def register_all_workflow_ops_tools(registry) -> None:
    register_manage_workflow_proposal_tool(registry)
    register_read_workflow_history_tool(registry)


__all__ = ["register_all_workflow_ops_tools"]
