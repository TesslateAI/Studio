# Deployment Targets Router

**File**: `orchestrator/app/routers/deployment_targets.py`

**Base path**: `/api/projects/{slug}/deployment-targets`

## Purpose

Manage "deployment target" nodes in the Project graph canvas. A target represents a destination (Vercel, Netlify, Cloudflare Pages, GitHub Pages, etc.) that can be connected to one or more project containers, configured, validated, and triggered to deploy.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/` | owner | Create a target node on the project canvas. |
| GET | `/` | owner | List targets for the project. |
| GET | `/providers` | owner | List supported provider types with capabilities. |
| GET | `/{target_id}` | owner | Get a single target. |
| PATCH | `/{target_id}` | owner | Update target configuration. |
| DELETE | `/{target_id}` | owner | Delete the target. |
| POST | `/{target_id}/connect/{container_id}` | owner | Attach a container to this target. |
| DELETE | `/{target_id}/disconnect/{container_id}` | owner | Detach a container. |
| GET | `/{target_id}/validate/{container_id}` | owner | Preflight: confirms build command, framework, and credentials. |
| POST | `/{target_id}/deploy` | owner | Trigger a deployment (builds locally, then pushes). |
| GET | `/{target_id}/history` | owner | Prior deployment records for the target. |
| POST | `/{target_id}/rollback/{deployment_id}` | owner | Re-promote a prior deployment as current. |

## Auth

All endpoints require `current_active_user` and project ownership (via `get_project_by_slug`).

## Related

- Models: `DeploymentTarget`, `Deployment`, `Container`, `ContainerConnection` in [models.py](../../../orchestrator/app/models.py).
- Provider glue: [deployments.md](deployments.md), [deployment-credentials.md](deployment-credentials.md).
- Frontend graph canvas: `app/src/components/panels/ProjectGraphCanvas.tsx`.
