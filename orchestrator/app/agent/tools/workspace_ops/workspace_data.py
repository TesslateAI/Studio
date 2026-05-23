"""Agent tool: ``workspace_data`` — read/write the project's built-in data store.

The workspace data store is a per-project KV/document database (plain rows in
the platform DB — no pods, no lifecycle). The agent always has full
project-scoped access; the public anon/service keys and per-collection access
flags gate only the *external* HTTP Data API, never this tool.
"""

import logging
from typing import Any

from ....services import workspace_data as store
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


# --- Action handlers --------------------------------------------------------
async def _list_collections(context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    collections = await store.list_collections(db, project_id)
    items = [
        {
            "name": c.name,
            "id": str(c.id),
            "record_count": await store.collection_record_count(db, c.id),
            "public_read": c.public_read,
            "public_insert": c.public_insert,
            "public_update": c.public_update,
            "public_delete": c.public_delete,
        }
        for c in collections
    ]
    return success_output(
        message=f"{len(items)} collection(s) in this workspace's data store.",
        collections=items,
    )


async def _create_collection(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not name:
        return error_output(message="'name' is required to create a collection.")
    collection = await store.create_collection(
        context["db"],
        context["project_id"],
        name,
        public_insert=bool(params.get("public_insert", True)),
        public_read=bool(params.get("public_read", False)),
        public_update=bool(params.get("public_update", False)),
        public_delete=bool(params.get("public_delete", False)),
    )
    return success_output(
        message=f"Created collection '{collection.name}'.",
        collection=collection.name,
        id=str(collection.id),
    )


async def _insert(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    collection_ref = params.get("collection")
    data = params.get("data")
    if not collection_ref:
        return error_output(message="'collection' is required.")
    if not isinstance(data, dict):
        return error_output(
            message="'data' must be a JSON object.",
            suggestion='Pass the document as an object, e.g. {"email": "a@b.com"}.',
        )
    collection = await store.require_collection(
        context["db"], context["project_id"], collection_ref
    )
    record = await store.insert_record(context["db"], collection, data)
    return success_output(
        message=f"Inserted a record into '{collection.name}'.",
        id=str(record.id),
        record={"id": str(record.id), "data": record.data},
    )


async def _query(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    collection_ref = params.get("collection")
    if not collection_ref:
        return error_output(message="'collection' is required.")
    collection = await store.require_collection(
        context["db"], context["project_id"], collection_ref
    )
    records, total = await store.list_records(
        context["db"],
        collection.id,
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )
    return success_output(
        message=f"Returned {len(records)} of {total} record(s) from '{collection.name}'.",
        total=total,
        count=len(records),
        records=[
            {
                "id": str(r.id),
                "data": r.data,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    )


async def _get(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    collection_ref = params.get("collection")
    record_id = params.get("record_id")
    if not collection_ref or not record_id:
        return error_output(message="'collection' and 'record_id' are required.")
    collection = await store.require_collection(
        context["db"], context["project_id"], collection_ref
    )
    record = await store.get_record(context["db"], collection.id, record_id)
    if record is None:
        return error_output(message=f"Record '{record_id}' not found in '{collection.name}'.")
    return success_output(
        message=f"Record '{record_id}'.",
        id=str(record.id),
        record={"id": str(record.id), "data": record.data},
    )


async def _update(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    collection_ref = params.get("collection")
    record_id = params.get("record_id")
    data = params.get("data")
    if not collection_ref or not record_id:
        return error_output(message="'collection' and 'record_id' are required.")
    if not isinstance(data, dict):
        return error_output(message="'data' must be a JSON object.")
    collection = await store.require_collection(
        context["db"], context["project_id"], collection_ref
    )
    record = await store.get_record(context["db"], collection.id, record_id)
    if record is None:
        return error_output(message=f"Record '{record_id}' not found in '{collection.name}'.")
    record = await store.update_record(context["db"], record, data)
    return success_output(
        message=f"Updated record '{record_id}' in '{collection.name}'.",
        id=str(record.id),
        record={"id": str(record.id), "data": record.data},
    )


async def _delete(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    collection_ref = params.get("collection")
    record_id = params.get("record_id")
    if not collection_ref or not record_id:
        return error_output(message="'collection' and 'record_id' are required.")
    collection = await store.require_collection(
        context["db"], context["project_id"], collection_ref
    )
    record = await store.get_record(context["db"], collection.id, record_id)
    if record is None:
        return error_output(message=f"Record '{record_id}' not found in '{collection.name}'.")
    await store.delete_record(context["db"], record)
    return success_output(message=f"Deleted record '{record_id}' from '{collection.name}'.")


async def _list_keys(context: dict[str, Any]) -> dict[str, Any]:
    keys = await store.list_data_keys(context["db"], context["project_id"])
    return success_output(
        message=f"{len(keys)} Data API key(s) on this workspace.",
        keys=[
            {
                "id": str(k.id),
                "name": k.name,
                "kind": k.kind,
                "prefix": k.key_prefix,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ],
    )


async def _create_key(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    kind = params.get("kind", "anon")
    if not name:
        return error_output(message="'name' is required to create a key.")
    key, raw = await store.create_data_key(
        context["db"],
        context["project_id"],
        name,
        kind,
        created_by_id=context.get("user_id"),
    )
    return success_output(
        message=(
            f"Created {key.kind} key '{key.name}'. The secret is shown only once — to let "
            f"a deployed frontend reach the data store, write it into the app's env file "
            f"(e.g. VITE_OPENSAIL_DATA_KEY in .env) next to the Data API URL. anon keys are "
            f"browser-safe; service keys are server-side only. For the exact client "
            f"snippet to drop into the app, call load_skill 'workspace-data-sdk'."
        ),
        id=str(key.id),
        kind=key.kind,
        key=raw,
    )


async def _revoke_key(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    key_id = params.get("key_id")
    if not key_id:
        return error_output(message="'key_id' is required.")
    if not await store.revoke_data_key(context["db"], context["project_id"], key_id):
        return error_output(message=f"Key '{key_id}' not found.")
    return success_output(message=f"Revoked key '{key_id}'.")


_ACTIONS = {
    "list_collections": lambda params, ctx: _list_collections(ctx),
    "create_collection": _create_collection,
    "insert": _insert,
    "query": _query,
    "get": _get,
    "update": _update,
    "delete": _delete,
    "list_keys": lambda params, ctx: _list_keys(ctx),
    "create_key": _create_key,
    "revoke_key": _revoke_key,
}

# Friendly next-step hints keyed by store error class name.
_SUGGESTIONS = {
    "CollectionNotFoundError": (
        "Create it first with action 'create_collection', or run "
        "action 'list_collections' to see what exists."
    ),
    "CollectionExistsError": "Use the existing collection, or pick a different name.",
    "QuotaExceededError": "Delete unused records/collections, or raise the project's quota.",
}


async def workspace_data_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch a workspace data store action."""
    action = params.get("action")
    if not action:
        return error_output(
            message="'action' is required.",
            suggestion=f"Choose one of: {', '.join(_ACTIONS)}",
        )
    if context.get("db") is None or context.get("project_id") is None:
        return error_output(
            message="The workspace data store needs an attached workspace.",
            suggestion="This chat has no workspace — attach one with request_workspace first.",
        )
    handler = _ACTIONS.get(action)
    if handler is None:
        return error_output(
            message=f"Unknown action '{action}'.",
            suggestion=f"Choose one of: {', '.join(_ACTIONS)}",
        )
    try:
        return await handler(params, context)
    except store.WorkspaceDataError as exc:
        return error_output(message=str(exc), suggestion=_SUGGESTIONS.get(type(exc).__name__))
    except Exception as exc:  # noqa: BLE001 - surface any failure to the agent
        logger.error("workspace_data action '%s' failed: %s", action, exc, exc_info=True)
        return error_output(message=f"workspace_data '{action}' failed: {exc}")


_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(_ACTIONS),
            "description": (
                "Collections/records: list_collections, create_collection, insert, query, "
                "get, update, delete. API keys: list_keys, create_key, revoke_key."
            ),
        },
        "collection": {
            "type": "string",
            "description": (
                "Collection name (or id). Required for record actions; not used by "
                "list_collections or the *_key actions."
            ),
        },
        "name": {
            "type": "string",
            "description": "Name for create_collection (collection name) or create_key (key name).",
        },
        "kind": {
            "type": "string",
            "enum": ["anon", "service"],
            "description": (
                "create_key: 'anon' is browser-safe and obeys each collection's public "
                "flags; 'service' is a server-side secret with full access. Default anon."
            ),
        },
        "key_id": {
            "type": "string",
            "description": "Data API key id (revoke_key).",
        },
        "record_id": {
            "type": "string",
            "description": "Record id (get, update, delete).",
        },
        "data": {
            "type": "object",
            "description": "JSON document to store (insert, update).",
        },
        "limit": {
            "type": "integer",
            "description": "Max records to return (query). Default 50, max 200.",
        },
        "offset": {
            "type": "integer",
            "description": "Pagination offset (query). Default 0.",
        },
        "public_insert": {
            "type": "boolean",
            "description": "create_collection: allow anonymous inserts from deployed frontends. Default true.",
        },
        "public_read": {
            "type": "boolean",
            "description": "create_collection: allow anonymous reads. Default false.",
        },
        "public_update": {
            "type": "boolean",
            "description": "create_collection: allow anonymous updates. Default false.",
        },
        "public_delete": {
            "type": "boolean",
            "description": "create_collection: allow anonymous deletes. Default false.",
        },
    },
    "required": ["action"],
}


def register_workspace_data_tool(registry) -> None:
    """Register the ``workspace_data`` tool."""
    registry.register(
        Tool(
            name="workspace_data",
            description=(
                "Read and write the workspace's built-in data store — a per-project "
                "KV/document database (collections of JSON records). Use it to persist "
                "structured data (form submissions, app state, lookups, scraped results) "
                "without an external database. Always available, including on workspaces "
                "with no running compute. Collection/record actions: list_collections, "
                "create_collection, insert, query, get, update, delete. Key management: "
                "list_keys, create_key, revoke_key — mint an anon key and write it into "
                "the app's env file so a deployed frontend can reach the data store. "
                "When building an app that USES this store from the frontend (form, "
                "dashboard, etc.), first call load_skill with skill_name "
                "'workspace-data-sdk' — it returns drop-in client code for TypeScript/"
                "Vite, Next.js, vanilla JS, Python, Go and curl, plus the exact env-var "
                "names the deploy flow auto-injects."
            ),
            parameters=_PARAMETERS,
            executor=workspace_data_executor,
            category=ToolCategory.PROJECT,
            # Plain JSON params/results; rows in the platform DB, no sockets/PTYs.
            state_serializable=True,
            holds_external_state=False,
            examples=[
                '{"tool_name": "workspace_data", "parameters": {"action": "create_collection", "name": "submissions"}}',
                '{"tool_name": "workspace_data", "parameters": {"action": "insert", "collection": "submissions", "data": {"email": "a@b.com", "message": "hi"}}}',
                '{"tool_name": "workspace_data", "parameters": {"action": "query", "collection": "submissions", "limit": 20}}',
            ],
        )
    )
    logger.info("Registered workspace_data tool")
