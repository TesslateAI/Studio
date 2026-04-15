"""Publish-time merger: .tesslate/config.json -> app.manifest.json (schema 2025-01).

Consumes a parsed base_config dict (canvas-authored) plus creator-supplied
``user_overrides`` (slug, version, billing, etc.) and produces a manifest_dict
that conforms to ``app_manifest_2025_01.schema.json``.

User overrides always win over inferred values. ``billing`` must be declared
by the creator — there is no safe default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..base_config_parser import HostedAgentConfig
from .app_manifest import MANIFEST_SCHEMA_VERSION

_DEFAULT_RUNTIME_API = "1.0"
_DEFAULT_STUDIO_MIN = "0.1.0"

# Container roles that should produce a ui surface.
_UI_ROLES = {"frontend", "preview", "ui", "web"}

# Substrings in image names that imply a database container.
_DB_IMAGE_HINTS = ("postgres", "mysql", "mariadb", "mongo", "redis", "sqlite")


@dataclass(frozen=True)
class MergeResult:
    manifest_dict: dict[str, Any]
    inferred: dict[str, str]


def merge_canvas_config(
    *,
    base_config: dict[str, Any],
    user_overrides: dict[str, Any],
    creator_user_id: str,
) -> MergeResult:
    """Build a schema-2025-01 manifest_dict from canvas config + creator inputs."""
    inferred: dict[str, str] = {}

    # ----- app meta (user-driven, required fields must be in user_overrides) -----
    app_overrides = dict(user_overrides.get("app") or {})
    for required in ("id", "name", "slug", "version"):
        if not app_overrides.get(required):
            raise ValueError(f"user_overrides.app.{required} is required")
    app_meta: dict[str, Any] = dict(app_overrides)
    app_meta["creator_id"] = creator_user_id

    # ----- compatibility -----
    compat_override = dict(user_overrides.get("compatibility") or {})
    studio = dict(compat_override.get("studio") or {"min": _DEFAULT_STUDIO_MIN})
    compatibility: dict[str, Any] = {
        "studio": studio,
        "manifest_schema": MANIFEST_SCHEMA_VERSION,
        "runtime_api": compat_override.get("runtime_api", _DEFAULT_RUNTIME_API),
    }
    if "required_features" in compat_override:
        compatibility["required_features"] = list(compat_override["required_features"])

    # ----- billing (no inference allowed) -----
    billing = user_overrides.get("billing")
    if not billing:
        raise ValueError("user_overrides.billing is required; creators must declare billing")

    # ----- containers / compute -----
    containers_raw = list(base_config.get("containers") or [])
    container_dicts = [_container_to_dict(c) for c in containers_raw]

    hosted_agents = base_config.get("hosted_agents") or ()
    hosted_agent_dicts = [_hosted_agent_to_dict(a) for a in hosted_agents]

    compute_override = dict(user_overrides.get("compute") or {})
    # Build id→name map for connection serialization when the canvas emits
    # UUID-keyed edges instead of name-keyed.
    container_name_by_id: dict[str, str] = {}
    for c in containers_raw:
        if isinstance(c, dict) and c.get("id") and c.get("name"):
            container_name_by_id[str(c["id"])] = str(c["name"])

    connections_raw = (
        compute_override.get("connections")
        or base_config.get("connections")
        or []
    )
    connections_manifest = _connections_to_manifest(
        connections_raw, container_name_by_id=container_name_by_id
    )

    compute: dict[str, Any] = {
        "tier": compute_override.get("tier", 0),
        "compute_model": compute_override.get("compute_model", "per-invocation"),
        "containers": compute_override.get("containers") or container_dicts,
        "connections": connections_manifest,
        "hosted_agents": compute_override.get("hosted_agents") or hosted_agent_dicts,
    }

    # ----- surfaces (user wins, else infer from containers) -----
    if user_overrides.get("surfaces"):
        surfaces = [dict(s) for s in user_overrides["surfaces"]]
    else:
        surfaces = []
        for idx, container in enumerate(containers_raw):
            role = (container.get("role") or "").lower()
            if role in _UI_ROLES:
                entrypoint = (
                    container.get("entrypoint")
                    or container.get("url")
                    or container.get("name")
                    or "/"
                )
                surfaces.append({"kind": "ui", "entrypoint": entrypoint})
                inferred[f"surfaces[{idx}].kind"] = f"inferred:container-role={role}"
        if not surfaces:
            # Schema requires minItems=1; fall back to a synthetic chat surface when
            # hosted agents exist, otherwise a placeholder ui surface so publish
            # fails fast on an empty app.
            if hosted_agent_dicts:
                surfaces.append({"kind": "chat", "entrypoint": hosted_agent_dicts[0]["id"]})
                inferred["surfaces[0].kind"] = "inferred:hosted-agent-fallback"
            else:
                raise ValueError(
                    "cannot infer any surfaces: no UI containers, no hosted agents, "
                    "and no surfaces supplied in user_overrides"
                )

    # ----- state -----
    if user_overrides.get("state"):
        state = dict(user_overrides["state"])
    else:
        db_container = _find_db_container(containers_raw)
        if db_container is not None:
            schema_hint = db_container.get("db_schema") or db_container.get("schema")
            state = {"model": "byo-database"}
            byo: dict[str, Any] = {}
            if schema_hint:
                byo["schema"] = schema_hint
            if db_container.get("connection_env"):
                byo["connection_env"] = db_container["connection_env"]
            if byo:
                state["byo_database"] = byo
            inferred["state.model"] = (
                f"inferred:db-container={db_container.get('name', '?')}"
            )
        elif _has_persistent_volume(containers_raw):
            state = {"model": "per-install-volume"}
            inferred["state.model"] = "inferred:persistent-volume-detected"
        else:
            state = {"model": "stateless"}
            inferred["state.model"] = "inferred:no-persistent-volumes"

    # ----- listing / source_visibility -----
    listing_override = dict(user_overrides.get("listing") or {})
    listing = {"visibility": listing_override.get("visibility", "private")}
    for extra in ("update_policy_default", "minimum_rollback_version"):
        if extra in listing_override:
            listing[extra] = listing_override[extra]
    source_visibility = dict(user_overrides.get("source_visibility") or {"level": "installers"})

    # ----- connectors / schedules -----
    connectors = [dict(c) for c in (user_overrides.get("connectors") or [])]
    if not connectors:
        connectors = _infer_connectors(base_config.get("connections") or [])
        if connectors:
            inferred["connectors"] = "inferred:from-base-config-connections"

    schedules = [dict(s) for s in (user_overrides.get("schedules") or [])]
    if not schedules:
        canvas_schedules = base_config.get("agent_schedules") or base_config.get("schedules") or []
        schedules = _schedules_to_manifest(list(canvas_schedules))

    manifest_dict: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "app": app_meta,
        "compatibility": compatibility,
        "surfaces": surfaces,
        "state": state,
        "billing": billing,
        "listing": listing,
        "source_visibility": source_visibility,
        "compute": compute,
    }
    if connectors:
        manifest_dict["connectors"] = connectors
    if schedules:
        manifest_dict["schedules"] = schedules
    if user_overrides.get("migrations"):
        manifest_dict["migrations"] = list(user_overrides["migrations"])
    if user_overrides.get("eval_scenarios"):
        manifest_dict["eval_scenarios"] = list(user_overrides["eval_scenarios"])

    return MergeResult(manifest_dict=manifest_dict, inferred=inferred)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _container_to_dict(container: Any) -> dict[str, Any]:
    if isinstance(container, dict):
        # Drop canvas-only fields that aren't part of ContainerSpec; keep extras.
        out = {k: v for k, v in container.items() if k not in {"role", "db_schema", "entrypoint", "url"}}
        out.setdefault("name", container.get("name", ""))
        out.setdefault("image", container.get("image", ""))
        # 2025-02: surface the DB-level is_primary flag into manifest as `primary`.
        if "primary" not in out and "is_primary" in container:
            out["primary"] = bool(container["is_primary"])
            out.pop("is_primary", None)
        return out
    # Dataclass-like with to_dict
    if hasattr(container, "to_dict"):
        d = container.to_dict()
        if "primary" not in d and "is_primary" in d:
            d["primary"] = bool(d.pop("is_primary"))
        return d
    raise TypeError(f"unsupported container entry: {type(container).__name__}")


def _connections_to_manifest(
    connections: list[Any],
    container_name_by_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Serialize container connection rows/dicts into manifest shape.

    Accepts either ORM-ish objects (with source_container_id/target_container_id)
    or plain dicts. Name resolution uses ``container_name_by_id`` when the
    input carries UUID references.
    """
    out: list[dict[str, Any]] = []
    container_name_by_id = container_name_by_id or {}
    valid_kinds = {
        "env_injection", "http_api", "database", "cache",
        "message_queue", "websocket", "depends_on",
    }
    for conn in connections or ():
        if isinstance(conn, dict):
            src = conn.get("source_container") or conn.get("source")
            tgt = conn.get("target_container") or conn.get("target")
            if not src and conn.get("source_container_id"):
                src = container_name_by_id.get(str(conn["source_container_id"]))
            if not tgt and conn.get("target_container_id"):
                tgt = container_name_by_id.get(str(conn["target_container_id"]))
            kind = conn.get("connector_type") or "env_injection"
            cfg = conn.get("config") or {}
        else:
            src = container_name_by_id.get(str(getattr(conn, "source_container_id", "")))
            tgt = container_name_by_id.get(str(getattr(conn, "target_container_id", "")))
            kind = getattr(conn, "connector_type", None) or "env_injection"
            cfg = getattr(conn, "config", None) or {}
        if not src or not tgt:
            continue
        if kind not in valid_kinds:
            continue
        out.append({
            "source_container": src,
            "target_container": tgt,
            "connector_type": kind,
            "config": dict(cfg) if isinstance(cfg, dict) else {},
        })
    return out


