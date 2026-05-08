# OpenSail Specifications

Frozen schema specifications that govern published OpenSail artifacts. Any change to a frozen spec is a breaking change: cut a new versioned file instead of mutating the existing one. Each spec has a hash-pin test that blocks merges that mutate the file in place.

## Active specs

The manifest specs split into two **shapes** as of 2026-05. The two are mutually
exclusive (top-level `additionalProperties: false`); pick by what your app does.

### Container-shape track (long-running pods, PVC state, surfaces)

| Spec | Version | Status | File |
|------|---------|--------|------|
| Tesslate App Manifest v1 | 2025-01 | Frozen, accepted by parser | [app-manifest-2025-01.md](app-manifest-2025-01.md) |
| Tesslate App Manifest v2 | 2025-02 | Frozen, accepted by parser; predecessor of 2026-06 | [app-manifest-2025-02.md](app-manifest-2025-02.md) |
| Tesslate App Manifest v2.1 | 2026-06 | Frozen, current for new container-shape seeds | [app-manifest-2026-06.md](app-manifest-2026-06.md) |

### Action-shape track (App Runtime Contract: typed RPC actions, no persistent pods)

| Spec | Version | Status | File |
|------|---------|--------|------|
| Tesslate App Manifest v3 | 2026-05 | Frozen, current for new action-shape apps | (see schema and `.agents/skills/build-tesslate-app/references/manifest-2026-05.md`) |

## Canonical source files

| Spec | Authoritative JSON Schema | Pydantic mirror | Parser | Hash-pin test |
|------|----------------------------|-----------------|--------|----------------|
| 2025-01 | `orchestrator/app/services/apps/app_manifest_2025_01.schema.json` | `orchestrator/app/services/apps/app_manifest.py::AppManifest` | `orchestrator/app/services/apps/manifest_parser.py` | `orchestrator/tests/apps/test_manifest_schema_frozen.py` |
| 2025-02 | `orchestrator/app/services/apps/app_manifest_2025_02.schema.json` | (structural-only; consumers read raw dict) | `orchestrator/app/services/apps/manifest_parser.py` | `orchestrator/tests/apps/test_manifest_schema_2025_02_frozen.py` |
| 2026-05 | `orchestrator/app/services/apps/app_manifest_2026_05.schema.json` | `orchestrator/app/services/apps/app_manifest.py::AppManifest2026_05` | `orchestrator/app/services/apps/manifest_parser.py` | (none yet — not frozen at time of writing) |
| 2026-06 | `orchestrator/app/services/apps/app_manifest_2026_06.schema.json` | (structural-only; consumers read raw dict) | `orchestrator/app/services/apps/manifest_parser.py` | `orchestrator/tests/apps/test_manifest_schema_2026_06_frozen.py` |

## How to evolve a spec

1. Do not edit the frozen file. Add a new `app_manifest_YYYY_MM.schema.json` with the next calendar month.
2. Add a new `app-manifest-YYYY-MM.md` under `docs/specs/` describing the diff from the previous version.
3. Update `orchestrator/app/services/apps/manifest_parser.py` to recognize the new `manifest_schema_version`. Keep support for older versions.
4. Add a hash-pin test `orchestrator/tests/apps/test_manifest_schema_YYYY_MM_frozen.py`.
5. Update `orchestrator/app/config_features.py::MANIFEST_SCHEMA_SUPPORTED`.
6. Update the table above.

## Feature flags

Manifest schema availability is advertised by the feature flag registry in `orchestrator/app/config_features.py`. The union of `MANIFEST_SCHEMA_SUPPORTED` plus always-on capabilities (including `manifest_schema_2025_02`) is surfaced at `GET /api/version` and compared against a manifest's `compatibility.required_features[]` at publish and install time.

## Related documents

- [Tesslate Apps CLAUDE context](../apps/CLAUDE.md)
- [Environment variables](../guides/environment-variables.md) for app-related feature flags
- [Seed apps](../../orchestrator/app/seeds/apps) for reference manifests validated against the active schemas
