# Tesslate App Manifest — v2.1 (2026-06, container-shape)

**Status:** Frozen. Any change to this version is a breaking change; new fields
or semantics go in a new schema file (`app_manifest_YYYY_MM.schema.json`).

**Authoritative schema:** `orchestrator/app/services/apps/app_manifest_2026_06.schema.json`
**Parser:** `orchestrator/app/services/apps/manifest_parser.py`
**Hash-pin test:** `orchestrator/tests/apps/test_manifest_schema_2026_06_frozen.py`

2026-06 supersedes 2025-02 on the **container-shape** track (long-running
container apps with PVC state, multi-service stacks). It is unrelated to
2026-05, which is the **action-shape** track (App Runtime Contract: typed
RPC actions, on-demand dispatch, no persistent pods). The two shapes are
mutually exclusive — top-level `additionalProperties: false` rejects mixing.

The parser accepts all four schemas (2025-01, 2025-02, 2026-05, 2026-06);
new container-shape seeds ship as 2026-06.

## What changed vs 2025-02

Three additive optional fields. No breaking changes; otherwise byte-identical
to 2025-02.

- **`compute.credentials[]`** — new top-level under `compute`. Declares
  user-supplied secrets the install modal collects at install time. Each
  entry's `secret_ref` matches the `${secret:<name>/<key>}` convention used
  in container env values. The orchestrator upserts an Opaque K8s Secret
  named `<name>` in the platform namespace; `secret_propagator` copies it
  into the project namespace at start time. K8s mode only.

  Schema:
  ```yaml
  credentials:
    - secret_ref: "zep-credentials/api_key"   # required, "<name>/<key>"
      label: "Zep API Key"                    # optional
      description: "Get a key at https://..." # optional
      required: true                           # optional, default true
  ```

- **`compute.containers[].readiness_port`** — new per-container field.
  Decouples the K8s readiness probe + Service + Ingress port from
  `ports[0]`. Defaults to `ports[0]` when omitted. Use when an in-pod
  reverse proxy fronts the app on a different port than the dev server
  (deer-flow's nginx on `:2026` fronting Next.js on `:3000` and a Python
  backend on `:8001`).

- **`state.mount_path`** — was implicit-default in 2025-02; now an explicit
  optional string. Required in practice when `state.model=per-install-volume`
  and a container uses `source_strategy=image` and the image's WORKDIR is
  not `/data` (the platform won't mount a PVC over an image's WORKDIR).

## Top-level shape

```yaml
manifest_schema_version: "2026-06"
app: { id, name, slug, version, ... }
compatibility: { studio: { min, max? }, manifest_schema: "2026-06", runtime_api, required_features[] }
surfaces: [ { kind, entrypoint?, name?, description?, tool_schema? } ]
compute:
  tier
  model              # "always-on" | "job-only"
  compute_model
  containers: [ { name, image, primary, ports, readiness_port?, env, startup_command, resources } ]
  connections: [ { source_container, target_container, connector_type, config } ]
  credentials: [ { secret_ref, label?, description?, required? } ]
  hosted_agents: [ ... ]
state: { model, volume_size?, mount_path?, byo_database? }
connectors: [ ... ]
schedules: [ { name, default_cron?, entrypoint?, execution, trigger_kind, editable?, optional? } ]
billing: { ai_compute, general_compute, platform_fee, promotional_budget? }
listing: { visibility, update_policy_default?, minimum_rollback_version? }
eval_scenarios: [ ... ]
```

See `app-manifest-2025-02.md` for `surfaces`, `compatibility`, `connections`,
`hosted_agents`, `connectors`, `schedules`, `billing`, `listing`, and
`eval_scenarios` semantics — those are unchanged.

## Resolution pipeline for new fields

```
manifest.compute.credentials[]
  → AppInstallModal.tsx (install-time UI; required-field gating)
  → InstallRequest.user_credentials (api.ts → routers/app_installs.py)
  → _provision_user_credentials() upserts platform-namespace K8s Secrets
  → secret_propagator copies secrets into proj-{id} at start time
  → secret_provisioner.provision_app_secrets() at install completion
  → env_resolver.resolve_env_for_pod() resolves ${secret:...} refs
       (compound values use synthetic __tsecret_* secretKeyRef + K8s $(VAR))

manifest.compute.containers[].readiness_port
  → _seed_publish_federated.py
  → base_config_parser.AppConfig.readiness_port
  → install_compute_materializer (stashed in Container.resources JSON)
  → compute_manager.create_v2_dev_deployment(readiness_port=...)
  → kubernetes/helpers.py: probe + Service + Ingress port

manifest.state.mount_path
  → _seed_publish_federated.py (carried through state_mount_path field)
  → install_compute_materializer (sets Container.state_mount_path)
  → kubernetes/helpers.py: PVC mount point on image-strategy containers
```

## Backward compatibility

All four schemas remain installable. The parser selects the validator via
the declared `manifest_schema_version`. Deployments advertise support
through `GET /api/version` (`features[]` includes `manifest_schema_2026_06`).

## Change discipline

- Never mutate `app_manifest_2026_06.schema.json` after it lands in `main`.
- `manifest_schema_version` is pinned to `"2026-06"` in the JSON Schema
  (as `const`).
- The hash-pin test in `tests/apps/test_manifest_schema_2026_06_frozen.py`
  fails if the schema file bytes change.

## See also

- `app-manifest-2025-02.md` — predecessor on the container-shape track.
- `.agents/skills/build-tesslate-app/references/manifest-2026-06.md` —
  exhaustive author-facing field reference, including worked examples for
  mirofish (credentials[]) and deer-flow (readiness_port).
- `.agents/skills/build-tesslate-app/SKILL.md` — top-level skill that
  routes between action-shape (2026-05) and container-shape (2026-06).