def _schedules_to_manifest(schedules: list[Any]) -> list[dict[str, Any]]:
    """Serialize AgentSchedule rows/dicts into manifest.schedules[] shape.

    Flattens ``trigger_config`` onto the top level so schema fields
    (``execution``, ``entrypoint``) live where the 2025-02 schema expects them.
    Unknown keys are dropped to keep manifests deterministic.
    """
    out: list[dict[str, Any]] = []
    for s in schedules or ():
        if isinstance(s, dict):
            name = s.get("name")
            cron = s.get("default_cron") or s.get("cron_expression") or s.get("cron")
            trigger_kind = s.get("trigger_kind", "cron")
            trigger_config = s.get("trigger_config") or {}
            entrypoint = s.get("entrypoint") or trigger_config.get("entrypoint")
            execution = s.get("execution") or trigger_config.get("execution", "job")
            editable = s.get("editable", True)
            optional = s.get("optional", True)
        else:
            name = getattr(s, "name", None)
            cron = getattr(s, "cron_expression", None)
            trigger_kind = getattr(s, "trigger_kind", "cron")
            trigger_config = getattr(s, "trigger_config", None) or {}
            entrypoint = trigger_config.get("entrypoint") if isinstance(trigger_config, dict) else None
            execution = (
                trigger_config.get("execution", "job") if isinstance(trigger_config, dict) else "job"
            )
            editable = True
            optional = True
        if not name:
            continue
        entry: dict[str, Any] = {
            "name": name,
            "trigger_kind": trigger_kind,
            "execution": execution,
            "editable": bool(editable),
            "optional": bool(optional),
        }
        if cron:
            entry["default_cron"] = cron
        if entrypoint:
            entry["entrypoint"] = entrypoint
        out.append(entry)
    return out


