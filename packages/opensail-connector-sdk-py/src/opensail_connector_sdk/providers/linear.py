"""Linear provider sugar.

Linear's API is GraphQL-first; the proxy allowlist exposes
``POST graphql`` plus a few REST helpers. We surface a minimal
``proxy.linear.graphql(query=..., variables=...)`` plus typed sugar for
the two operations creators ask for most: ``issues.list`` and
``issues.create``. The sugar is implemented as canned GraphQL operations
sent through the same ``graphql`` endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..client import ConnectorProxy


_CONNECTOR_ID = "linear"

_ISSUES_LIST_QUERY = """
query IssuesList($first: Int, $filter: IssueFilter) {
  issues(first: $first, filter: $filter) {
    nodes {
      id
      identifier
      title
      state { id name type }
      assignee { id name email }
      url
      createdAt
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()


_ISSUES_CREATE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      title
      url
    }
  }
}
""".strip()


class _LinearIssues:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(
        self,
        *,
        first: int | None = 50,
        filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {}
        if first is not None:
            variables["first"] = first
        if filter is not None:
            variables["filter"] = filter
        return await self._proxy.linear.graphql(  # type: ignore[attr-defined]
            query=_ISSUES_LIST_QUERY, variables=variables
        )

    async def create(
        self,
        *,
        team_id: str,
        title: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        input_obj: dict[str, Any] = {"teamId": team_id, "title": title}
        if description is not None:
            input_obj["description"] = description
        if assignee_id is not None:
            input_obj["assigneeId"] = assignee_id
        if priority is not None:
            input_obj["priority"] = priority
        if labels is not None:
            input_obj["labelIds"] = labels
        input_obj.update(extra)
        return await self._proxy.linear.graphql(  # type: ignore[attr-defined]
            query=_ISSUES_CREATE_MUTATION, variables={"input": input_obj}
        )


class Linear:
    """Top-level ``proxy.linear`` namespace."""

    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy
        self.issues = _LinearIssues(proxy)

    async def graphql(
        self,
        *,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a raw GraphQL request to ``POST /graphql``."""
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        if operation_name is not None:
            body["operationName"] = operation_name
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path="graphql",
            json=body,
        )


__all__ = ["Linear"]
