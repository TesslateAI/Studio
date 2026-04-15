# Tesslate App Manifest — v2 (2025-02)

**Status:** Frozen. Any change to this version is a breaking change; new fields
or semantics go in a new schema file (`app_manifest_YYYY_MM.schema.json`).

**Authoritative schema:** `orchestrator/app/services/apps/app_manifest_2025_02.schema.json`
**Parser:** `orchestrator/app/services/apps/manifest_parser.py`
**Hash-pin test:** `orchestrator/tests/apps/test_manifest_schema_2025_02_frozen.py`

2025-02 supersedes 2025-01. The parser accepts **both** schemas — legacy apps
continue to install as long as they declare `manifest_schema_version: "2025-01"`
with a 2025-01 document; new seeds ship as 2025-02.

## What changed vs 2025-01

- `manifest_schema_version` / `compatibility.manifest_schema` pinned to `"2025-02"`.
- `surfaces.minItems` is now **0** — headless apps (cron / webhook only) are
  first-class.
- `surfaces[].entrypoint` is now **required only** for `kind ∈ {ui, chat}`;
  other surface kinds may omit it. For `ui`/`chat` surfaces, `entrypoint` is a
  path relative to the primary container URL (the parser keeps legacy absolute
  URL behaviour for 2025-01 manifests — the semantic flip is scoped to 2025-02).
- `compute.containers[].primary: boolean (default false)`. If `containers` is
  non-empty the array must contain at least one entry with `primary: true`
  (JSON Schema `contains` rule). This removes the implicit "first container is
  primary" rule.
- New `compute.connections[]`: mirrors the `ContainerConnection` DB rows so
  multi-container apps can declare dependencies (`env_injection`, `http_api`,
  `database`, `cache`, `message_queue`, `websocket`, `depends_on`) with
  `source_container` / `target_container` name strings and a free-form
  `config: object` (typically `env_mapping`).
- `schedules[].execution: enum[job, http-post] (default "job")` and
  `schedules[].trigger_kind: enum[cron, webhook] (default "cron")`.
- `schedules[].entrypoint` is optional (webhook-triggered schedules with
  `execution: http-post` resolve the endpoint from `trigger_config` at runtime).
- Secret-ref env values of shape `"${secret:<name>/<key>}"` in container `env`
  maps are formalized as a **convention** (no schema change — env values are
  still `additionalProperties: {type: string}`). Resolution to
  `valueFrom.secretKeyRef` happens at pod-spec build time; see
  `services/apps/env_resolver.py`.

## Top-level shape

```yaml
manifest_schema_version: "2025-02"
app: { id, name, slug, version, ... }
compatibility: { studio: { min, max? }, manifest_schema, runtime_api, required_features[] }
surfaces: [ { kind, entrypoint?, name?, description?, tool_schema? } ]   # minItems: 0
compute:
  tier
  compute_model
  containers: [ { name, image, primary, ports, env, startup_command, resources } ]
  connections: [ { source_container, target_container, connector_type, config } ]
  hosted_agents: [ ... same shape as 2025-01 ... ]
state: { model, volume_size?, byo_database? }
connectors: [ ... same shape as 2025-01 ... ]
schedules: [ { name, default_cron?, entrypoint?, execution, trigger_kind, editable?, optional? } ]
billing: { ai_compute, general_compute, platform_fee, promotional_budget? }
listing: { visibility, update_policy_default?, minimum_rollback_version? }
eval_scenarios: [ ... ]
```

## Primary container & surface entrypoint semantics

For `kind: ui | chat` in 2025-02 manifests, `entrypoint` is a path relative to
the primary container's URL (the container with `primary: true`). The workspace
resolves the iframe src as `${primary_url}${entrypoint || "/"}` at runtime.

Headless apps (`surfaces: []`) never render an iframe — the workspace falls
through to the Schedules tab as the primary layout.

## Schedules & triggers

| `trigger_kind` | `execution` | Semantics                                                                      |
|----------------|-------------|---------------------------------------------------------------------------------|
| `cron`         | `job`       | Cron fires → V1Job built from primary container image + `entrypoint` command.   |
| `cron`         | `http-post` | Cron fires → POST to `${primary_url}${entrypoint}` with invocation-key auth.    |
| `webhook`      | `job`       | External POST to `/api/app-instances/{id}/trigger/{name}` → V1Job.              |
| `webhook`      | `http-post` | External POST → POST to primary container endpoint.                             |

Webhook triggers authenticate via HMAC-SHA256 of the body against
`trigger_config.webhook_secret` (header: `X-Tesslate-Signature`).

See the 2025-01 spec for `state`, `billing`, `listing`, `fork policy`,
`source_visibility`, and `eval_scenarios` semantics — those are unchanged.

## Backward compatibility

Both schemas remain installable. The parser selects the validator via the
declared `manifest_schema_version`. Deployments advertise support through
`GET /api/version` (`features[]` includes `manifest_schema_2025_02`).

## Change discipline

- Never mutate `app_manifest_2025_02.schema.json` after it lands in `main`.
- `manifest_schema_version` is pinned to `"2025-02"` in the JSON Schema (as
  `const`).
- The hash-pin test in `tests/apps/test_manifest_schema_2025_02_frozen.py`
  fails if the schema file bytes change.