def _hosted_agent_to_dict(agent: Any) -> dict[str, Any]:
    if isinstance(agent, HostedAgentConfig):
        return agent.to_dict()
    if isinstance(agent, dict):
        return HostedAgentConfig.from_dict(agent).to_dict()
    if hasattr(agent, "to_dict"):
        return agent.to_dict()
    raise TypeError(f"unsupported hosted_agent entry: {type(agent).__name__}")


def _find_db_container(containers: list[Any]) -> dict[str, Any] | None:
    for c in containers:
        if not isinstance(c, dict):
            continue
        role = (c.get("role") or "").lower()
        image = (c.get("image") or "").lower()
        if role in {"db", "database"}:
            return c
        if any(hint in image for hint in _DB_IMAGE_HINTS):
            return c
    return None


def _has_persistent_volume(containers: list[Any]) -> bool:
    for c in containers:
        if not isinstance(c, dict):
            continue
        volumes = c.get("volumes") or c.get("persistent_volumes")
        if volumes:
            return True
    return False


def _infer_connectors(connections: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        kind = conn.get("kind")
        conn_id = conn.get("id") or conn.get("name")
        if not kind or not conn_id or conn_id in seen:
            continue
        if kind not in {"mcp", "api_key", "oauth", "webhook"}:
            continue
        seen.add(conn_id)
        entry: dict[str, Any] = {"id": conn_id, "kind": kind}
        if conn.get("scopes"):
            entry["scopes"] = list(conn["scopes"])
        if "required" in conn:
            entry["required"] = bool(conn["required"])
        if "oauth" in conn:
            entry["oauth"] = bool(conn["oauth"])
        if conn.get("secret_key"):
            entry["secret_key"] = conn["secret_key"]
        out.append(entry)
    return out
